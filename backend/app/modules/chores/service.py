"""Chores: per-date view of scheduled/voluntary boolean activities and idempotent completions."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.clock import clock, iso
from app.core.deps import Ctx
from app.core.errors import ApiError, not_found, validation
from app.db.models import Activity, ChoreCompletion, DayStatus, Schedule
from app.modules.activities import schedules as sched


def _item(act: Activity, versions: list[Schedule], day: date, done: ChoreCompletion | None) -> dict[str, Any]:
    voluntary = not versions
    scheduled = sched.is_scheduled(versions, day)
    return {
        "activity_id": str(act.id),
        "code": act.code,
        "name": act.name,
        "icon": act.icon,
        "date": day.isoformat(),
        "scheduled": scheduled,
        "voluntary": voluntary,
        "due": scheduled or voluntary,
        "completed": done is not None,
        "completed_at": iso(done.completed_at) if done else None,
        "reward_eligible": act.reward_eligible,
        "schedule": sched.schedule_dict(sched.display_version(versions, day)),
    }


def chores_for(ctx: Ctx, day: date) -> dict[str, Any]:
    acts = ctx.db.execute(
        select(Activity).where(Activity.child_id == ctx.child_id, Activity.kind == "boolean",
                               Activity.archived_at.is_(None)).order_by(Activity.sort_order, Activity.created_at)
    ).scalars().all()
    versions = sched.load_versions(ctx.db, ctx.child_id, [a.id for a in acts])
    done = {
        c.activity_id: c for c in ctx.db.execute(
            select(ChoreCompletion).where(ChoreCompletion.child_id == ctx.child_id, ChoreCompletion.local_date == day)
        ).scalars()
    }
    items = [_item(a, versions.get(a.id, []), day, done.get(a.id)) for a in acts]
    return {
        "date": day.isoformat(),
        "items": items,
        "summary": {
            "scheduled_total": sum(1 for i in items if i["scheduled"]),
            "scheduled_completed": sum(1 for i in items if i["scheduled"] and i["completed"]),
            "voluntary_completed": sum(1 for i in items if i["voluntary"] and i["completed"]),
        },
    }


def set_completion(ctx: Ctx, activity_id: uuid.UUID, day: date, completed: bool) -> dict[str, Any]:
    act = ctx.db.execute(
        select(Activity).where(Activity.id == activity_id, Activity.child_id == ctx.child_id,
                               Activity.kind == "boolean")
    ).scalar_one_or_none()
    if act is None:
        raise not_found("Поручение не найдено.")
    if act.archived_at is not None:
        raise ApiError(409, "activity_archived", "Поручение в архиве.")
    today = ctx.today
    if day > today or (not ctx.is_guardian and day != today):
        raise validation("date_not_allowed", "Отметить можно только сегодняшнее дело.", "date")
    versions = sched.load_versions(ctx.db, ctx.child_id, [act.id]).get(act.id, [])
    scheduled = sched.is_scheduled(versions, day)
    if versions and not scheduled:
        raise validation("not_scheduled", "На этот день поручение не запланировано.", "date")

    def current() -> ChoreCompletion | None:
        return ctx.db.execute(
            select(ChoreCompletion).where(ChoreCompletion.activity_id == act.id, ChoreCompletion.local_date == day)
        ).scalar_one_or_none()

    row = current()
    if completed and row is None:
        try:
            ctx.db.add(ChoreCompletion(child_id=ctx.child_id, activity_id=act.id, local_date=day,
                                       scheduled=scheduled, completed_at=clock.now(), actor_id=ctx.actor_id))
            ctx.db.commit()
        except IntegrityError:
            ctx.db.rollback()  # concurrent identical request already completed it
    elif not completed and row is not None:
        ctx.db.delete(row)
        ctx.db.commit()
    return _item(act, versions, day, current())


# ---- walk day statuses ------------------------------------------------------------------------
def list_day_statuses(ctx: Ctx, category: str, start: date, end: date) -> list[dict[str, str]]:
    rows = ctx.db.execute(
        select(DayStatus).where(DayStatus.child_id == ctx.child_id, DayStatus.category == category,
                                DayStatus.local_date >= start, DayStatus.local_date <= end)
        .order_by(DayStatus.local_date)
    ).scalars()
    return [{"date": r.local_date.isoformat(), "status": r.status} for r in rows]


def set_day_status(ctx: Ctx, category: str, day: date, status: str | None) -> dict[str, Any]:
    if day > ctx.today:
        raise validation("future_date", "Нельзя отметить будущий день.", "date")
    if status == "excluded" and not ctx.is_guardian:
        raise ApiError(403, "forbidden", "Исключить день (болезнь, отпуск) может взрослый.")
    row = ctx.db.get(DayStatus, (ctx.child_id, category, day))
    if row is not None and row.status == "excluded" and not ctx.is_guardian:
        raise ApiError(403, "forbidden", "Этот день исключил взрослый.")
    if status is None:
        if row is not None:
            ctx.db.delete(row)
    elif row is None:
        ctx.db.add(DayStatus(child_id=ctx.child_id, category=category, local_date=day, status=status,
                             set_by=ctx.actor_id))
    else:
        row.status = status
        row.set_by = ctx.actor_id
    try:
        ctx.db.commit()
    except IntegrityError:
        ctx.db.rollback()
    return {"date": day.isoformat(), "status": status}
