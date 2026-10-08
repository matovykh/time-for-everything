"""Time entries: all-time history, per-date totals, manual entries, audited edits."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.clock import clock, iso, utc
from app.core.deps import Ctx, require_guardian
from app.core.errors import ApiError, not_found, validation
from app.db.models import Activity, TimeEntry

MIN_DATE = date(2000, 1, 1)
MAX_DAY_SECONDS = 86400


def quality_default(activity: Activity) -> str:
    return "pending" if activity.category == "lesson" else "not_required"


def entry_dict(e: TimeEntry) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "activity_id": str(e.activity_id),
        "activity_date": e.activity_date.isoformat(),
        "duration_seconds": e.duration_seconds,
        "source": e.source,
        "quality_status": e.quality_status,
        "workload": e.workload,
        "note": e.note,
        "revision": e.revision,
        "created_at": iso(e.created_at),
        "updated_at": iso(e.updated_at),
    }


def _audit_view(e: TimeEntry) -> dict[str, Any]:
    # Notes are free text written by a child: keep only their length in the audit trail.
    return {"activity_date": e.activity_date.isoformat(), "duration_seconds": e.duration_seconds,
            "quality_status": e.quality_status, "workload": e.workload, "note_length": len(e.note or ""),
            "revision": e.revision}


def check_daily_total(db: Session, child_id: uuid.UUID, activity_id: uuid.UUID, day: date, seconds: int,
                      exclude_id: uuid.UUID | None = None) -> None:
    q = select(func.coalesce(func.sum(TimeEntry.duration_seconds), 0)).where(
        TimeEntry.child_id == child_id, TimeEntry.activity_id == activity_id,
        TimeEntry.activity_date == day, TimeEntry.deleted_at.is_(None))
    if exclude_id is not None:
        q = q.where(TimeEntry.id != exclude_id)
    if int(db.execute(q).scalar_one()) + seconds > MAX_DAY_SECONDS:
        raise validation("daily_total_exceeded", "За один день по занятию нельзя записать больше 24 часов.",
                         "duration_seconds")


def check_date(day: date, today: date) -> None:
    if day > today:
        raise validation("future_date", "Нельзя записать время на будущую дату.", "activity_date")
    if day < MIN_DATE:
        raise validation("validation_error", "Слишком ранняя дата.", "activity_date")


def _encode_cursor(e: TimeEntry) -> str:
    raw = json.dumps([e.activity_date.isoformat(), utc(e.created_at).isoformat(), str(e.id)])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[date, datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        d, created, eid = json.loads(base64.urlsafe_b64decode(padded))
        return date.fromisoformat(d), datetime.fromisoformat(created), uuid.UUID(eid)
    except (ValueError, TypeError) as exc:
        raise validation("validation_error", "Некорректный cursor.", "cursor") from exc


def list_entries(ctx: Ctx, activity: Activity, limit: int, cursor: str | None) -> dict[str, Any]:
    q = select(TimeEntry).where(TimeEntry.child_id == ctx.child_id, TimeEntry.activity_id == activity.id,
                                TimeEntry.deleted_at.is_(None))
    if cursor:
        d, created, eid = _decode_cursor(cursor)
        if ctx.db.bind is not None and ctx.db.bind.dialect.name == "sqlite":
            created = created.replace(tzinfo=None)
        q = q.where(or_(
            TimeEntry.activity_date < d,
            and_(TimeEntry.activity_date == d, TimeEntry.created_at < created),
            and_(TimeEntry.activity_date == d, TimeEntry.created_at == created, TimeEntry.id < eid),
        ))
    rows = ctx.db.execute(
        q.order_by(TimeEntry.activity_date.desc(), TimeEntry.created_at.desc(), TimeEntry.id.desc()).limit(limit + 1)
    ).scalars().all()
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [entry_dict(e) for e in rows], "next_cursor": _encode_cursor(rows[-1]) if more else None}


def daily_totals(ctx: Ctx, activity: Activity) -> dict[str, Any]:
    rows = ctx.db.execute(
        select(TimeEntry.activity_date, func.sum(TimeEntry.duration_seconds), func.count())
        .where(TimeEntry.child_id == ctx.child_id, TimeEntry.activity_id == activity.id,
               TimeEntry.deleted_at.is_(None))
        .group_by(TimeEntry.activity_date).order_by(TimeEntry.activity_date)
    ).all()
    return {"activity_id": str(activity.id),
            "points": [{"date": d.isoformat(), "seconds": int(s), "entries": int(c)} for d, s, c in rows]}


REVIEWED = ("confirmed", "rejected")


def check_workload_allowed(ctx: Ctx, workload: str, current: str = "normal") -> None:
    """Spec §5.2: workload (normal/increased/excluded) is marked by an adult; a child could otherwise
    drop slow days from the reward comparison."""
    if workload != current and not ctx.is_guardian:
        raise ApiError(403, "forbidden", "Объём и сложность задания отмечает взрослый.")


def create_manual(ctx: Ctx, activity: Activity, *, activity_date: date, duration_seconds: int, note: str,
                  workload: str) -> tuple[int, dict[str, Any]]:
    check_workload_allowed(ctx, workload)
    check_date(activity_date, ctx.today)
    check_daily_total(ctx.db, ctx.child_id, activity.id, activity_date, duration_seconds)
    now = clock.now()
    e = TimeEntry(child_id=ctx.child_id, activity_id=activity.id, activity_date=activity_date,
                  duration_seconds=duration_seconds, source="manual", quality_status=quality_default(activity),
                  workload=workload, note=note, created_by=ctx.actor_id, created_at=now, updated_at=now, revision=1)
    ctx.db.add(e)
    ctx.db.flush()
    return 201, entry_dict(e)


def get_entry(ctx: Ctx, entry_id: uuid.UUID, *, for_update: bool = False) -> TimeEntry:
    q = select(TimeEntry).where(TimeEntry.id == entry_id, TimeEntry.child_id == ctx.child_id,
                                TimeEntry.deleted_at.is_(None))
    if for_update:
        q = q.with_for_update()
    e = ctx.db.execute(q).scalar_one_or_none()
    if e is None:
        raise not_found("Запись не найдена.")
    return e


def _check_revision(e: TimeEntry, revision: int) -> None:
    if e.revision != revision:
        raise ApiError(409, "revision_conflict", "Запись изменена в другом месте. Данные обновлены.",
                       details={"current": entry_dict(e)})


def update_entry(ctx: Ctx, entry_id: uuid.UUID, revision: int, changes: dict[str, Any]) -> dict[str, Any]:
    e = get_entry(ctx, entry_id, for_update=True)
    _check_revision(e, revision)
    new_date = changes.get("activity_date", e.activity_date)
    new_seconds = changes.get("duration_seconds", e.duration_seconds)
    measured_change = new_date != e.activity_date or new_seconds != e.duration_seconds
    if measured_change and e.quality_status in REVIEWED and not ctx.is_guardian:
        # Reviewed entries are frozen for the child (only the note is editable): shortening, moving out of
        # the reward window, or edit→pending→delete chains would let a child keep only the fastest days.
        raise ApiError(403, "forbidden", "Запись уже проверена взрослым: исправить время или дату может только он.")
    if "workload" in changes:
        check_workload_allowed(ctx, changes["workload"], e.workload)
    before = _audit_view(e)
    if e.source == "manual" and new_seconds < 60:
        raise validation("validation_error", "Ручная запись — от 1 минуты.", "duration_seconds")
    check_date(new_date, ctx.today)
    check_daily_total(ctx.db, ctx.child_id, e.activity_id, new_date, new_seconds, exclude_id=e.id)
    for k, v in changes.items():
        setattr(e, k, v)
    e.revision += 1
    e.updated_at = clock.now()
    audit.record(ctx.db, actor_id=ctx.actor_id, child_id=ctx.child_id, action="entry.update",
                 target_type="time_entry", target_id=e.id, before=before, after=_audit_view(e))
    ctx.db.commit()
    return entry_dict(e)


def delete_entry(ctx: Ctx, entry_id: uuid.UUID, revision: int) -> None:
    e = get_entry(ctx, entry_id, for_update=True)
    _check_revision(e, revision)
    if e.quality_status in REVIEWED and not ctx.is_guardian:
        # Deleting reviewed (e.g. slow) days would let a child keep only the fastest results (spec §5.2.3).
        raise ApiError(403, "forbidden", "Проверенную взрослым запись удаляет взрослый.")
    before = _audit_view(e)
    e.deleted_at = clock.now()
    e.revision += 1
    audit.record(ctx.db, actor_id=ctx.actor_id, child_id=ctx.child_id, action="entry.delete",
                 target_type="time_entry", target_id=e.id, before=before, after=None)
    ctx.db.commit()


def set_quality(ctx: Ctx, entry_id: uuid.UUID, revision: int, status: str) -> dict[str, Any]:
    require_guardian(ctx)
    e = get_entry(ctx, entry_id, for_update=True)
    _check_revision(e, revision)
    if e.quality_status == "not_required":
        raise validation("validation_error", "Подтверждение качества нужно только для уроков.", "quality_status")
    before = _audit_view(e)
    e.quality_status = status
    e.revision += 1
    e.updated_at = clock.now()
    audit.record(ctx.db, actor_id=ctx.actor_id, child_id=ctx.child_id, action="entry.quality",
                 target_type="time_entry", target_id=e.id, before=before, after=_audit_view(e))
    ctx.db.commit()
    return entry_dict(e)
