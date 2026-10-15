"""Session (server-side Supabase Auth with HttpOnly cookies) and profile endpoints."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field, StringConstraints
from sqlalchemy.exc import SQLAlchemyError

from app.core.clock import clock, is_valid_timezone, iso, local_date
from app.core.config import get_settings
from app.core.deps import Ctx, auth_not_configured, get_auth_client, get_ctx, verify_access_token
from app.core.errors import ApiError, validation
from app.core.schemas import Strict
from app.core.security import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    clear_session_cookies,
    login_limiter,
    new_csrf_token,
    set_csrf_cookie,
    set_session_cookies,
)
from app.db.session import get_db, get_optional_db
from app.integrations.supabase_auth import (
    AuthError,
    AuthUnavailable,
    InvalidCredentials,
    SupabaseAuthClient,
    UpstreamRateLimited,
)
from app.modules.accounts import revocation
from app.modules.accounts.provisioning import ensure_profile, linked_children
from app.modules.timers.service import pause_all_running

log = logging.getLogger("app.auth")
router = APIRouter(tags=["auth"])


class LoginIn(Strict):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class LogoutIn(Strict):
    pause_running_timers: bool = True


class MePatch(Strict):
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] | None = None
    grade: Annotated[str, StringConstraints(pattern=r"^(?:[1-9]|1[01])$")] | None = None
    timezone: Annotated[str, StringConstraints(max_length=64)] | None = None
    theme: Literal["light", "dark", "system"] | None = None
    onboarding_version: Annotated[int, Field(strict=True, ge=0, le=1000)] | None = None


def me_dict(ctx: Ctx) -> dict[str, Any]:
    actor, child = ctx.actor, ctx.child
    children = linked_children(ctx.db, actor) if actor.role in ("guardian", "admin") else []
    return {
        "id": str(actor.id),
        "email": actor.email,
        "display_name": child.display_name,
        "grade": child.grade,
        "timezone": child.timezone,
        "theme": actor.theme,
        "role": actor.role,
        "active_world": child.active_world,
        "onboarding_version": child.onboarding_version,
        "rewards_started_on": child.rewards_started_on.isoformat(),
        "today": local_date(child.timezone).isoformat(),
        "acting_child_id": str(child.id),
        "children": [{"id": str(c.id), "display_name": c.display_name} for c in children],
        "permissions": {
            "can_confirm_quality": ctx.is_guardian,
            "can_manage_rewards_settings": ctx.is_guardian,
            # Reward-relevant inputs an adult controls (spec §5.2, §4.1); the UI hides/locks them otherwise.
            "can_edit_timezone": ctx.is_guardian,
            "can_set_workload": ctx.is_guardian,
            "can_delete_reviewed_entries": ctx.is_guardian,
            "is_admin": actor.role == "admin",
        },
    }


@router.get("/auth/csrf")
def csrf(request: Request) -> JSONResponse:
    token = request.cookies.get("tfe_csrf")
    if not token or len(token) < 32:
        token = new_csrf_token()
    resp = JSONResponse({"csrf_token": token})
    set_csrf_cookie(resp, token, get_settings())
    return resp


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/auth/login")
def login(body: LoginIn, request: Request, auth: SupabaseAuthClient = Depends(get_auth_client),
          db=Depends(get_db)) -> JSONResponse:
    settings = get_settings()
    if not settings.auth_configured:
        raise auth_not_configured()
    ip = _client_ip(request)
    email = body.email.lower()
    for key, limit in ((f"ip:{ip}", settings.login_rate_limit * 3), (f"acct:{ip}:{email}", settings.login_rate_limit)):
        wait = login_limiter.hit(key, limit, settings.login_rate_window_seconds)
        if wait is not None:
            raise ApiError(429, "rate_limited", "Слишком много попыток. Подождите немного.",
                           headers={"Retry-After": str(wait)})
    try:
        tokens = auth.sign_in_with_password(email, body.password)
    except InvalidCredentials as exc:
        raise ApiError(401, "invalid_credentials", "Неверный email или пароль.") from exc
    except UpstreamRateLimited as exc:
        raise ApiError(429, "rate_limited", "Слишком много попыток. Подождите немного.",
                       headers={"Retry-After": "60"}) from exc
    except AuthUnavailable as exc:
        raise ApiError(503, "auth_unavailable", "Сервис входа временно недоступен.") from exc
    principal = verify_access_token(tokens.access_token)
    profile = ensure_profile(db, principal)
    ctx = Ctx(db=db, actor=profile, child=profile, is_guardian=False)
    try:  # light due-period check at login (spec §8); failures never block login
        from app.modules.rewards.service import evaluate_due

        evaluate_due(db, profile, ctx.today, profile.id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        # No traceback/message: DB errors may carry SQL parameters (personal data).
        log.error("reward evaluation at login failed request_id=%s error=%s",
                  getattr(request.state, "request_id", None), type(exc).__name__)
    token = new_csrf_token()
    resp = JSONResponse({"me": me_dict(ctx), "csrf_token": token})
    set_session_cookies(resp, tokens.access_token, tokens.refresh_token, tokens.expires_in, settings)
    set_csrf_cookie(resp, token, settings)
    return resp


def _session_expired(request: Request) -> JSONResponse:
    resp = JSONResponse({"code": "session_expired", "message": "Сессия истекла. Войдите снова.",
                         "field_errors": [], "request_id": getattr(request.state, "request_id", None),
                         "details": None}, status_code=401)
    clear_session_cookies(resp, get_settings())
    return resp


@router.post("/auth/refresh")
def refresh(request: Request, auth: SupabaseAuthClient = Depends(get_auth_client),
            db=Depends(get_db)) -> JSONResponse:
    settings = get_settings()
    if not settings.auth_configured:
        raise auth_not_configured()
    rt = request.cookies.get(REFRESH_COOKIE)
    # Replay protection: a refresh token captured before logout is refused without calling Supabase.
    if not rt or revocation.refresh_token_revoked(db, rt):
        return _session_expired(request)
    try:
        tokens = auth.refresh(rt)
        principal = verify_access_token(tokens.access_token)
    except (AuthError, ApiError) as exc:
        if isinstance(exc, ApiError) and exc.status != 401:
            raise
        return _session_expired(request)
    except UpstreamRateLimited as exc:
        raise ApiError(429, "rate_limited", "Слишком много попыток.", headers={"Retry-After": "60"}) from exc
    except AuthUnavailable as exc:
        raise ApiError(503, "auth_unavailable", "Сервис входа временно недоступен.") from exc
    if revocation.is_revoked(db, principal):
        # Session was logged out locally (e.g. upstream /logout failed): never hand out new tokens.
        auth.sign_out(tokens.access_token)
        return _session_expired(request)
    token = request.cookies.get("tfe_csrf") or new_csrf_token()
    resp = JSONResponse({"csrf_token": token,
                         "expires_at": iso(clock.now() + timedelta(seconds=tokens.expires_in))})
    set_session_cookies(resp, tokens.access_token, tokens.refresh_token, tokens.expires_in, settings)
    set_csrf_cookie(resp, token, settings)
    return resp


@router.post("/auth/logout", status_code=204)
def logout(request: Request, body: Annotated[LogoutIn | None, Body()] = None,
           auth: SupabaseAuthClient = Depends(get_auth_client), db=Depends(get_optional_db)) -> Response:
    settings = get_settings()
    pause = body.pause_running_timers if body else True
    token = request.cookies.get(ACCESS_COOKIE)
    rid = getattr(request.state, "request_id", None)
    principal = None
    revoked = True  # nothing verifiable to revoke (no cookie / forged token) counts as done
    if token and settings.auth_configured:
        try:  # signature must be genuine; an expired session can still be revoked
            principal = verify_access_token(token, allow_expired=True)
        except ApiError as exc:
            # A genuine-looking session that cannot be verified right now (JWKS unreachable) is NOT ended.
            revoked = exc.status == 401
    if principal is not None:
        revoked = False
        if db is None:
            log.error("logout revocation impossible: database not ready request_id=%s", rid)
        else:
            # 1. Local revocation first: it must not depend on Supabase /logout succeeding.
            try:
                revocation.revoke(db, principal, request.cookies.get(REFRESH_COOKIE))
                revoked = True
            except revocation.RevocationFailed as exc:
                log.error("logout revocation failed request_id=%s error=%s", rid,
                          type(exc.__cause__ or exc).__name__)
            # 2. Server-side timer policy (pause), best effort, only once the session is really revoked.
            if revoked and pause:
                try:
                    pause_all_running(db, ensure_profile(db, principal))
                except SQLAlchemyError as exc:
                    db.rollback()
                    log.error("logout timer pause failed request_id=%s error=%s", rid, type(exc).__name__)
        # 3. Upstream revocation of refresh tokens (best effort; failures are swallowed by the client).
        auth.sign_out(token)
    if revoked:
        resp: Response = Response(status_code=204)
    else:
        resp = JSONResponse(
            {"code": "logout_incomplete",
             "message": "Выход на этом устройстве выполнен, но сервер не смог завершить сессию. "
                        "Если данные входа могли попасть к кому-то ещё, войдите снова и повторите выход позже.",
             "field_errors": [], "request_id": rid, "details": None},
            status_code=503)
    # Cookies are always removed from this browser, whatever the outcome.
    clear_session_cookies(resp, settings)
    return resp


@router.get("/me")
def get_me(ctx: Ctx = Depends(get_ctx)) -> dict:
    return me_dict(ctx)


@router.patch("/me")
def patch_me(body: MePatch, ctx: Ctx = Depends(get_ctx)) -> dict:
    changes = body.model_dump(exclude_unset=True)
    target = ctx.child
    new_tz = changes.get("timezone")
    if new_tz is not None and new_tz != target.timezone and not ctx.is_guardian:
        # The zone defines the child's "today": changing it could re-open yesterday for chores/entries.
        raise ApiError(403, "forbidden", "Часовой пояс меняет взрослый.")
    if new_tz is not None and not is_valid_timezone(new_tz):
        raise validation("validation_error", "Неизвестный часовой пояс.", "timezone")
    if changes.get("onboarding_version") is not None and changes["onboarding_version"] < target.onboarding_version:
        raise validation("validation_error", "Версия знакомства не может уменьшаться.", "onboarding_version")
    for field in ("display_name", "timezone", "onboarding_version"):
        if changes.get(field) is not None:
            setattr(target, field, changes[field])
    if "grade" in changes:
        target.grade = changes["grade"]
    if changes.get("theme") is not None:
        ctx.actor.theme = changes["theme"]
    target.revision += 1
    target.updated_at = clock.now()
    ctx.db.commit()
    return me_dict(ctx)
