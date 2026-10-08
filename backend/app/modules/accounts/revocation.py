"""Persistent local logout revocation.

Logout records, *before* any upstream call: the Supabase session (`sid:`), the access token hash
(`at:`, fallback when the token has no session_id claim) and the refresh token hash (`rt:`).
Every authenticated request and every refresh checks these keys, so a copied cookie stops working
even if Supabase's /logout call fails or the JWT has not expired yet.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.clock import clock
from app.db.models import RevokedSession
from app.integrations.supabase_auth import Principal, token_digest

# Supabase sessions/refresh tokens have no fixed lifetime by default: keep these long.
SESSION_RETENTION = timedelta(days=400)
TOKEN_LEEWAY = timedelta(minutes=5)


def access_keys(p: Principal) -> list[str]:
    keys = []
    if p.session_id:
        keys.append(f"sid:{p.session_id}")
    if p.token_digest:
        keys.append(f"at:{p.token_digest}")
    return keys


def _any_revoked(db: Session, keys: list[str]) -> bool:
    if not keys:
        return False
    return db.execute(select(RevokedSession.key).where(RevokedSession.key.in_(keys)).limit(1)).first() is not None


def is_revoked(db: Session, p: Principal) -> bool:
    return _any_revoked(db, access_keys(p))


def refresh_token_revoked(db: Session, refresh_token: str) -> bool:
    return _any_revoked(db, [f"rt:{token_digest(refresh_token)}"])


class RevocationFailed(Exception):
    """The revocation could not be persisted; the session must not be reported as ended."""


def revoke(db: Session, p: Principal, refresh_token: str | None) -> None:
    """Idempotent. Returns only after the revocation is committed; otherwise raises RevocationFailed.
    Only called with a signature-verified principal."""
    now = clock.now()
    long_exp = now + SESSION_RETENTION
    rows: list[tuple[str, str, datetime]] = []
    if p.session_id:
        rows.append((f"sid:{p.session_id}", "session", long_exp))
    if p.token_digest:
        rows.append((f"at:{p.token_digest}", "access_token", (p.expires_at or now) + TOKEN_LEEWAY))
    if refresh_token:
        rows.append((f"rt:{token_digest(refresh_token)}", "refresh_token", long_exp))
    keys = [k for k, _, _ in rows]
    try:
        db.execute(delete(RevokedSession).where(RevokedSession.expires_at < now))
        for key, kind, expires_at in rows:
            if db.get(RevokedSession, key) is None:
                db.add(RevokedSession(key=key, user_id=p.user_id, kind=kind, revoked_at=now, expires_at=expires_at))
        db.commit()
    except IntegrityError:
        # A concurrent logout of the same session inserted the same keys: fine only if they are all stored.
        db.rollback()
        stored = set(db.execute(select(RevokedSession.key).where(RevokedSession.key.in_(keys))).scalars())
        if stored != set(keys):
            raise RevocationFailed() from None
    except SQLAlchemyError as exc:
        db.rollback()
        raise RevocationFailed() from exc
