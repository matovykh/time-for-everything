"""HTTP-level protections: request id, body size limit, CSRF, security headers, cookies,
and a small in-process login rate limiter (single-process deployment per spec)."""

from __future__ import annotations

import hmac
import logging
import secrets
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings, get_settings
from app.core.errors import error_body

log = logging.getLogger("app.errors")

ACCESS_COOKIE = "tfe_at"
REFRESH_COOKIE = "tfe_rt"
CSRF_COOKIE = "tfe_csrf"
CSRF_HEADER = "x-csrf-token"
MAX_BODY_BYTES = 64 * 1024
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
REFRESH_MAX_AGE = 30 * 24 * 3600


# ---- cookies -------------------------------------------------------------------------------
def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(CSRF_COOKIE, token, max_age=REFRESH_MAX_AGE, path="/", secure=settings.secure_cookies,
                        httponly=False, samesite="strict")


def set_session_cookies(response: Response, access: str, refresh: str, expires_in: int, settings: Settings) -> None:
    # The cookie outlives the JWT on purpose: an expired token yields 401 session_expired (→ refresh)
    # rather than silently disappearing and looking like a logged-out browser. `exp` is always verified.
    del expires_in
    response.set_cookie(ACCESS_COOKIE, access, max_age=REFRESH_MAX_AGE, path="/api",
                        secure=settings.secure_cookies, httponly=True, samesite="lax")
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=REFRESH_MAX_AGE, path="/api/v1/auth",
                        secure=settings.secure_cookies, httponly=True, samesite="strict")


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name, path in ((ACCESS_COOKIE, "/api"), (REFRESH_COOKIE, "/api/v1/auth"), (CSRF_COOKIE, "/")):
        response.delete_cookie(name, path=path, secure=settings.secure_cookies, httponly=name != CSRF_COOKIE,
                               samesite="strict" if name != ACCESS_COOKIE else "lax")


# ---- middleware ----------------------------------------------------------------------------
class BodyLimitMiddleware:
    """Reject request bodies over MAX_BODY_BYTES, whether or not Content-Length is sent."""

    def __init__(self, app: ASGIApp, limit: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self.limit):
            await self._reject(scope, send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    # FastAPI re-raises HTTPException from body parsing; mapped to payload_too_large.
                    raise StarletteHTTPException(413)
            return message

        await self.app(scope, limited_receive, send)

    @staticmethod
    async def _reject(scope: Scope, send: Send) -> None:
        response = JSONResponse(error_body(None, "payload_too_large", "Слишком большой запрос."), status_code=413)
        await response(scope, _noop_receive, send)


async def _noop_receive() -> Message:
    return {"type": "http.disconnect"}


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def _origin_allowed(request: Request, settings: Settings) -> bool:
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return origin is None
    if settings.app_base_url:
        base = urlsplit(settings.app_base_url)
        return origin == f"{base.scheme}://{base.netloc}"
    return urlsplit(origin).netloc == request.headers.get("host", "")


def csrf_ok(request: Request, settings: Settings) -> bool:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if len(cookie) < 32 or not hmac.compare_digest(cookie.encode(), header.encode()):
        return False
    return _origin_allowed(request, settings)


def install_http_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id", "")
        if not (8 <= len(rid) <= 64 and rid.replace("-", "").isalnum()):
            rid = uuid.uuid4().hex
        request.state.request_id = rid
        path = request.url.path
        if path.startswith("/api/") and request.method in UNSAFE_METHODS and not csrf_ok(request, get_settings()):
            response: Response = JSONResponse(
                error_body(rid, "csrf_failed", "Сессия устарела. Обновите страницу и повторите."), status_code=403
            )
        else:
            try:
                response = await call_next(request)
            except Exception as exc:  # noqa: BLE001
                # Handled here so neither Starlette nor uvicorn logs a traceback whose text may contain
                # SQL parameters / personal data. Only request id, route template and exception class.
                route = request.scope.get("route")
                log.error("unhandled error request_id=%s method=%s route=%s error=%s", rid, request.method,
                          getattr(route, "path", "?"), type(exc).__name__)
                response = JSONResponse(
                    error_body(rid, "internal_error", "Внутренняя ошибка. Попробуйте позже."), status_code=500)
        response.headers["X-Request-ID"] = rid
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.add_middleware(BodyLimitMiddleware)


# ---- rate limiting -------------------------------------------------------------------------
class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int) -> int | None:
        """Record an attempt. Returns seconds to wait when over the limit, else None."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(window - (now - q[0])) + 1)
            q.append(now)
            if len(self._hits) > 10_000:  # bound memory
                for k in [k for k, v in self._hits.items() if not v][:5_000]:
                    self._hits.pop(k, None)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = SlidingWindowLimiter()
