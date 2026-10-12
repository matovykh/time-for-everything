"""POST /auth/login stage diagnostics: correlated, ordered, timed and value-free.

Real cookie/JWT path (no principal override); Supabase Auth HTTP is an httpx.MockTransport as in
test_auth_security.py."""

from __future__ import annotations

import logging
import uuid
from contextlib import nullcontext

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from app.core import deps, login_stages
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import login_limiter
from app.db import session as db_session
from app.db.models import Activity, Profile, WalletAccount
from app.integrations.supabase_auth import AuthUnavailable, Principal, SupabaseAuthClient, TokenVerifier
from app.main import app
from app.modules.accounts import router as accounts_router
from app.modules.accounts.provisioning import DEFAULT_ACTIVITIES, ensure_profile
from tests.conftest import ensure_auth_user
from tests.test_auth_security import PUBLISHABLE, SECRET, SUPABASE, FakeSupabase

EMAIL = "kid@example.test"
PASSWORD = "correct horse"
RID = "login-diag-0001"
CANARY_HOST = "db.canaryprojectref.supabase.co"
CANARY_PW = "canary-" + "dsn-password-in-driver-message"
CANARY_SQL = "insert into profiles (email) values ('kid@example.test')"
ALL_STAGES = ["db_dependency", "supabase_sign_in", "jwt_verify", "ensure_profile", "reward_evaluation", "response"]
DISPLAY_NAME = "Алексей"  # user_metadata.display_name in the minted JWT: personal, must never be logged
OLD_EMAIL = "old-address@example.test"
EP = "ensure_profile."
N_ACT = len(DEFAULT_ACTIVITIES)

# ensure_profile.* sub-stages (stage, index) for each path, in order.
NEW_PROFILE = (
    [(EP + "profile_get", None), (EP + "profile_add", None), (EP + "profile_flush", None)]
    + [(EP + s, i) for i in range(N_ACT) for s in ("activity_add", "activity_flush", "activity_children_add")]
    + [(EP + s, None) for s in ("wallet_world_add", "final_flush", "active_world_flush", "commit")]
)
EXISTING_SAME_EMAIL = [(EP + "profile_get", None)]
EXISTING_NEW_EMAIL = [(EP + "profile_get", None), (EP + "email_commit", None)]
EVENT_KEYS = {"request_id", "stage", "index", "event", "outcome", "elapsed_ms", "error", "status", "code", "cause",
              "category", "driver_error", "sqlstate"}


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


def _isequence(events) -> list[tuple[str, int | None, str]]:
    return [(e["stage"], int(e["index"]) if "index" in e else None, e["event"]) for e in events]


def _ok(stages) -> list[tuple[str, int | None, str]]:
    return [(s, i, ev) for s, i in stages for ev in ("start", "ok")]


def _login_ok(inner, top=ALL_STAGES) -> list[tuple[str, int | None, str]]:
    """Successful login: every top-level stage start/ok, with `inner` nested inside ensure_profile."""
    out = []
    for s in top:
        out.append((s, None, "start"))
        if s == "ensure_profile":
            out += _ok(inner)
        out.append((s, None, "ok"))
    return out


def _until_ensure_profile() -> list[tuple[str, int | None, str]]:
    return _ok((s, None) for s in ALL_STAGES[:3]) + [("ensure_profile", None, "start")]


def _provision_directly(engine, user_id: uuid.UUID, email: str) -> None:
    """Pre-existing profile (an earlier login), created without diagnostics."""
    with Session(engine, expire_on_commit=False) as db:
        ensure_profile(db, Principal(user_id=user_id, email=email, user_metadata={}))


def _assert_safe(caplog, resp, *extra: str) -> None:
    logged = "\n".join(rec.getMessage() + str(rec.exc_text or "") for rec in caplog.records)
    secrets = [EMAIL, PASSWORD, CANARY_HOST, CANARY_PW, CANARY_SQL, "insert into", SECRET, PUBLISHABLE, "rt-1",
               "Traceback", DISPLAY_NAME, "INSERT", "UPDATE", "SELECT", "UNIQUE", "profiles", *extra]
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
    # first login: the profile is provisioned, every sub-stage nested inside ensure_profile
    assert _isequence(events) == _login_ok(NEW_PROFILE)
    assert len(NEW_PROFILE) == 3 + 3 * 11 + 4
    assert sum(s.endswith("flush") for s, _ in NEW_PROFILE) == 14
    assert {e["request_id"] for e in events} == {RID}
    for e in events:
        if e["event"] == "ok":
            assert float(e["elapsed_ms"]) >= 0
        else:
            assert "elapsed_ms" not in e
    assert len(r.cookies) == 3  # tfe_at (JWT), tfe_rt, tfe_csrf: all asserted absent from the logs
    _assert_safe(caplog, r, r.json()["csrf_token"], str(fake.user))


def test_login_of_existing_profile_with_same_email_logs_only_profile_get(fake, engine, caplog):
    _provision_directly(engine, fake.user, EMAIL)
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text
    assert _isequence(_stage_events(caplog)) == _login_ok(EXISTING_SAME_EMAIL)
    _assert_safe(caplog, r, str(fake.user))


def test_login_of_existing_profile_with_changed_email_logs_email_commit(fake, engine, caplog):
    _provision_directly(engine, fake.user, OLD_EMAIL)
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text
    assert _isequence(_stage_events(caplog)) == _login_ok(EXISTING_NEW_EMAIL)
    with Session(engine) as db:
        assert db.get(Profile, fake.user).email == EMAIL  # behaviour unchanged: the email was updated
    _assert_safe(caplog, r, str(fake.user), OLD_EMAIL)


@pytest.mark.parametrize("stage, index", [
    (EP + "profile_flush", None),
    (EP + "activity_flush", 0),
    (EP + "activity_flush", 3),
    (EP + "activity_flush", N_ACT - 1),
    (EP + "final_flush", None),
    (EP + "active_world_flush", None),
])
def test_flush_failure_is_located_at_its_sub_stage(fake, monkeypatch, caplog, stage, index):
    """The failing flush is identified by WHAT is pending in the session at that moment, not by call count."""
    def pending(session: Session) -> bool:
        if stage == EP + "profile_flush":
            return any(isinstance(o, Profile) for o in session.new)
        if stage == EP + "activity_flush":
            return any(isinstance(o, Activity) and o.code == DEFAULT_ACTIVITIES[index][0] for o in session.new)
        if stage == EP + "final_flush":
            return any(isinstance(o, WalletAccount) for o in session.new)
        return any(isinstance(o, Profile) and o.active_world is not None for o in session.dirty)

    real_flush = Session.flush

    def flush(self, *a, **k):
        if pending(self):
            raise _db_timeout()
        return real_flush(self, *a, **k)

    monkeypatch.setattr(Session, "flush", flush)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    events = _stage_events(caplog)
    done = NEW_PROFILE[:NEW_PROFILE.index((stage, index))]
    assert _isequence(events) == _until_ensure_profile() + _ok(done) + [
        (stage, index, "start"), (stage, index, "error"), ("ensure_profile", None, "error")]
    err = events[-2]
    assert err["outcome"] == "raised" and err["error"] == "OperationalError" and err["category"] == "timeout"
    assert err["request_id"] == RID and float(err["elapsed_ms"]) >= 0
    assert ("index" in err) == (index is not None)
    _assert_safe(caplog, r, str(fake.user))


@pytest.mark.parametrize("existing_email, inner", [(None, NEW_PROFILE), (OLD_EMAIL, EXISTING_NEW_EMAIL)])
def test_commit_failure_is_located_at_its_sub_stage(fake, engine, monkeypatch, caplog, existing_email, inner):
    if existing_email:
        _provision_directly(engine, fake.user, existing_email)

    def commit(_self):
        raise _db_timeout()

    monkeypatch.setattr(Session, "commit", commit)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    events = _stage_events(caplog)
    stage, index = inner[-1]
    assert stage in (EP + "commit", EP + "email_commit")
    assert _isequence(events) == _until_ensure_profile() + _ok(inner[:-1]) + [
        (stage, index, "start"), (stage, index, "error"), ("ensure_profile", None, "error")]
    assert events[-2]["outcome"] == "raised" and events[-2]["error"] == "OperationalError"
    _assert_safe(caplog, r, str(fake.user), OLD_EMAIL)


def _lose_profile_race(monkeypatch, *, every_time: bool) -> None:
    """Session.get(Profile) misses although the row exists: a concurrent first login committed it in between."""
    real_get = Session.get
    misses = []

    def get(self, entity, ident, *a, **k):
        if entity is Profile and (every_time or not misses):
            misses.append(ident)
            return None
        return real_get(self, entity, ident, *a, **k)

    monkeypatch.setattr(Session, "get", get)


def test_concurrent_first_login_integrity_cleanup_is_logged_and_login_succeeds(fake, engine, monkeypatch, caplog):
    _provision_directly(engine, fake.user, EMAIL)  # the concurrent request's profile, already committed
    _lose_profile_race(monkeypatch, every_time=False)
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text  # behaviour unchanged: the winner's profile is used
    events = _stage_events(caplog)
    inner = [(EP + "profile_get", None, "start"), (EP + "profile_get", None, "ok"),
             (EP + "profile_add", None, "start"), (EP + "profile_add", None, "ok"),
             (EP + "profile_flush", None, "start"), (EP + "profile_flush", None, "error"),
             *_ok([(EP + "integrity_rollback", None), (EP + "integrity_reread", None)])]
    expected = _login_ok([])
    at = expected.index(("ensure_profile", None, "ok"))
    assert _isequence(events) == expected[:at] + inner + expected[at:]
    err = next(e for e in events if e["event"] == "error")
    assert err["stage"] == EP + "profile_flush" and err["outcome"] == "raised" and err["error"] == "IntegrityError"
    assert err["category"] == "database_error"
    _assert_safe(caplog, r, str(fake.user))


def test_integrity_reread_miss_reraises_at_ensure_profile(fake, engine, monkeypatch, caplog):
    _provision_directly(engine, fake.user, EMAIL)
    _lose_profile_race(monkeypatch, every_time=True)
    _client, r = _login(caplog)
    assert r.status_code == 500  # behaviour unchanged: the IntegrityError propagates (generic handler)
    events = _stage_events(caplog)
    assert _isequence(events)[-6:] == [
        (EP + "profile_flush", None, "error"),
        *_ok([(EP + "integrity_rollback", None), (EP + "integrity_reread", None)]),
        ("ensure_profile", None, "error")]
    assert events[-1]["error"] == "IntegrityError" and events[-1]["outcome"] == "raised"
    _assert_safe(caplog, r, str(fake.user))


def test_integrity_rollback_failure_is_located(fake, engine, monkeypatch, caplog):
    _provision_directly(engine, fake.user, EMAIL)
    _lose_profile_race(monkeypatch, every_time=False)

    def rollback(_self):
        raise _db_timeout()

    monkeypatch.setattr(Session, "rollback", rollback)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    events = _stage_events(caplog)
    assert _isequence(events)[-4:] == [
        (EP + "profile_flush", None, "error"), (EP + "integrity_rollback", None, "start"),
        (EP + "integrity_rollback", None, "error"), ("ensure_profile", None, "error")]
    assert events[-2]["error"] == "OperationalError" and events[-2]["category"] == "timeout"
    assert (EP + "integrity_reread", None, "start") not in _isequence(events)
    _assert_safe(caplog, r, str(fake.user))


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
    received = []

    def fake_ensure_profile(_db, _principal, *, login_request_id=None):
        received.append(login_request_id)
        raise _db_timeout()

    monkeypatch.setattr(accounts_router, "ensure_profile", fake_ensure_profile)
    _client, r = _login(caplog)
    assert received == [RID]  # the login route propagates its request id
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
    expected = _login_ok(NEW_PROFILE)
    expected[expected.index(("reward_evaluation", None, "ok"))] = ("reward_evaluation", None, "error")
    assert _isequence(events) == expected
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
    assert _isequence(_stage_events(caplog)) == _login_ok(NEW_PROFILE, ALL_STAGES[1:])


def test_other_routes_using_get_db_log_no_login_stages(fake, engine, caplog):
    client, r = _login(caplog)
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    # /me and /auth/logout both run ensure_profile (get_ctx; logout's timer pause) WITHOUT a login request id,
    # including the email-update commit path
    with Session(engine) as db:
        db.get(Profile, fake.user).email = OLD_EMAIL
        db.commit()
    caplog.clear()
    assert client.get("/api/v1/me").status_code == 200
    assert client.post("/api/v1/auth/refresh").status_code == 200
    with Session(engine) as db:
        db.get(Profile, fake.user).email = OLD_EMAIL
        db.commit()
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert [rec for rec in caplog.records if rec.name == "app.auth.login"] == []


def test_first_profile_via_me_logs_no_login_stages(make_api, caplog):
    caplog.set_level(logging.DEBUG)
    a = make_api()  # get_ctx provisions the profile on the first /me: the no-request-id path
    caplog.clear()
    assert a.get("/api/v1/me").status_code == 200
    with Session(db_session.get_engine()) as db:
        assert db.get(Profile, a.user_id) is not None
    assert [rec for rec in caplog.records if rec.name == "app.auth.login"] == []


# ---- direct ensure_profile calls: exact Session operations, with and without a login request id -----------------
class _RecordingSession:
    """Proxy that records every method ensure_profile calls on `db` (only explicit calls, not SQLAlchemy internals)."""

    def __init__(self, db: Session, timeline: list) -> None:
        self._db = db
        self._timeline = timeline

    def __getattr__(self, name: str):
        attr = getattr(self._db, name)
        if not callable(attr):
            return attr

        def call(*a, **k):
            self._timeline.append(("db", name))
            return attr(*a, **k)

        return call


class _TimelineHandler(logging.Handler):
    def __init__(self, timeline: list) -> None:
        super().__init__(logging.DEBUG)
        self._timeline = timeline

    def emit(self, record: logging.LogRecord) -> None:
        _head, *pairs = record.getMessage().split(" ")
        e = dict(p.split("=", 1) for p in pairs)
        self._timeline.append(("log", e["stage"], int(e["index"]) if "index" in e else None, e["event"]))


def _children(kind: str, weekdays) -> list[tuple[str, str]]:
    return [("db", "add")] * ((kind == "timed") + bool(weekdays))


def _expected_timeline(scenario: str) -> list[tuple]:
    """Interleaved stage logs and Session calls: each DB operation sits inside its own sub-stage."""
    def stage(name, ops, index=None):
        return [("log", EP + name, index, "start"), *ops, ("log", EP + name, index, "ok")]

    out = stage("profile_get", [("db", "get")])
    if scenario == "existing_same_email":
        return out
    if scenario == "existing_new_email":
        return out + stage("email_commit", [("db", "commit")])
    out += stage("profile_add", [("db", "add")]) + stage("profile_flush", [("db", "flush")])
    for i, (_c, _n, _ic, kind, *_rest, weekdays) in enumerate(DEFAULT_ACTIVITIES):
        out += (stage("activity_add", [("db", "add")], i) + stage("activity_flush", [("db", "flush")], i)
                + stage("activity_children_add", _children(kind, weekdays), i))
    out += (stage("wallet_world_add", [("db", "add"), ("db", "add")]) + stage("final_flush", [("db", "flush")])
            + stage("active_world_flush", [("db", "flush")]) + stage("commit", [("db", "commit")]))
    return out


def _run_direct(engine, caplog, scenario: str, rid: str | None) -> tuple[list, list[str]]:
    uid = uuid.uuid4()
    ensure_auth_user(engine, uid)
    if scenario != "new":
        _provision_directly(engine, uid, "direct@example.test" if scenario == "existing_same_email" else OLD_EMAIL)
    timeline: list = []
    statements: list[str] = []

    def on_sql(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    handler = _TimelineHandler(timeline)
    caplog.set_level(logging.DEBUG, logger="app.auth.login")
    login_stages.log.addHandler(handler)
    event.listen(engine, "before_cursor_execute", on_sql)
    try:
        with Session(engine, expire_on_commit=False) as db:
            profile = ensure_profile(_RecordingSession(db, timeline),
                                     Principal(user_id=uid, email="direct@example.test", user_metadata={}),
                                     login_request_id=rid)
            assert profile.id == uid and profile.email == "direct@example.test"
    finally:
        event.remove(engine, "before_cursor_execute", on_sql)
        login_stages.log.removeHandler(handler)
    with Session(engine) as db:  # committed result is the same either way
        assert db.get(Profile, uid).active_world is not None
        assert len(db.scalars(select(Activity).where(Activity.child_id == uid)).all()) == N_ACT
    return timeline, statements


@pytest.mark.parametrize("scenario", ["new", "existing_same_email", "existing_new_email"])
def test_ensure_profile_session_operations_are_identical_with_and_without_request_id(engine, caplog, scenario):
    with_rid, sql_with = _run_direct(engine, caplog, scenario, "diag-rid-0001")
    without_rid, sql_without = _run_direct(engine, caplog, scenario, None)
    # with a request id: every Session call sits inside exactly the expected sub-stage
    assert with_rid == _expected_timeline(scenario)
    # without one: nothing is logged, and the Session calls (kind, count, order) and SQL are identical
    assert all(item[0] == "db" for item in without_rid)
    assert without_rid == [item for item in with_rid if item[0] == "db"]
    assert sql_without == sql_with
    ops = [name for _db, name in without_rid]
    expected_counts = {
        "new": {"get": 1, "flush": 14, "commit": 1, "rollback": 0},
        "existing_same_email": {"get": 1, "flush": 0, "commit": 0, "rollback": 0},
        "existing_new_email": {"get": 1, "flush": 0, "commit": 1, "rollback": 0},  # no explicit flush
    }[scenario]
    assert {k: ops.count(k) for k in expected_counts} == expected_counts
    assert set(ops) <= {"get", "add", "flush", "commit"}


# ---- vocabulary / privacy of the helper itself -------------------------------------------------------------------
def test_stage_vocabulary_and_index_are_fixed(caplog):
    caplog.set_level(logging.DEBUG, logger="app.auth.login")
    with login_stages.LoginStage(RID, f"ensure_profile.{EMAIL}", index=3):
        pass
    with login_stages.LoginStage(RID, EP + "activity_add", index=f"{EMAIL}"):  # type: ignore[arg-type]
        pass
    with login_stages.LoginStage(RID, EP + "activity_add", index=True):  # bool is not an index
        pass
    with login_stages.LoginStage(RID, EP + "activity_flush", index=10):
        pass
    events = _stage_events(caplog)
    assert [(e["stage"], e.get("index")) for e in events[::2]] == [
        ("unknown", "3"), (EP + "activity_add", "?"), (EP + "activity_add", "?"), (EP + "activity_flush", "10")]
    _assert_safe(caplog, type("R", (), {"cookies": {}})())
    assert set(login_stages.ENSURE_PROFILE_STAGES) <= login_stages.STAGES
    assert {s for s, _ in NEW_PROFILE + EXISTING_NEW_EMAIL} <= set(login_stages.ENSURE_PROFILE_STAGES)


@pytest.mark.parametrize("rid", [None, ""])
def test_optional_stage_without_request_id_is_a_silent_no_op(caplog, rid):
    caplog.set_level(logging.DEBUG)
    ctx = login_stages.optional_stage(rid, EP + "profile_get")
    assert isinstance(ctx, nullcontext)
    with pytest.raises(ValueError), login_stages.optional_stage(rid, EP + "profile_flush", 1):
        raise ValueError("propagates untouched")
    assert caplog.records == []
    assert isinstance(login_stages.optional_stage(RID, EP + "profile_get"), login_stages.LoginStage)


def test_login_stage_events_use_only_value_free_fields(fake, engine, monkeypatch, caplog):
    """Across a success and an integrity-race login: fixed keys, fixed stage names, small integer indexes."""
    _client, r = _login(caplog)
    assert r.status_code == 200
    events = _stage_events(caplog)
    with Session(engine) as db:  # second login of the same user loses a simulated race (Session.get miss)
        db.get(Profile, fake.user).email = OLD_EMAIL
        db.commit()
    _lose_profile_race(monkeypatch, every_time=False)
    login_limiter.reset()
    _client, r2 = _login(caplog)
    assert r2.status_code == 200
    events += _stage_events(caplog)
    for e in events:
        assert set(e) <= EVENT_KEYS, e
        assert e["stage"] in login_stages.STAGES
        assert e["request_id"] == RID
        if "index" in e:
            assert e["stage"].startswith(EP + "activity_") and 0 <= int(e["index"]) < N_ACT
    values = [v for e in events for k, v in e.items() if k not in ("stage", "request_id")]
    personal = [EMAIL, OLD_EMAIL, DISPLAY_NAME, str(fake.user), *(a[0] for a in DEFAULT_ACTIVITIES),
                *(a[1] for a in DEFAULT_ACTIVITIES)]
    assert not any(p in v for p in personal for v in values)
    _assert_safe(caplog, r2, str(fake.user), OLD_EMAIL, *(a[1] for a in DEFAULT_ACTIVITIES))
