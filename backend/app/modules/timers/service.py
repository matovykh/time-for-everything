"""Server-authoritative, per-activity independent timers.

Every command runs in one transaction: the draft row is locked (SELECT … FOR UPDATE on
PostgreSQL), the expected revision is compared, and the revision is incremented. Concurrent
commands from two devices therefore yield exactly one success and one 409.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import clock, iso, iso_date, local_date, utc
from app.core.deps import Ctx
from app.core.errors import ApiError, validation
from app.db.models import Activity, Profile, TimeEntry, TimerDraft
from app.modules.activities.service import ensure_active, get_timed_activity
from app.modules.entries.service import check_daily_total, check_workload_allowed, entry_dict, quality_default

CONFIRM_AFTER_MS = 4 * 3600 * 1000
CORRECT_AFTER_MS = 24 * 3600 * 1000
MAX_DAY_SECONDS = 86400


def _ms(delta: timedelta) -> int:
    return max(0, delta // timedelta(milliseconds=1))


def elapsed_ms(draft: TimerDraft | None, now: datetime) -> int:
    if draft is None or draft.state == "idle":
        return 0
    total = draft.accumulated_ms
    if draft.state == "running" and draft.running_since is not None:
        total += _ms(now - utc(draft.running_since))
    return total


def timer_dict(activity_id: uuid.UUID, draft: TimerDraft | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or clock.now()
    elapsed = elapsed_ms(draft, now)
    idle = draft is None or draft.state == "idle"
    return {
        "activity_id": str(activity_id),
        "state": "idle" if idle else draft.state,
        "accumulated_ms": 0 if idle else draft.accumulated_ms,
        "running_since": None if idle else iso(draft.running_since),
        "elapsed_ms": elapsed,
        "session_started_at": None if idle else iso(draft.session_started_at),
        "started_on": None if idle else iso_date(draft.started_on),
        "long_session": "correct" if elapsed > CORRECT_AFTER_MS else "confirm" if elapsed > CONFIRM_AFTER_MS
        else "none",
        "revision": draft.revision if draft else 0,
        "server_now": iso(now),
    }


def drafts_by_activity(db: Session, child_id: uuid.UUID) -> dict[uuid.UUID, TimerDraft]:
    rows = db.execute(select(TimerDraft).where(TimerDraft.child_id == child_id)).scalars()
    return {d.activity_id: d for d in rows}


def active_timers(ctx: Ctx) -> list[dict[str, Any]]:
    now = clock.now()
    rows = ctx.db.execute(
        select(TimerDraft).where(TimerDraft.child_id == ctx.child_id, TimerDraft.state != "idle")
        .order_by(TimerDraft.updated_at)
    ).scalars()
    return [timer_dict(d.activity_id, d, now) for d in rows]


def _lock_draft(db: Session, child_id: uuid.UUID, activity_id: uuid.UUID) -> TimerDraft:
    q = select(TimerDraft).where(TimerDraft.child_id == child_id, TimerDraft.activity_id == activity_id)
    draft = db.execute(q.with_for_update()).scalar_one_or_none()
    if draft is None:  # activities created before drafts existed; unique key guards races
        draft = TimerDraft(child_id=child_id, activity_id=activity_id, state="idle", accumulated_ms=0, revision=0)
        db.add(draft)
        db.flush()
    return draft


def _check(draft: TimerDraft, activity_id: uuid.UUID, revision: int, allowed: set[str], now: datetime) -> None:
    if revision != draft.revision:
        raise ApiError(409, "revision_conflict", "Таймер изменён на другом устройстве. Состояние обновлено.",
                       details={"current": timer_dict(activity_id, draft, now)})
    if draft.state not in allowed:
        raise ApiError(409, "invalid_timer_state", "Эта команда недоступна в текущем состоянии таймера.",
                       details={"current": timer_dict(activity_id, draft, now)})


def _to_idle(draft: TimerDraft) -> None:
    draft.state = "idle"
    draft.accumulated_ms = 0
    draft.running_since = None
    draft.session_started_at = None
    draft.started_on = None


def _other_running(ctx: Ctx, activity_id: uuid.UUID, now: datetime) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(TimerDraft, Activity.name).join(Activity, Activity.id == TimerDraft.activity_id)
        .where(TimerDraft.child_id == ctx.child_id, TimerDraft.state == "running",
               TimerDraft.activity_id != activity_id)
    ).all()
    return [{"activity_id": str(d.activity_id), "name": name, "elapsed_ms": elapsed_ms(d, now)} for d, name in rows]


def command(ctx: Ctx, activity_id: uuid.UUID, cmd: str, revision: int) -> tuple[int, dict[str, Any]]:
    activity = get_timed_activity(ctx, activity_id)
    ensure_active(activity)
    now = clock.now()
    draft = _lock_draft(ctx.db, ctx.child_id, activity.id)
    other: list[dict[str, Any]] = []
    if cmd == "start":
        _check(draft, activity.id, revision, {"idle", "paused"}, now)
        if draft.state == "idle":
            draft.session_started_at = now
            draft.started_on = local_date(ctx.child.timezone, now)
            draft.accumulated_ms = 0
        draft.state = "running"
        draft.running_since = now
        other = _other_running(ctx, activity.id, now)
    elif cmd == "pause":
        _check(draft, activity.id, revision, {"running"}, now)
        draft.accumulated_ms = elapsed_ms(draft, now)
        draft.state = "paused"
        draft.running_since = None
    elif cmd == "reset":
        _check(draft, activity.id, revision, {"running", "paused"}, now)
        _to_idle(draft)
    else:  # pragma: no cover - router restricts values
        raise ApiError(404, "not_found", "Неизвестная команда.")
    draft.revision += 1
    draft.updated_at = now
    ctx.db.flush()
    return 200, {"timer": timer_dict(activity.id, draft, now), "other_running": other}


def save(ctx: Ctx, activity_id: uuid.UUID, *, revision: int, activity_date: date | None,
         confirm_long_session: bool, duration_seconds: int | None, note: str, workload: str
         ) -> tuple[int, dict[str, Any]]:
    activity = get_timed_activity(ctx, activity_id)
    ensure_active(activity)
    check_workload_allowed(ctx, workload)
    now = clock.now()
    draft = _lock_draft(ctx.db, ctx.child_id, activity.id)
    _check(draft, activity.id, revision, {"running", "paused"}, now)
    elapsed = elapsed_ms(draft, now)
    elapsed_s = elapsed // 1000
    if duration_seconds is not None:
        if duration_seconds > elapsed_s:
            raise validation("validation_error", "Длительность не может превышать время таймера.",
                             "duration_seconds")
        seconds = duration_seconds
    else:
        if elapsed > CORRECT_AFTER_MS:
            raise ApiError(422, "session_too_long",
                           "Таймер работал больше 24 часов. Укажите фактическую длительность.",
                           details={"current": timer_dict(activity.id, draft, now)})
        if elapsed > CONFIRM_AFTER_MS and not confirm_long_session:
            raise ApiError(422, "long_session_confirmation_required",
                           "Таймер работал больше 4 часов. Подтвердите сохранение.",
                           details={"current": timer_dict(activity.id, draft, now)})
        seconds = elapsed_s
    if seconds < 1:
        raise validation("duration_too_short", "Сохранить можно не меньше 1 секунды.", "duration_seconds")
    today = local_date(ctx.child.timezone, now)
    started_on = draft.started_on or today
    day = activity_date or started_on
    if not (started_on <= day <= today):
        raise validation("date_not_allowed", "Дата должна быть между началом занятия и сегодняшним днём.",
                         "activity_date")
    check_daily_total(ctx.db, ctx.child_id, activity.id, day, seconds)
    entry = TimeEntry(
        child_id=ctx.child_id, activity_id=activity.id, activity_date=day, duration_seconds=seconds,
        source="timer", quality_status=quality_default(activity), workload=workload, note=note,
        created_by=ctx.actor_id, created_at=now, updated_at=now, revision=1,
    )
    ctx.db.add(entry)
    _to_idle(draft)
    draft.revision += 1
    draft.updated_at = now
    ctx.db.flush()
    return 201, {"timer": timer_dict(activity.id, draft, now), "entry": entry_dict(entry)}


def pause_all_running(db: Session, child: Profile) -> int:
    """Used on logout: pause every running timer of the child (revision++)."""
    now = clock.now()
    rows = db.execute(
        select(TimerDraft).where(TimerDraft.child_id == child.id, TimerDraft.state == "running").with_for_update()
    ).scalars().all()
    for d in rows:
        d.accumulated_ms = elapsed_ms(d, now)
        d.state = "paused"
        d.running_since = None
        d.revision += 1
        d.updated_at = now
    db.commit()
    return len(rows)
