"""POST /auth/login resilience: profile provisioning, DB failures and the concurrent-first-login race.

Behavioural regressions only (status codes, persisted state, value-free logs). Real cookie/JWT path (no principal
override); Supabase Auth HTTP is an httpx.MockTransport as in test_auth_security.py."""

from __future__ import annotations

import logging
import uuid

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import exc as sa_exc
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import deps
from app.core.config import get_settings
from app.db import session as db_session
from app.db.models import Activity, ChildWorld, Profile, WalletAccount
from app.integrations.supabase_auth import AuthUnavailable, Principal, SupabaseAuthClient, TokenVerifier
from app.main import app
from app.modules.accounts import router as accounts_router
from app.modules.accounts.provisioning import DEFAULT_ACTIVITIES, ensure_profile
from tests.conftest import ensure_auth_user
from tests.test_auth_security import PUBLISHABLE, SECRET, SUPABASE, FakeSupabase

EMAIL = "kid@example.test"
PASSWORD = "correct horse"
RID = "login-resilience-0001"
CANARY_HOST = "db.canaryprojectref.supabase.co"
CANARY_PW = "canary-" + "dsn-password-in-driver-message"
CANARY_SQL = "insert into profiles (email) values ('kid@example.test')"
DISPLAY_NAME = "Алексей"  # user_metadata.display_name in the minted JWT: personal, must never be logged
OLD_EMAIL = "old-address@example.test"
N_ACT = len(DEFAULT_ACTIVITIES)


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


def _provision_directly(engine, user_id: uuid.UUID, email: str) -> None:
    """Pre-existing profile (an earlier login)."""
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


def _assert_fully_provisioned(engine, user_id: uuid.UUID, email: str) -> None:
    with Session(engine) as db:
        profile = db.get(Profile, user_id)
        assert profile is not None and profile.email == email and profile.active_world is not None
        assert len(db.scalars(select(Activity).where(Activity.child_id == user_id)).all()) == N_ACT
        assert db.get(WalletAccount, user_id) is not None
        assert len(db.scalars(select(ChildWorld).where(ChildWorld.child_id == user_id)).all()) == 1


def _assert_not_provisioned(engine, user_id: uuid.UUID) -> None:
    with Session(engine) as db:
        assert db.get(Profile, user_id) is None
        assert db.scalars(select(Activity).where(Activity.child_id == user_id)).all() == []


def test_first_login_provisions_profile_and_logs_nothing_personal(fake, engine, caplog):
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text
    assert r.headers["x-request-id"] == RID
    assert len(r.cookies) == 3  # tfe_at (JWT), tfe_rt, tfe_csrf: all asserted absent from the logs
    _assert_fully_provisioned(engine, fake.user, EMAIL)
    _assert_safe(caplog, r, r.json()["csrf_token"], str(fake.user))


def test_login_of_existing_profile_with_changed_email_updates_email(fake, engine, caplog):
    _provision_directly(engine, fake.user, OLD_EMAIL)
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text
    _assert_fully_provisioned(engine, fake.user, EMAIL)
    _assert_safe(caplog, r, str(fake.user), OLD_EMAIL)


@pytest.mark.parametrize("scenario", ["new", "existing_same_email", "existing_new_email"])
def test_ensure_profile_direct_outcomes(engine, scenario):
    uid = uuid.uuid4()
    ensure_auth_user(engine, uid)
    if scenario != "new":
        _provision_directly(engine, uid, "direct@example.test" if scenario == "existing_same_email" else OLD_EMAIL)
    with Session(engine, expire_on_commit=False) as db:
        profile = ensure_profile(db, Principal(user_id=uid, email="direct@example.test", user_metadata={}))
        assert profile.id == uid and profile.email == "direct@example.test"
    _assert_fully_provisioned(engine, uid, "direct@example.test")


@pytest.mark.parametrize("failing", ["profile", "activity_first", "activity_last", "wallet", "active_world"])
def test_flush_timeout_during_provisioning_is_503_and_persists_nothing(fake, engine, monkeypatch, caplog, failing):
    """A DB timeout at any provisioning flush maps to 503 database_unavailable and leaves no partial profile."""
    def pending(session: Session) -> bool:
        if failing == "profile":
            return any(isinstance(o, Profile) for o in session.new)
        if failing.startswith("activity_"):
            code = DEFAULT_ACTIVITIES[0 if failing == "activity_first" else N_ACT - 1][0]
            return any(isinstance(o, Activity) and o.code == code for o in session.new)
        if failing == "wallet":
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
    assert r.json()["request_id"] == RID
    monkeypatch.setattr(Session, "flush", real_flush)
    _assert_not_provisioned(engine, fake.user)
    _assert_safe(caplog, r, str(fake.user))


@pytest.mark.parametrize("existing_email", [None, OLD_EMAIL])
def test_commit_timeout_during_login_is_503(fake, engine, monkeypatch, caplog, existing_email):
    if existing_email:
        _provision_directly(engine, fake.user, existing_email)

    def commit(_self):
        raise _db_timeout()

    monkeypatch.setattr(Session, "commit", commit)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
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


def test_concurrent_first_login_uses_the_winners_profile(fake, engine, monkeypatch, caplog):
    _provision_directly(engine, fake.user, EMAIL)  # the concurrent request's profile, already committed
    _lose_profile_race(monkeypatch, every_time=False)
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text
    assert r.json()["me"]["id"] == str(fake.user)
    _assert_safe(caplog, r, str(fake.user))


def test_integrity_reread_miss_propagates_as_generic_500(fake, engine, monkeypatch, caplog):
    _provision_directly(engine, fake.user, EMAIL)
    _lose_profile_race(monkeypatch, every_time=True)
    _client, r = _login(caplog)
    assert r.status_code == 500 and r.json()["code"] == "internal_error"
    _assert_safe(caplog, r, str(fake.user))


def test_integrity_rollback_timeout_is_503(fake, engine, monkeypatch, caplog):
    _provision_directly(engine, fake.user, EMAIL)
    _lose_profile_race(monkeypatch, every_time=False)

    def rollback(_self):
        raise _db_timeout()

    monkeypatch.setattr(Session, "rollback", rollback)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    _assert_safe(caplog, r, str(fake.user))


def test_schema_check_timeout_fails_login_before_contacting_supabase(fake, monkeypatch, caplog):
    db_session.configure_engine(db_session._engine)  # drop the cached "schema ok"

    def schema_status(_engine):
        raise _db_timeout()

    monkeypatch.setattr(db_session, "schema_status", schema_status)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    assert fake.calls == []  # Supabase was never contacted
    _assert_safe(caplog, r)


@pytest.mark.parametrize(("case", "status", "code"), [
    ("wrong_password", 401, "invalid_credentials"),
    ("supabase_down", 503, "auth_unavailable"),
    ("jwks_down", 503, "auth_unavailable"),
])
def test_auth_failures_map_to_stable_codes(fake, monkeypatch, caplog, case, status, code):
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
    _assert_safe(caplog, r, password)


def test_ensure_profile_db_timeout_is_503_correlated_with_request_id(fake, monkeypatch, caplog):
    def fake_ensure_profile(_db, _principal):
        raise _db_timeout()

    monkeypatch.setattr(accounts_router, "ensure_profile", fake_ensure_profile)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    assert r.json()["request_id"] == RID
    # the global DB handler line carries the request id and the value-free category
    handler = [rec.getMessage() for rec in caplog.records if rec.name == "app.db"]
    assert any("database unavailable" in m and f"request_id={RID}" in m and "category=timeout" in m for m in handler)
    _assert_safe(caplog, r)


def test_reward_evaluation_failure_never_blocks_login(fake, monkeypatch, caplog):
    import app.modules.rewards.service as rewards

    def evaluate_due(*_a, **_k):
        raise _db_timeout()

    monkeypatch.setattr(rewards, "evaluate_due", evaluate_due)
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text
    assert any(rec.name == "app.auth" and rec.getMessage() == f"reward evaluation at login failed request_id={RID} "
               "error=OperationalError" for rec in caplog.records)
    _assert_safe(caplog, r)


def test_failing_rollback_after_reward_failure_is_503(fake, monkeypatch, caplog):
    import app.modules.rewards.service as rewards

    def evaluate_due(*_a, **_k):
        raise _db_timeout()

    def rollback(_self):
        raise _db_timeout()

    monkeypatch.setattr(rewards, "evaluate_due", evaluate_due)
    monkeypatch.setattr(Session, "rollback", rollback)
    _client, r = _login(caplog)
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    _assert_safe(caplog, r)


def test_login_honours_get_db_dependency_override(fake, engine, caplog):
    used: list[Session] = []

    def override_db():
        with Session(engine, expire_on_commit=False) as session:
            used.append(session)
            yield session

    app.dependency_overrides[db_session.get_db] = override_db
    _client, r = _login(caplog)
    assert r.status_code == 200, r.text
    assert len(used) == 1
