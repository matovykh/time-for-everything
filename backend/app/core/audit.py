"""Append-only audit trail. Callers pass sanitized snapshots (no free-text notes, no secrets)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record(db: Session, *, actor_id: uuid.UUID | None, child_id: uuid.UUID | None, action: str,
           target_type: str, target_id: Any, before: dict[str, Any] | None = None,
           after: dict[str, Any] | None = None) -> None:
    db.add(AuditEvent(actor_id=actor_id, child_id=child_id, action=action, target_type=target_type,
                      target_id=str(target_id) if target_id is not None else None, before=before, after=after))
