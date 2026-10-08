"""Real cookie/JWT path: no principal override here. Supabase Auth HTTP is replaced by an
httpx.MockTransport (test-only) so the production client code is exercised end-to-end."""

from __future__ import annotations

import json
import time
import uuid

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import deps
from app.core.config import get_settings
from app.integrations.supabase_auth import AuthError, SupabaseAuthClient, TokenVerifier
from app.main import app
from tests.conftest import FIXED_NOW, ensure_auth_user

SUPABASE = "https://abcdefghijklmnopqrst.supabase.co"
SECRET = "test-only-hs256-secret-with-enough-length-0123456789"
PUBLISHABLE = "sb_publishable_test_only"


def mint(sub: uuid.UUID, *, exp_delta=3600, aud="authenticated", iss=f"{SUPABASE}/auth/v1", role="authenticated",
         key=SECRET, alg="HS256", headers=None, session_id: str | None = None) -> str:
    now = int(FIXED_NOW.timestamp()) if exp_delta < 0 else int(time.time())
    claims = {"sub": str(sub), "aud": aud, "iss": iss, "role": role, "exp": now + exp_delta, "iat": now,
              "email": "kid@example.test", "user_metadata": {"display_name": "Алексей", "role": "admin"},
              "jti": uuid.uuid4().hex}
    if session_id:
        claims["session_id"] = session_id
    return jwt.encode(claims, key, algorithm=alg, headers=headers)


@pytest.fixture
def configured(monkeypatch, engine):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", PUBLISHABLE)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    get_settings.cache_clear()
    deps.get_verifier.cache_clear()
    yield
    get_settings.cache_clear()
    deps.get_verifier.cache_clear()


class FakeSupabase:
    """Deliberately lenient: it keeps accepting old refresh tokens, so the backend's own revocation
    is what blocks replay. `logout_mode`: ok | http_500 | network_error."""

    def __init__(self) -> None:
        self.user = uuid.uuid4()
        self.session_id = str(uuid.uuid4())
        self.calls: list[httpx.Request] = []
        self.logout_mode = "ok"
        self.with_session_id = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers["apikey"] == PUBLISHABLE
        if request.url.path == "/auth/v1/token":
            body = json.loads(request.content)
            grant = request.url.params["grant_type"]
            if grant == "password" and body == {"email": "kid@example.test", "password": "correct horse"}:
                return httpx.Response(200, json=self.tokens())
            if grant == "refresh_token" and body == {"refresh_token": "rt-1"}:
                return httpx.Response(200, json=self.tokens())
            return httpx.Response(400, json={"error": "invalid_grant"})
        if request.url.path == "/auth/v1/logout":
            assert request.headers["authorization"].startswith("Bearer ")
            if self.logout_mode == "network_error":
                raise httpx.ConnectError("upstream down", request=request)
            return httpx.Response(500 if self.logout_mode == "http_500" else 204)
        return httpx.Response(404)

    def tokens(self) -> dict:
        sid = self.session_id if self.with_session_id else None
        return {"access_token": mint(self.user, session_id=sid), "refresh_token": "rt-1", "expires_in": 3600,
                "token_type": "bearer", "user": {"id": str(self.user)}}


@pytest.fixture
def supabase(configured, engine):
    fake = FakeSupabase()
    ensure_auth_user(engine, fake.user)
    app.dependency_overrides[deps.get_auth_client] = lambda: SupabaseAuthClient(
        get_settings(), transport=httpx.MockTransport(fake.handler))
    return fake


def browser() -> TestClient:
    c = TestClient(app, base_url="https://testserver")
    token = c.get("/api/v1/auth/csrf").json()["csrf_token"]
    c.headers["X-CSRF-Token"] = token
    return c


def test_login_sets_secure_httponly_cookies_and_provisions(supabase):
    c = browser()
    r = c.post("/api/v1/auth/login", json={"email": "kid@example.test", "password": "correct horse"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["me"]["role"] == "child"  # user_metadata.role=admin is ignored
    assert body["me"]["display_name"] == "Алексей"
    assert "access_token" not in r.text and "rt-1" not in r.text  # tokens never in JSON
    cookies = r.headers.get_list("set-cookie")
    at = next(x for x in cookies if x.startswith("tfe_at="))
    rt = next(x for x in cookies if x.startswith("tfe_rt="))
    assert "HttpOnly" in at and "Secure" in at and "SameSite=lax" in at and "Path=/api" in at
    assert "HttpOnly" in rt and "SameSite=strict" in rt and "Path=/api/v1/auth" in rt
    c.headers["X-CSRF-Token"] = body["csrf_token"]
    assert c.get("/api/v1/me").json()["id"] == str(supabase.user)
    assert len(c.get("/api/v1/activities").json()["items"]) == 11


def test_wrong_password_and_rate_limit(supabase, monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "3")
    get_settings.cache_clear()
    c = browser()
    codes = [c.post("/api/v1/auth/login", json={"email": "kid@example.test", "password": "nope"}).status_code
             for _ in range(4)]
    assert codes == [401, 401, 401, 429]


def test_csrf_required_for_mutations_including_login(supabase, monkeypatch):
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/api/v1/auth/login", json={"email": "kid@example.test", "password": "correct horse"})
    assert r.status_code == 403 and r.json()["code"] == "csrf_failed"
    c.get("/api/v1/auth/csrf")
    c.headers["X-CSRF-Token"] = "x" * 43
    assert c.post("/api/v1/auth/login", json={}).json()["code"] == "csrf_failed"
    good = browser()
    monkeypatch.setenv("APP_BASE_URL", "https://app.example")
    get_settings.cache_clear()
    r = good.post("/api/v1/auth/login", json={"email": "kid@example.test", "password": "correct horse"},
                  headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = good.post("/api/v1/auth/login", json={"email": "kid@example.test", "password": "correct horse"},
                  headers={"Origin": "https://app.example"})
    assert r.status_code == 200


def test_refresh_and_logout(supabase):
    c = browser()
    login = c.post("/api/v1/auth/login", json={"email": "kid@example.test", "password": "correct horse"})
    c.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    r = c.post("/api/v1/auth/refresh")
    assert r.status_code == 200 and "expires_at" in r.json()
    act = next(a for a in c.get("/api/v1/activities").json()["items"] if a["code"] == "math")
    c.post(f"/api/v1/activities/{act['id']}/timer/start", json={"revision": 0},
           headers={"Idempotency-Key": uuid.uuid4().hex})
    r = c.post("/api/v1/auth/logout")
    assert r.status_code == 204
    assert any(x.startswith('tfe_at=""') or "Max-Age=0" in x for x in r.headers.get_list("set-cookie"))
    assert any(call.url.path == "/auth/v1/logout" for call in supabase.calls)
    # timers were paused server-side at sign-out (new sign-in = new Supabase session)
    supabase.session_id = str(uuid.uuid4())
    c2 = browser()
    l2 = c2.post("/api/v1/auth/login", json={"email": "kid@example.test", "password": "correct horse"})
    c2.headers["X-CSRF-Token"] = l2.json()["csrf_token"]
    assert c2.get(f"/api/v1/activities/{act['id']}/timer").json()["state"] == "paused"
    # refresh with unknown token clears the session
    c3 = browser()
    c3.cookies.set("tfe_rt", "bogus", domain="testserver.local", path="/api/v1/auth")
    assert c3.post("/api/v1/auth/refresh").status_code == 401


def test_cookie_token_verification(configured, engine):
    c = browser()
    uid = uuid.uuid4()
    ensure_auth_user(engine, uid)
    cases = {
        "session_expired": mint(uid, exp_delta=-3600),
        "not_authenticated": mint(uid, aud="other"),
    }
    for code, token in cases.items():
        c.cookies.set("tfe_at", token, domain="testserver.local", path="/api")
        r = c.get("/api/v1/me")
        assert r.status_code == 401 and r.json()["code"] == code
        c.cookies.clear()
    for bad in (mint(uid, iss="https://evil.supabase.co/auth/v1"), mint(uid, role="anon"),
                mint(uid, key="another-secret-another-secret-another-secret"), "not-a-jwt"):
        c.cookies.set("tfe_at", bad, domain="testserver.local", path="/api")
        assert c.get("/api/v1/me").json()["code"] == "not_authenticated"
        c.cookies.clear()
    c.cookies.set("tfe_at", mint(uid), domain="testserver.local", path="/api")
    assert c.get("/api/v1/me").status_code == 200


def test_asymmetric_es256_via_jwks(configured, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    uid = uuid.uuid4()
    token = mint(uid, key=key, alg="ES256", headers={"kid": "k1"})
    verifier = TokenVerifier(get_settings())

    class FakeJWKS:
        def get_signing_key_from_jwt(self, _token):
            return jwt.PyJWK.from_dict(json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key())), "ES256")

    monkeypatch.setattr(verifier, "_jwks_client", lambda: FakeJWKS())
    assert verifier.verify(token).user_id == uid
    other = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(AuthError):
        verifier.verify(mint(uid, key=other, alg="ES256", headers={"kid": "k1"}))
    # "none" / unexpected algorithms are rejected outright
    with pytest.raises(AuthError):
        verifier.verify(jwt.encode({"sub": str(uid)}, None, algorithm="none"))


def test_hs256_rejected_without_configured_secret(configured, monkeypatch):
    monkeypatch.delenv("SUPABASE_JWT_SECRET")
    get_settings.cache_clear()
    with pytest.raises(AuthError):
        TokenVerifier(get_settings()).verify(mint(uuid.uuid4()))


def test_settings_never_expose_secrets(configured, monkeypatch, make_api):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")
    get_settings.cache_clear()
    api = make_api()
    r = api.get("/api/v1/settings")
    assert r.status_code == 200
    text = r.text
    for secret in (SECRET, PUBLISHABLE, "sk-test-secret-value", SUPABASE):
        assert secret not in text
    assert r.json()["integrations"]["openai"] == {"configured": True}


def test_login_unconfigured_returns_503(engine):
    c = browser()
    r = c.post("/api/v1/auth/login", json={"email": "a@b.c", "password": "x"})
    assert r.status_code == 503 and r.json()["code"] == "service_not_configured"
    assert "SUPABASE_URL" in r.json()["details"]["missing"]


def test_body_limit(api):
    r = api.post("/api/v1/activities", content=b"{" + b" " * 70_000 + b"}",
                 headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["code"] == "payload_too_large"


# ---- logout revocation ---------------------------------------------------------------------------
def logged_in(fake) -> tuple[TestClient, str, str]:
    c = browser()
    r = c.post("/api/v1/auth/login", json={"email": "kid@example.test", "password": "correct horse"})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c, c.cookies.get("tfe_at"), c.cookies.get("tfe_rt")


def attacker(access: str | None = None, refresh: str | None = None) -> TestClient:
    """A different browser that replays cookies captured before logout."""
    a = browser()
    if access:
        a.cookies.set("tfe_at", access, domain="testserver.local", path="/api")
    if refresh:
        a.cookies.set("tfe_rt", refresh, domain="testserver.local", path="/api/v1/auth")
    return a


@pytest.mark.parametrize("logout_mode", ["ok", "http_500", "network_error"])
def test_copied_cookie_rejected_after_logout_even_if_upstream_fails(supabase, logout_mode):
    c, at, rt = logged_in(supabase)
    stolen = attacker(at, rt)
    assert stolen.get("/api/v1/me").status_code == 200  # works before logout
    supabase.logout_mode = logout_mode
    assert c.post("/api/v1/auth/logout").status_code == 204
    r = stolen.get("/api/v1/me")
    assert r.status_code == 401 and r.json()["code"] == "not_authenticated"
    # refresh-token replay is refused locally, without asking Supabase
    before = sum(1 for x in supabase.calls if x.url.params.get("grant_type") == "refresh_token")
    r = stolen.post("/api/v1/auth/refresh")
    assert r.status_code == 401 and r.json()["code"] == "session_expired"
    assert sum(1 for x in supabase.calls if x.url.params.get("grant_type") == "refresh_token") == before


def test_refresh_cannot_resurrect_revoked_session(supabase):
    c, at, _rt = logged_in(supabase)
    assert c.post("/api/v1/auth/logout").status_code == 204
    # a refresh token not seen at logout (e.g. captured earlier) still yields the revoked session_id
    stolen = attacker(refresh="rt-1-other")
    supabase_refresh = supabase.handler

    def accept_any(request):
        if request.url.params.get("grant_type") == "refresh_token":
            return httpx.Response(200, json=supabase.tokens())
        return supabase_refresh(request)

    app.dependency_overrides[deps.get_auth_client] = lambda: SupabaseAuthClient(
        get_settings(), transport=httpx.MockTransport(accept_any))
    r = stolen.post("/api/v1/auth/refresh")
    assert r.status_code == 401 and r.json()["code"] == "session_expired"
    issued = [x for x in r.headers.get_list("set-cookie") if x.startswith("tfe_at=") and 'tfe_at=""' not in x]
    assert issued == []  # no new access token handed out
    # Supabase was asked to revoke the resurrected tokens again
    assert any(x.url.path == "/auth/v1/logout" for x in supabase.calls)


def test_token_without_session_id_revoked_by_hash(supabase):
    supabase.with_session_id = False
    c, at, rt = logged_in(supabase)
    assert c.post("/api/v1/auth/logout").status_code == 204
    assert attacker(at).get("/api/v1/me").status_code == 401


def test_logout_with_expired_access_token_still_revokes_refresh(supabase, engine):
    c, _at, rt = logged_in(supabase)
    expired = mint(supabase.user, exp_delta=-3600, session_id=supabase.session_id)
    c.cookies.set("tfe_at", expired, domain="testserver.local", path="/api")
    assert c.post("/api/v1/auth/logout").status_code == 204
    assert attacker(refresh=rt).post("/api/v1/auth/refresh").status_code == 401
    # forged (unsigned) tokens cannot be used to fill the revocation table
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app.db.models import RevokedSession

    with Session(engine) as db:
        n = db.execute(select(func.count()).select_from(RevokedSession)).scalar_one()
    junk = attacker(jwt.encode({"sub": str(uuid.uuid4())}, "wrong-key-wrong-key-wrong-key-wrong", "HS256"),
                    "junk-refresh")
    assert junk.post("/api/v1/auth/logout").status_code == 204
    with Session(engine) as db:
        assert db.execute(select(func.count()).select_from(RevokedSession)).scalar_one() == n


def test_new_login_after_logout_works(supabase):
    c, _, _ = logged_in(supabase)
    c.post("/api/v1/auth/logout")
    supabase.session_id = str(uuid.uuid4())  # Supabase issues a new session on sign-in
    c2, _, _ = logged_in(supabase)
    assert c2.get("/api/v1/me").status_code == 200


def test_unhandled_errors_are_logged_without_details(api, monkeypatch, caplog):
    import app.modules.activities.service as activities

    def boom(*_a, **_k):
        raise RuntimeError("SQL params: email=kid@example.test note=секрет")

    monkeypatch.setattr(activities, "list_activities", boom)
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    client.headers.update(api.client.headers)
    with caplog.at_level("DEBUG"):
        r = client.get("/api/v1/activities")
    assert r.status_code == 500 and r.json()["code"] == "internal_error"
    logged = "\n".join(rec.getMessage() + (rec.exc_text or "") for rec in caplog.records)
    assert "RuntimeError" in logged and r.json()["request_id"] in logged
    assert "kid@example.test" not in logged and "секрет" not in logged and "Traceback" not in logged
    assert all(rec.exc_info is None for rec in caplog.records)


# ---- logout must not claim success it cannot guarantee --------------------------------------------
def _cleared(resp) -> bool:
    cookies = resp.headers.get_list("set-cookie")
    return all(any(c.startswith(f"{name}=") and ("Max-Age=0" in c or f'{name}=""' in c) for c in cookies)
               for name in ("tfe_at", "tfe_rt", "tfe_csrf"))


def test_logout_returns_503_when_revocation_cannot_be_persisted(supabase, monkeypatch):
    from sqlalchemy.exc import OperationalError

    import app.modules.accounts.revocation as revocation

    c, at, _rt = logged_in(supabase)

    def db_down(*_a, **_k):
        raise OperationalError("delete from revoked_sessions", {}, Exception("connection lost"))

    monkeypatch.setattr(revocation, "delete", db_down)
    r = c.post("/api/v1/auth/logout")
    assert r.status_code == 503 and r.json()["code"] == "logout_incomplete"
    assert "не смог завершить сессию" in r.json()["message"]
    assert _cleared(r)  # this browser is signed out regardless
    assert any(x.url.path == "/auth/v1/logout" for x in supabase.calls)  # upstream still attempted
    # honest outcome: the session was NOT revoked locally, so no false sense of invalidation
    assert attacker(at).get("/api/v1/me").status_code == 200
    monkeypatch.undo()
    # once the DB works again, logging out with the same session succeeds and revokes it
    again = attacker(at)
    assert again.post("/api/v1/auth/logout").status_code == 204
    assert attacker(at).get("/api/v1/me").status_code == 401


def test_logout_returns_503_when_database_unavailable(supabase):
    from app.db.session import get_optional_db

    c, at, _rt = logged_in(supabase)
    def no_db():
        yield None  # what get_optional_db yields when the DB is not configured/reachable/migrated

    app.dependency_overrides[get_optional_db] = no_db
    r = c.post("/api/v1/auth/logout")
    assert r.status_code == 503 and r.json()["code"] == "logout_incomplete" and _cleared(r)
    del app.dependency_overrides[get_optional_db]
    assert attacker(at).get("/api/v1/me").status_code == 200  # not claimed as revoked


def test_logout_returns_503_when_token_cannot_be_verified(supabase, monkeypatch):
    from app.integrations.supabase_auth import AuthUnavailable

    c, _at, _rt = logged_in(supabase)

    def jwks_down(self, token, *, allow_expired=False):
        raise AuthUnavailable()

    monkeypatch.setattr(TokenVerifier, "verify", jwks_down)
    r = c.post("/api/v1/auth/logout")
    assert r.status_code == 503 and r.json()["code"] == "logout_incomplete" and _cleared(r)


def test_logout_without_session_or_with_forged_token_is_204(configured):
    assert browser().post("/api/v1/auth/logout").status_code == 204
    forged = attacker(jwt.encode({"sub": str(uuid.uuid4())}, "x" * 40, "HS256"))
    r = forged.post("/api/v1/auth/logout")
    assert r.status_code == 204 and _cleared(r)


def test_repeated_logout_of_same_session_is_204(supabase):
    c, at, rt = logged_in(supabase)
    assert c.post("/api/v1/auth/logout").status_code == 204
    # a second device holding the same (already revoked, still unexpired) tokens logs out too
    assert attacker(at, rt).post("/api/v1/auth/logout").status_code == 204
