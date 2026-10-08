"""Activities catalog (timed activities and boolean chores) with guardian-protected fields."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from app.core import audit
from app.core.clock import clock, iso
from app.core.deps import Ctx
from app.core.errors import ApiError, forbidden, not_found, validation
from app.db.models import Activity, Schedule, TimerDraft
from app.modules.activities import schedules as sched

PROTECTED_FIELDS = {"objective", "target_seconds", "schedule", "archived", "reward_eligible"}


def get_activity(ctx: Ctx, activity_id: uuid.UUID) -> Activity:
    act = ctx.db.execute(
        select(Activity).where(Activity.id == activity_id, Activity.child_id == ctx.child_id)
    ).scalar_one_or_none()
    if act is None:
        raise not_found("Занятие не найдено.")
    return act


def get_timed_activity(ctx: Ctx, activity_id: uuid.UUID) -> Activity:
    act = get_activity(ctx, activity_id)
    if act.kind != "timed":
        raise ApiError(422, "wrong_activity_kind", "У этого дела нет таймера.")
    return act


def ensure_active(act: Activity) -> None:
    if act.archived_at is not None:
        raise ApiError(409, "activity_archived", "Занятие в архиве.")


def activity_dict(act: Activity, versions: list[Schedule], draft: TimerDraft | None, today: date) -> dict[str, Any]:
    from app.modules.timers.service import timer_dict

    return {
        "id": str(act.id),
        "code": act.code,
        "name": act.name,
        "icon": act.icon,
        "kind": act.kind,
        "category": act.category,
        "objective": act.objective,
        "target_seconds": act.target_seconds,
        "sort_order": act.sort_order,
        "reward_eligible": act.reward_eligible,
        "archived_at": iso(act.archived_at),
        "schedule": sched.schedule_dict(sched.display_version(versions, today)) if act.kind == "boolean" else None,
        "revision": act.revision,
        "created_at": iso(act.created_at),
        "updated_at": iso(act.updated_at),
        "timer": timer_dict(act.id, draft) if act.kind == "timed" else None,
    }


def serialize(ctx: Ctx, act: Activity) -> dict[str, Any]:
    versions = sched.load_versions(ctx.db, ctx.child_id, [act.id]).get(act.id, [])
    draft = ctx.db.execute(
        select(TimerDraft).where(TimerDraft.child_id == ctx.child_id, TimerDraft.activity_id == act.id)
    ).scalar_one_or_none()
    return activity_dict(act, versions, draft, ctx.today)


def list_activities(ctx: Ctx, include_archived: bool) -> list[dict[str, Any]]:
    from app.modules.timers.service import drafts_by_activity

    q = select(Activity).where(Activity.child_id == ctx.child_id)
    if not include_archived:
        q = q.where(Activity.archived_at.is_(None))
    acts = ctx.db.execute(q.order_by(Activity.sort_order, Activity.created_at)).scalars().all()
    versions = sched.load_versions(ctx.db, ctx.child_id)
    drafts = drafts_by_activity(ctx.db, ctx.child_id)
    today = ctx.today
    return [activity_dict(a, versions.get(a.id, []), drafts.get(a.id), today) for a in acts]


def _validate_schedule(ctx: Ctx, schedule: dict[str, Any]) -> tuple[list[int], date, date | None]:
    weekdays = schedule["weekdays"]
    starts_on: date = schedule.get("starts_on") or ctx.today
    ends_on: date | None = schedule.get("ends_on")
    if starts_on < ctx.today:
        raise validation("date_not_allowed", "Расписание меняется только с сегодняшнего или будущего дня.",
                         "schedule.starts_on")
    if ends_on is not None and ends_on < starts_on:
        raise validation("validation_error", "Дата окончания раньше даты начала.", "schedule.ends_on")
    return sorted(set(weekdays)), starts_on, ends_on


def _validate_target(objective: str, target: int | None) -> None:
    if objective in ("reach", "maintain") and target is None:
        raise validation("validation_error", "Для этой цели нужно указать время.", "target_seconds")


def create_activity(ctx: Ctx, data: dict[str, Any]) -> dict[str, Any]:
    kind = data["kind"]
    if kind == "timed":
        if data.get("schedule") is not None:
            raise validation("validation_error", "Расписание доступно только для поручений.", "schedule")
        objective = data.get("objective") or "none"
        if objective == "decrease":
            raise validation("validation_error", "Цель «сокращать время» доступна только урокам.", "objective")
        _validate_target(objective, data.get("target_seconds"))
        category = "custom"
    else:
        if data.get("objective") not in (None, "none") or data.get("target_seconds") is not None:
            raise validation("validation_error", "У поручения нет цели по времени.", "objective")
        objective, category = "none", "chore"
    now = clock.now()
    act = Activity(
        child_id=ctx.child_id, code=None, name=data["name"], icon=data.get("icon"), kind=kind, category=category,
        objective=objective, target_seconds=data.get("target_seconds") if kind == "timed" else None,
        sort_order=data.get("sort_order") or 1000, reward_eligible=ctx.is_guardian, created_by=ctx.actor_id,
        created_at=now, updated_at=now, revision=1,
    )
    ctx.db.add(act)
    ctx.db.flush()
    if kind == "timed":
        ctx.db.add(TimerDraft(child_id=ctx.child_id, activity_id=act.id, state="idle", accumulated_ms=0, revision=0))
    elif data.get("schedule") is not None:
        weekdays, starts_on, ends_on = _validate_schedule(ctx, data["schedule"])
        ctx.db.add(Schedule(child_id=ctx.child_id, activity_id=act.id, weekdays_mask=sched.mask_from_weekdays(weekdays),
                            starts_on=starts_on, ends_on=ends_on, created_by=ctx.actor_id))
    audit.record(ctx.db, actor_id=ctx.actor_id, child_id=ctx.child_id, action="activity.create",
                 target_type="activity", target_id=act.id, after={"kind": kind, "category": category})
    ctx.db.commit()
    return serialize(ctx, act)


def update_activity(ctx: Ctx, activity_id: uuid.UUID, revision: int, changes: dict[str, Any]) -> dict[str, Any]:
    act = ctx.db.execute(
        select(Activity).where(Activity.id == activity_id, Activity.child_id == ctx.child_id).with_for_update()
    ).scalar_one_or_none()
    if act is None:
        raise not_found("Занятие не найдено.")
    if act.revision != revision:
        raise ApiError(409, "revision_conflict", "Занятие изменено в другом месте.",
                       details={"current": serialize(ctx, act)})
    protected = PROTECTED_FIELDS & changes.keys()
    if "reward_eligible" in changes and not ctx.is_guardian:
        raise forbidden("Значимость для наград задаёт взрослый.")
    if protected and (act.code is not None or act.reward_eligible) and not ctx.is_guardian:
        raise forbidden("Эти настройки занятия меняет взрослый.")
    before = {k: getattr(act, k) for k in ("name", "objective", "target_seconds", "reward_eligible", "sort_order")}
    before["archived"] = act.archived_at is not None

    if "schedule" in changes:
        if act.kind != "boolean":
            raise validation("validation_error", "Расписание доступно только для поручений.", "schedule")
        if changes["schedule"] is None:
            raise validation("validation_error", "Чтобы убрать поручение, отправьте его в архив.", "schedule")
        weekdays, starts_on, ends_on = _validate_schedule(ctx, changes["schedule"])
        sched.replace_from(ctx.db, ctx.child_id, act.id, weekdays, starts_on, ends_on, ctx.actor_id)
    if act.kind == "boolean" and ({"objective", "target_seconds"} & changes.keys()):
        raise validation("validation_error", "У поручения нет цели по времени.", "objective")
    if "objective" in changes:
        if changes["objective"] == "decrease" and act.category != "lesson":
            raise validation("validation_error", "Цель «сокращать время» доступна только урокам.", "objective")
        act.objective = changes["objective"]
    if "target_seconds" in changes:
        act.target_seconds = changes["target_seconds"]
    if act.kind == "timed":
        _validate_target(act.objective, act.target_seconds)
    for field in ("name", "icon", "sort_order", "reward_eligible"):
        if field in changes:
            if field == "sort_order" and changes[field] is None:
                continue
            setattr(act, field, changes[field])
    if "archived" in changes:
        if changes["archived"] and act.archived_at is None and act.kind == "timed":
            draft = ctx.db.execute(
                select(TimerDraft).where(TimerDraft.child_id == ctx.child_id, TimerDraft.activity_id == act.id)
            ).scalar_one_or_none()
            if draft is not None and draft.state != "idle":
                raise ApiError(409, "invalid_timer_state", "Сначала сохрани или сбрось таймер этого занятия.")
        if changes["archived"] and act.archived_at is None:
            act.archived_at = clock.now()
            if act.kind == "boolean":
                sched.end_after(ctx.db, ctx.child_id, act.id, ctx.today)
        elif not changes["archived"]:
            act.archived_at = None
    act.revision += 1
    act.updated_at = clock.now()
    after = {k: getattr(act, k) for k in ("name", "objective", "target_seconds", "reward_eligible", "sort_order")}
    after["archived"] = act.archived_at is not None
    audit.record(ctx.db, actor_id=ctx.actor_id, child_id=ctx.child_id, action="activity.update",
                 target_type="activity", target_id=act.id, before=before, after=after)
    ctx.db.commit()
    return serialize(ctx, act)
