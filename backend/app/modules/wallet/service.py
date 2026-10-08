"""Wallet: the only code that writes ledger rows and balances.

The balance cache row is changed with a single conditional UPDATE (`balance + amount >= 0`),
which is atomic on PostgreSQL and SQLite alike; a CHECK (balance >= 0) is the last line of defence.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.clock import clock, iso
from app.core.errors import ApiError, validation
from app.db.models import WalletAccount, WalletTransaction


def lock_account(db: Session, child_id: uuid.UUID) -> WalletAccount:
    q = select(WalletAccount).where(WalletAccount.child_id == child_id)
    acc = db.execute(q.with_for_update()).scalar_one_or_none()
    if acc is None:
        acc = WalletAccount(child_id=child_id, balance=0)
        db.add(acc)
        db.flush()
    return acc


def balance_of(db: Session, child_id: uuid.UUID) -> int:
    value = db.execute(select(WalletAccount.balance).where(WalletAccount.child_id == child_id)).scalar_one_or_none()
    return int(value or 0)


def post(db: Session, *, child_id: uuid.UUID, amount: int, reason_code: str, description: str,
         idempotency_key: str, source_type: str | None = None, source_id: uuid.UUID | None = None,
         period_end: date | None = None, actor_id: uuid.UUID | None = None) -> WalletTransaction:
    if amount == 0:
        raise ValueError("zero amount")
    lock_account(db, child_id)
    new_balance = db.execute(
        update(WalletAccount)
        .where(WalletAccount.child_id == child_id, WalletAccount.balance + amount >= 0)
        .values(balance=WalletAccount.balance + amount, updated_at=clock.now())
        .returning(WalletAccount.balance)
    ).scalar_one_or_none()
    if new_balance is None:
        raise ApiError(409, "insufficient_balance", "Недостаточно звёзд.",
                       details={"balance": balance_of(db, child_id), "required": -amount})
    seq = db.execute(select(func.coalesce(func.max(WalletTransaction.seq), 0))
                     .where(WalletTransaction.child_id == child_id)).scalar_one() + 1
    tx = WalletTransaction(child_id=child_id, seq=seq, amount=amount, balance_after=int(new_balance),
                           reason_code=reason_code,
                           description=description, source_type=source_type, source_id=source_id,
                           period_end=period_end, idempotency_key=idempotency_key, created_by=actor_id,
                           created_at=clock.now())
    db.add(tx)
    db.flush()
    return tx


def tx_dict(t: WalletTransaction) -> dict[str, Any]:
    return {
        "id": str(t.id), "amount": t.amount, "balance_after": t.balance_after, "reason_code": t.reason_code,
        "description": t.description, "source_type": t.source_type,
        "source_id": str(t.source_id) if t.source_id else None,
        "period_end": t.period_end.isoformat() if t.period_end else None, "created_at": iso(t.created_at),
    }


def ledger(db: Session, child_id: uuid.UUID, limit: int, cursor: str | None) -> dict[str, Any]:
    q = select(WalletTransaction).where(WalletTransaction.child_id == child_id)
    if cursor:
        if not cursor.isdigit() or len(cursor) > 12:
            raise validation("validation_error", "Некорректный cursor.", "cursor")
        q = q.where(WalletTransaction.seq < int(cursor))
    rows = db.execute(q.order_by(WalletTransaction.seq.desc()).limit(limit + 1)).scalars().all()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = str(rows[-1].seq) if more else None
    return {"balance": balance_of(db, child_id), "items": [tx_dict(t) for t in rows], "next_cursor": next_cursor}
