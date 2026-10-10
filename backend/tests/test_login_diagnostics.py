"""POST /auth/login stage diagnostics: correlated, ordered, timed and value-free.

Real cookie/JWT path (no principal override); Supabase Auth HTTP is an httpx.MockTransport as in
test_auth_security.py."""

from __future__ import annotations

import logging

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from app.core import deps, login_stages
from app.core.config import get_settings
from app.core.errors import ApiError
from app.db import session as db_session
from app.integrations.supabase_auth import AuthUnavailable, SupabaseAuthClient, TokenVerifier
from app.main import app
from app.modules.accounts import router as accounts_router
from tests.conftest import ensure_auth_user
from tests.test_auth_security import PUBLISHABLE, SECRET, SUPABASE, FakeSupabase

EMAIL = "kid@example.test"
PASSWORD = "correct horse"
RID = "login-diag-0001"
CANARY_HOST = "db.canaryprojectref.supabase.co"
CANARY_PW = "canary-" + "dsn-password-in-driver-message"
CANARY_SQL = "insert into profiles (email) values ('kid@example.test')"
ALL_STAGES = ["db_dependency", "supabase_sign_in", "jwt_verify", "ensure_profile", "reward_evaluation", "response"]


@pytest.fixture
def fake(monkeypatch, engine):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", PUBLISHABLE)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    get_settings.cache_clear()
    deps.get_verifier.cache_clear()
    f = FakeSupabase()
    ensure_auth_user(engine, f.user)
    app.dependency_overrides[deps.get_auth_client] = lambda: SupabaseAuthClient(
        get_settings(), transport=httpx.MockTransport(f.handler))
    yield f
    get_settings.cache_clear()
    deps.get_verifier.cache_clear()


def _db_timeout() -> sa_exc.OperationalError:
    """Driver error whose message carries everything that must never reach a log."""
    return sa_exc.OperationalError(CANARY_SQL, {"email": EMAIL}, psycopg.OperationalError(
        f"consuming input failed: SSL SYSCALL error: Operation timed out host={CANARY_HOST} pw={CANARY_PW}"))


def _login(caplog, password: str = PASSWORD):
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    client.headers["X-CSRF-Token"] = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    caplog.clear()
    caplog.set_level(logging.DEBUG)
    resp = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": password},
                       headers={"X-Request-ID": RID})
    return client, resp


def _stage_events(caplog) -> list[dict[str, str]]:
    out = []
    for rec in caplog.records:
        if rec.name == "app.auth.login":
            head, *pairs = rec.getMessage().split(" ")
            assert head == "login_stage"
            out.append(dict(p.split("=", 1) for p in pairs))
    return out


def _sequence(events) -> list[tuple[str, str]]:
    return [(e["stage"], e["event"]) for e in events]


def _assert_safe(caplog, resp, *extra: str) -> None:
    logged = "\n".join(rec.getMessage() + str(rec.exc_text or "") for rec in caplog.records)
    secrets = [EMAIL, PASSWORD, CANARY_HOST, CANARY_PW, CANARY_SQL, "insert into", SECRET, PUBLISHABLE, "rt-1",
               "Traceback", *extra]
    for cookie in resp.cookies.values():
        secrets.append(cookie)
    for s in secrets:
        assert s not in logged, s
    assert all(rec.exc_info is None for rec in caplog.records)


def test_successful_login_logs_every_stage_in_order(fake, caplog):
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text
    assert r.headers["x-request-id"] == RID
    events = _stage_events(caplog)
    assert _sequence(events) == [(s, ev) for s in ALL_STAGES for ev in ("start", "ok")]
    assert {e["request_id"] for e in events} == {RID}
    for e in events:
        if e["event"] == "ok":
            assert float(e["elapsed_ms"]) >= 0
        else:
            assert "elapsed_ms" not in e
    assert len(r.cookies) == 3  # tfe_at (JWT), tfe_rt, tfe_csrf: all asserted absent from the logs
    _assert_safe(caplog, r, r.json()["csrf_token"])


def test_db_dependency_failure_is_located_before_the_handler(fake, monkeypatch, caplog):
    db_session.configure_engine(db_session._engine)  # drop the cached "schema ok"

    def schema_status(_engine):
        raise _db_timeout()

    monkeypatch.setattr(db_session, "schema_status", schema_status)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    events = _stage_events(caplog)
    assert _sequence(events) == [("db_dependency", "start"), ("db_dependency", "error")]
    err = events[-1]
    assert err["request_id"] == RID and err["outcome"] == "raised"
    assert err["error"] == "ApiError" and err["status"] == "503" and err["code"] == "database_unavailable"
    assert err["cause"] == "OperationalError" and err["category"] == "timeout"
    assert err["driver_error"] == "OperationalError" and err["sqlstate"] == "None"
    assert float(err["elapsed_ms"]) >= 0
    assert fake.calls == []  # Supabase was never contacted
    _assert_safe(caplog, r)


@pytest.mark.parametrize(("case", "status", "code", "stage", "fields"), [
    ("wrong_password", 401, "invalid_credentials", "supabase_sign_in", {"error": "InvalidCredentials"}),
    ("supabase_down", 503, "auth_unavailable", "supabase_sign_in",
     {"error": "AuthUnavailable", "cause": "ConnectError"}),
    ("jwks_down", 503, "auth_unavailable", "jwt_verify",
     {"error": "ApiError", "status": "503", "code": "auth_unavailable", "cause": "AuthUnavailable"}),
])
def test_auth_failures_are_located(fake, monkeypatch, caplog, case, status, code, stage, fields):
    password = PASSWORD
    if case == "wrong_password":
        password = "wrong-" + "password-canary"
    elif case == "supabase_down":
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"cannot reach {SUPABASE}", request=request)

        app.dependency_overrides[deps.get_auth_client] = lambda: SupabaseAuthClient(
            get_settings(), transport=httpx.MockTransport(down))
    else:
        def jwks_down(self, token, *, allow_expired=False):
            raise AuthUnavailable()

        monkeypatch.setattr(TokenVerifier, "verify", jwks_down)
    _client, r = _login(caplog, password)
    assert r.status_code == status and r.json()["code"] == code
    events = _stage_events(caplog)
    done = ALL_STAGES[:ALL_STAGES.index(stage)]
    assert _sequence(events) == [(s, ev) for s in done for ev in ("start", "ok")] + [(stage, "start"),
                                                                                      (stage, "error")]
    err = events[-1]
    assert err["request_id"] == RID and err["outcome"] == "raised"
    assert {k: err.get(k) for k in fields} == fields
    _assert_safe(caplog, r, password)


def test_ensure_profile_db_timeout_is_located_and_correlated(fake, monkeypatch, caplog):
    def ensure_profile(_db, _principal):
        raise _db_timeout()

    monkeypatch.setattr(accounts_router, "ensure_profile", ensure_profile)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    assert r.json()["request_id"] == RID
    events = _stage_events(caplog)
    assert _sequence(events)[-2:] == [("ensure_profile", "start"), ("ensure_profile", "error")]
    assert ("reward_evaluation", "start") not in _sequence(events)
    err = events[-1]
    assert err == {"request_id": RID, "stage": "ensure_profile", "event": "error", "outcome": "raised",
                   "elapsed_ms": err["elapsed_ms"], "error": "OperationalError", "category": "timeout",
                   "driver_error": "OperationalError", "sqlstate": "None"}
    # the pre-existing global DB handler line carries the same request id, so both can be joined
    handler = [rec.getMessage() for rec in caplog.records if rec.name == "app.db"]
    assert any("database unavailable" in m and f"request_id={RID}" in m and "category=timeout" in m for m in handler)
    _assert_safe(caplog, r)


def test_swallowed_reward_failure_is_reported_as_swallowed_and_login_succeeds(fake, monkeypatch, caplog):
    import app.modules.rewards.service as rewards

    def evaluate_due(*_a, **_k):
        raise _db_timeout()

    monkeypatch.setattr(rewards, "evaluate_due", evaluate_due)
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text
    events = _stage_events(caplog)
    expected = [(s, ev) for s in ALL_STAGES for ev in ("start", "ok")]
    expected[expected.index(("reward_evaluation", "ok"))] = ("reward_evaluation", "error")
    assert _sequence(events) == expected
    err = next(e for e in events if e["stage"] == "reward_evaluation" and e["event"] == "error")
    assert err["outcome"] == "swallowed" and err["error"] == "OperationalError" and err["category"] == "timeout"
    assert err["request_id"] == RID
    # the existing error line is kept unchanged
    assert any(rec.name == "app.auth" and rec.getMessage() == f"reward evaluation at login failed request_id={RID} "
               "error=OperationalError" for rec in caplog.records)
    _assert_safe(caplog, r)


def test_failing_rollback_after_reward_failure_is_reported_as_raised(fake, monkeypatch, caplog):
    import app.modules.rewards.service as rewards

    def evaluate_due(*_a, **_k):
        raise _db_timeout()

    def rollback(_self):
        raise _db_timeout()

    monkeypatch.setattr(rewards, "evaluate_due", evaluate_due)
    monkeypatch.setattr(Session, "rollback", rollback)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"  # behaviour unchanged
    events = _stage_events(caplog)
    assert _sequence(events)[-1] == ("reward_evaluation", "error") and events[-1]["outcome"] == "raised"
    _assert_safe(caplog, r)


def test_describe_failure_never_includes_messages_or_unsafe_codes():
    exc = ApiError(503, "Bad Code <script>", f"message with {EMAIL}")
    exc.__cause__ = RuntimeError(f"password={PASSWORD}")
    text = login_stages.describe_failure(exc)
    assert text == "error=ApiError status=503 code=? cause=RuntimeError"
    plain = login_stages.describe_failure(ValueError(f"{EMAIL} {PASSWORD}"))
    assert plain == "error=ValueError"


def test_login_still_honours_get_db_dependency_override(fake, engine, caplog):
    """Diagnostics must not change dependency identity: an override of get_db still applies to login."""
    used: list[Session] = []

    def override_db():
        with Session(engine, expire_on_commit=False) as session:
            used.append(session)
            yield session

    app.dependency_overrides[db_session.get_db] = override_db
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text
    assert len(used) == 1
    # the override replaced get_db, so its stage is absent; the handler stages still run
    assert _sequence(_stage_events(caplog)) == [(s, ev) for s in ALL_STAGES[1:] for ev in ("start", "ok")]


def test_other_routes_using_get_db_log_no_login_stages(fake, caplog):
    client, r = _login(caplog)
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    caplog.clear()
    assert client.get("/api/v1/me").status_code == 200
    assert client.post("/api/v1/auth/refresh").status_code == 200
    assert _stage_events(caplog) == []
