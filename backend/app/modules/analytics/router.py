"""Read-only aggregations (analytics never changes state)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.deps import Ctx, get_ctx
from app.core.errors import validation
from app.db.models import Activity, TimeEntry

router = APIRouter(tags=["analytics"])

CATEGORY_SERIES = [("lessons", "Уроки"), ("walk", "Прогулки"), ("other", "Другие занятия")]
CATEGORY_KEY = {"lesson": "lessons", "walk": "walk", "reading": "other", "custom": "other"}


def week_start(d: date) -> date:
    return d - timedelta(days=d.isoweekday() - 1)


def aggregate(ctx: Ctx, bucket: str, group_by: str, start: date, end: date) -> dict[str, Any]:
    today = ctx.today
    rows = ctx.db.execute(
        select(TimeEntry.activity_date, Activity.id, Activity.name, Activity.category,
               func.sum(TimeEntry.duration_seconds))
        .join(Activity, Activity.id == TimeEntry.activity_id)
        .where(TimeEntry.child_id == ctx.child_id, Activity.child_id == ctx.child_id,
               TimeEntry.deleted_at.is_(None), TimeEntry.activity_date >= start, TimeEntry.activity_date <= end)
        .group_by(TimeEntry.activity_date, Activity.id, Activity.name, Activity.category)
    ).all()
    if group_by == "category":
        series = [{"key": k, "label": label} for k, label in CATEGORY_SERIES]
    else:
        acts = ctx.db.execute(
            select(Activity).where(Activity.child_id == ctx.child_id, Activity.kind == "timed")
            .order_by(Activity.sort_order, Activity.created_at)
        ).scalars()
        series = [{"key": str(a.id), "label": a.name} for a in acts]
    keys = [s["key"] for s in series]

    step = 7 if bucket == "week" else 1
    buckets: list[dict[str, Any]] = []
    index: dict[date, dict[str, int]] = {}
    cursor = start
    while cursor <= end:
        b_end = cursor + timedelta(days=step - 1)
        totals = dict.fromkeys(keys, 0)
        index[cursor] = totals
        buckets.append({"start": cursor.isoformat(), "end": b_end.isoformat(), "complete": b_end < today,
                        "totals": totals, "total_seconds": 0})
        cursor = b_end + timedelta(days=1)
    overall: dict[str, int] = defaultdict(int)
    for day, act_id, _name, category, seconds in rows:
        key = CATEGORY_KEY[category] if group_by == "category" else str(act_id)
        b_start = week_start(day) if bucket == "week" else day
        totals = index.get(b_start)
        if totals is None or key not in totals:
            continue
        totals[key] += int(seconds)
        overall[key] += int(seconds)
    for b in buckets:
        b["total_seconds"] = sum(b["totals"].values())
    totals_all = {k: overall.get(k, 0) for k in keys}
    return {
        "timezone": ctx.child.timezone, "bucket": bucket, "group_by": group_by,
        "from": start.isoformat(), "to": end.isoformat(), "series": series, "buckets": buckets,
        "totals": totals_all, "total_seconds": sum(totals_all.values()),
    }


@router.get("/analytics/time")
def time_analytics(
    bucket: Literal["week", "day"] = "week",
    group_by: Literal["category", "activity"] = "category",
    weeks: Annotated[int, Query(ge=1, le=52)] = 4,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    ctx: Ctx = Depends(get_ctx),
) -> dict:
    if bucket == "week":
        current = week_start(ctx.today)
        start, end = current - timedelta(days=7 * (weeks - 1)), current + timedelta(days=6)
    else:
        if from_ is None or to is None:
            raise validation("validation_error", "Для bucket=day нужны from и to.", "from")
        if from_ > to or (to - from_).days >= 366:
            raise validation("validation_error", "Диапазон — не больше 366 дней.", "from")
        start, end = from_, to
    return aggregate(ctx, bucket, group_by, start, end)
