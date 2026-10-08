"""FastAPI dependencies: authenticated principal, provisioning and acting-child context.

Tests may replace `get_principal` / `get_auth_client` through `app.dependency_overrides`.
There is no environment switch that disables authentication.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import local_date
from app.core.config import get_settings
from app.core.errors import ApiError, not_found
from app.core.security import ACCESS_COOKIE
from app.db.models import GuardianChild, Profile
from app.db.session import get_db
from app.integrations.supabase_auth import (
    AuthError,
    AuthUnavailable,
    Principal,
    SupabaseAuthClient,
    TokenVerifier,
)
from app.modules.accounts import revocation
from app.modules.accounts.provisioning import ensure_profile

_SESSION_MESSAGES = {
    "not_authenticated": "Нужно войти.",
    "session_expired": "Сессия истекла. Обновите сессию.",
}


@lru_cache
def get_verifier() -> TokenVerifier:
    return TokenVerifier(get_settings())


def get_auth_client() -> SupabaseAuthClient:
    return SupabaseAuthClient(get_settings())


def auth_not_configured() -> ApiError:
    return ApiError(503, "service_not_configured", "Вход не настроен на сервере.",
                    details={"missing": get_settings().missing_settings()})


def verify_access_token(token: str, *, allow_expired: bool = False) -> Principal:
    if not get_settings().auth_configured:
        raise auth_not_configured()
    try:
        return get_verifier().verify(token, allow_expired=allow_expired)
    except AuthError as exc:
        raise ApiError(401, exc.code, _SESSION_MESSAGES[exc.code]) from exc
    except AuthUnavailable as exc:
        raise ApiError(503, "auth_unavailable", "Сервис входа временно недоступен.") from exc


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    """Verified JWT from the HttpOnly cookie that has not been revoked by a logout."""
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise ApiError(401, "not_authenticated", _SESSION_MESSAGES["not_authenticated"])
    principal = verify_access_token(token)
    if revocation.is_revoked(db, principal):
        raise ApiError(401, "not_authenticated", _SESSION_MESSAGES["not_authenticated"])
    return principal


@dataclass
class Ctx:
    db: Session
    actor: Profile
    child: Profile
    is_guardian: bool

    @property
    def child_id(self) -> uuid.UUID:
        return self.child.id

    @property
    def actor_id(self) -> uuid.UUID:
        return self.actor.id

    @property
    def today(self) -> date:
        return local_date(self.child.timezone)


def get_ctx(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    x_child_id: str | None = Header(default=None, alias="X-Child-Id"),
) -> Ctx:
    actor = ensure_profile(db, principal)
    if not x_child_id or x_child_id == str(actor.id):
        return Ctx(db=db, actor=actor, child=actor, is_guardian=False)
    try:
        child_id = uuid.UUID(x_child_id)
    except ValueError as exc:
        raise not_found() from exc
    if actor.role not in ("guardian", "admin"):
        raise not_found()
    link = db.execute(
        select(GuardianChild).where(GuardianChild.guardian_id == actor.id, GuardianChild.child_id == child_id)
    ).scalar_one_or_none()
    child = db.get(Profile, child_id) if link else None
    if child is None:
        raise not_found()
    return Ctx(db=db, actor=actor, child=child, is_guardian=True)


def require_guardian(ctx: Ctx) -> None:
    if not ctx.is_guardian:
        raise ApiError(403, "forbidden", "Это действие доступно взрослому.")
