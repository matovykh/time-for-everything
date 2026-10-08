"""Versioned weekly schedules for chores. Weekdays are ISO (1 = Monday … 7 = Sunday)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Schedule


def mask_from_weekdays(weekdays: Iterable[int]) -> int:
    mask = 0
    for d in weekdays:
        if not 1 <= d <= 7:
            raise ValueError("weekday out of range")
        mask |= 1 << (d - 1)
    return mask


def weekdays_from_mask(mask: int) -> list[int]:
    return [d for d in range(1, 8) if mask & (1 << (d - 1))]


def version_for(versions: list[Schedule], day: date) -> Schedule | None:
    for v in versions:
        if v.starts_on <= day and (v.ends_on is None or v.ends_on >= day):
            return v
    return None


def is_scheduled(versions: list[Schedule], day: date) -> bool:
    v = version_for(versions, day)
    return bool(v and v.weekdays_mask & (1 << (day.isoweekday() - 1)))


def display_version(versions: list[Schedule], today: date) -> Schedule | None:
    """Version effective today, else the next upcoming one, else the latest past one."""
    current = version_for(versions, today)
    if current:
        return current
    upcoming = sorted((v for v in versions if v.starts_on > today), key=lambda v: v.starts_on)
    if upcoming:
        return upcoming[0]
    return max(versions, key=lambda v: v.starts_on) if versions else None


def schedule_dict(v: Schedule | None) -> dict | None:
    if v is None:
        return None
    return {
        "weekdays": weekdays_from_mask(v.weekdays_mask),
        "starts_on": v.starts_on.isoformat(),
        "ends_on": v.ends_on.isoformat() if v.ends_on else None,
    }


def load_versions(db: Session, child_id: uuid.UUID, activity_ids: Iterable[uuid.UUID] | None = None
                  ) -> dict[uuid.UUID, list[Schedule]]:
    q = select(Schedule).where(Schedule.child_id == child_id)
    if activity_ids is not None:
        ids = list(activity_ids)
        if not ids:
            return {}
        q = q.where(Schedule.activity_id.in_(ids))
    result: dict[uuid.UUID, list[Schedule]] = defaultdict(list)
    for s in db.execute(q.order_by(Schedule.starts_on)).scalars():
        result[s.activity_id].append(s)
    return result


def replace_from(db: Session, child_id: uuid.UUID, activity_id: uuid.UUID, weekdays: list[int],
                 starts_on: date, ends_on: date | None, actor_id: uuid.UUID) -> None:
    """New version from `starts_on`; earlier versions end the day before; later ones are dropped."""
    versions = load_versions(db, child_id, [activity_id]).get(activity_id, [])
    for v in versions:
        if v.starts_on >= starts_on:
            db.delete(v)
        elif v.ends_on is None or v.ends_on >= starts_on:
            v.ends_on = starts_on - timedelta(days=1)
    db.flush()
    db.add(Schedule(child_id=child_id, activity_id=activity_id, weekdays_mask=mask_from_weekdays(weekdays),
                    starts_on=starts_on, ends_on=ends_on, created_by=actor_id))


def end_after(db: Session, child_id: uuid.UUID, activity_id: uuid.UUID, last_day: date) -> None:
    """Stop scheduling after `last_day` (used when archiving)."""
    for v in load_versions(db, child_id, [activity_id]).get(activity_id, []):
        if v.starts_on > last_day:
            db.delete(v)
        elif v.ends_on is None or v.ends_on > last_day:
            v.ends_on = last_day
