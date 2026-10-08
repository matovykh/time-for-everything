"""Idempotency-Key handling. The stored response is written in the same DB transaction as the
mutation, so a replay can never observe a half-applied command."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import clock, utc
from app.core.errors import ApiError
from app.db.models import IdempotencyRequest

KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")
TTL = timedelta(hours=24)
_REPLAYABLE_CONFLICTS = {"revision_conflict", "invalid_timer_state", "already_owned", "insufficient_balance"}


def read_key(request: Request, required: bool) -> str | None:
    key = request.headers.get("idempotency-key")
    if key is None:
        if required:
            raise ApiError(400, "idempotency_key_required", "Нужен заголовок Idempotency-Key.")
        return None
    if not KEY_RE.match(key):
        raise ApiError(400, "invalid_idempotency_key", "Некорректный Idempotency-Key.")
    return key


def request_hash(method: str, path: str, body: Any) -> str:
    raw = json.dumps({"m": method, "p": path, "b": body}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _replay(row: IdempotencyRequest) -> JSONResponse:
    return JSONResponse(row.response, status_code=row.status_code, headers={"Idempotent-Replay": "true"})


def scoped_key(child_id: uuid.UUID, key: str) -> str:
    """Keys are scoped to (actor, acting child): a guardian reusing a key for another child is a new request."""
    return f"{child_id}:{key}"


def _lookup(db: Session, actor_id: uuid.UUID, key: str, digest: str) -> JSONResponse | None:
    row = db.get(IdempotencyRequest, (actor_id, key))
    if row is None:
        return None
    if utc(row.expires_at) <= clock.now():
        db.delete(row)
        db.flush()
        return None
    if row.request_hash != digest:
        raise ApiError(422, "idempotency_key_reuse", "Этот Idempotency-Key уже использован для другого запроса.")
    return _replay(row)


def run(
    db: Session,
    actor_id: uuid.UUID,
    key: str | None,
    request: Request,
    body: Any,
    action: Callable[[], tuple[int, dict[str, Any]]],
    *,
    child_id: uuid.UUID,
) -> JSONResponse:
    """Execute `action` (which mutates `db` without committing) exactly once per (actor, child, key)."""
    digest = request_hash(request.method, request.url.path, {"child": str(child_id), "body": body})
    key = scoped_key(child_id, key) if key is not None else None
    if key is not None:
        replay = _lookup(db, actor_id, key, digest)
        if replay is not None:
            db.commit()
            return replay
    try:
        status, payload = action()
        if key is not None:
            now = clock.now()
            db.add(IdempotencyRequest(actor_id=actor_id, key=key, request_hash=digest, status_code=status,
                                      response=payload, created_at=now, expires_at=now + TTL))
        db.commit()
    except ApiError as err:
        db.rollback()
        if key is not None and err.code in _REPLAYABLE_CONFLICTS:
            replay = _lookup(db, actor_id, key, digest)
            if replay is not None:
                return replay
        raise
    except IntegrityError as exc:
        db.rollback()
        if key is not None:
            replay = _lookup(db, actor_id, key, digest)
            if replay is not None:
                return replay
        raise ApiError(409, "idempotency_conflict", "Запрос уже выполняется или данные изменились. Повторите.") from exc
    return JSONResponse(payload, status_code=status)
