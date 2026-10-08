"""Server-side Supabase Auth integration.

* Password sign-in / refresh / logout go through the Supabase Auth (GoTrue) REST API using the
  publishable (or legacy anon) key in the `apikey` header. No service/secret key is used.
* Access tokens are verified locally: asymmetric signing keys via the project's JWKS endpoint
  `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`; optionally a legacy HS256 shared secret.
  Claims checked: signature, exp, aud (= "authenticated"), iss (= {SUPABASE_URL}/auth/v1),
  sub (UUID) and role == "authenticated".
"""

from __future__ import annotations

import hashlib
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt

from app.core.config import Settings

ASYMMETRIC_ALGS = ["ES256", "RS256"]
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,128}$")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthError(Exception):
    """Token invalid (code: not_authenticated | session_expired)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AuthUnavailable(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class UpstreamRateLimited(Exception):
    pass


@dataclass
class Principal:
    user_id: uuid.UUID
    email: str | None = None
    user_metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None  # Supabase `session_id` claim, used for logout revocation
    token_digest: str | None = None  # sha256 of the access token (fallback revocation key)
    expires_at: datetime | None = None


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    expires_in: int
    user: dict[str, Any]


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jwks: jwt.PyJWKClient | None = None
        self._lock = threading.Lock()

    def _jwks_client(self) -> jwt.PyJWKClient:
        with self._lock:
            if self._jwks is None:
                self._jwks = jwt.PyJWKClient(
                    f"{self.settings.supabase_url}/auth/v1/.well-known/jwks.json",
                    cache_keys=True,
                    lifespan=600,
                    timeout=5,
                )
            return self._jwks

    def _key_for(self, token: str) -> tuple[Any, list[str]]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError("not_authenticated") from exc
        alg = header.get("alg")
        if alg == "HS256":
            secret = self.settings.supabase_jwt_secret
            if secret is None:
                raise AuthError("not_authenticated")
            return secret.get_secret_value(), ["HS256"]
        if alg not in ASYMMETRIC_ALGS:
            raise AuthError("not_authenticated")
        try:
            return self._jwks_client().get_signing_key_from_jwt(token).key, [alg]
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthUnavailable() from exc
        except jwt.PyJWTError as exc:
            raise AuthError("not_authenticated") from exc

    def verify(self, token: str, *, allow_expired: bool = False) -> Principal:
        """`allow_expired` is used only by logout so an expired-but-genuine session can be revoked."""
        if not self.settings.supabase_url:
            raise AuthUnavailable()
        key, algs = self._key_for(token)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=algs,
                audience=self.settings.supabase_jwt_audience,
                issuer=f"{self.settings.supabase_url}/auth/v1",
                options={"require": ["exp", "sub", "aud", "iss"], "verify_exp": not allow_expired},
                leeway=10,
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("session_expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("not_authenticated") from exc
        if claims.get("role") != "authenticated":
            raise AuthError("not_authenticated")
        try:
            user_id = uuid.UUID(str(claims["sub"]))
        except ValueError as exc:
            raise AuthError("not_authenticated") from exc
        meta = claims.get("user_metadata")
        sid = claims.get("session_id")
        try:
            exp = datetime.fromtimestamp(int(claims["exp"]), UTC)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AuthError("not_authenticated") from exc
        return Principal(user_id=user_id, email=claims.get("email"),
                         user_metadata=meta if isinstance(meta, dict) else {},
                         session_id=sid if isinstance(sid, str) and SESSION_ID_RE.match(sid) else None,
                         token_digest=token_digest(token), expires_at=exp)


class SupabaseAuthClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    def _client(self) -> httpx.Client:
        key = self.settings.supabase_publishable_key
        if not self.settings.supabase_url or key is None:
            raise AuthUnavailable()
        return httpx.Client(
            base_url=f"{self.settings.supabase_url}/auth/v1",
            headers={"apikey": key.get_secret_value(), "Content-Type": "application/json"},
            timeout=10,
            transport=self._transport,
        )

    @staticmethod
    def _tokens(resp: httpx.Response) -> TokenSet:
        data = resp.json()
        try:
            return TokenSet(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_in=int(data.get("expires_in", 3600)),
                user=data.get("user") or {},
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthUnavailable() from exc

    def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            with self._client() as client:
                return client.post(path, **kwargs)
        except httpx.HTTPError as exc:
            raise AuthUnavailable() from exc

    def sign_in_with_password(self, email: str, password: str) -> TokenSet:
        resp = self._post("/token", params={"grant_type": "password"}, json={"email": email, "password": password})
        if resp.status_code == 429:
            raise UpstreamRateLimited()
        if resp.status_code in (400, 401, 403, 422):
            raise InvalidCredentials()
        if resp.status_code != 200:
            raise AuthUnavailable()
        return self._tokens(resp)

    def refresh(self, refresh_token: str) -> TokenSet:
        resp = self._post("/token", params={"grant_type": "refresh_token"}, json={"refresh_token": refresh_token})
        if resp.status_code == 429:
            raise UpstreamRateLimited()
        if resp.status_code in (400, 401, 403, 422):
            raise AuthError("session_expired")
        if resp.status_code != 200:
            raise AuthUnavailable()
        return self._tokens(resp)

    def sign_out(self, access_token: str) -> None:
        """Revoke the current session's refresh tokens (best effort)."""
        try:
            self._post("/logout", params={"scope": "local"}, headers={"Authorization": f"Bearer {access_token}"})
        except AuthUnavailable:
            pass
