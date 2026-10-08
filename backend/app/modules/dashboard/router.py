"""Composite read model for the «Мой день» screen. Read-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.core.deps import Ctx, get_ctx
from app.db.models import Activity, TimeEntry
from app.modules.chores.service import chores_for
from app.modules.rewards import service as rewards
from app.modules.timers.service import active_timers
from app.modules.wallet.service import balance_of
from app.modules.world.catalog import THEMES_BY_CODE
from app.modules.world.service import collection

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(get_ctx)) -> dict:
    today = ctx.today
    walk = ctx.db.execute(
        select(Activity).where(Activity.child_id == ctx.child_id, Activity.category == "walk",
                               Activity.archived_at.is_(None)).order_by(Activity.sort_order)
    ).scalars().first()
    walk_info = None
    if walk is not None:
        seconds = ctx.db.execute(
            select(func.coalesce(func.sum(TimeEntry.duration_seconds), 0)).where(
                TimeEntry.child_id == ctx.child_id, TimeEntry.activity_id == walk.id,
                TimeEntry.activity_date == today, TimeEntry.deleted_at.is_(None))
        ).scalar_one()
        walk_info = {"activity_id": str(walk.id), "today_seconds": int(seconds), "target_seconds": walk.target_seconds}
    worlds = collection(ctx)
    active = next((w for w in worlds["items"] if w["code"] == worlds["active_world"]), None)
    preview = rewards.preview(ctx)
    return {
        "today": today.isoformat(),
        "timezone": ctx.child.timezone,
        "display_name": ctx.child.display_name,
        "balance": balance_of(ctx.db, ctx.child_id),
        "walk": walk_info,
        "chores": chores_for(ctx, today),
        "timers": active_timers(ctx),
        "world": {
            "active_world": worlds["active_world"],
            "name": THEMES_BY_CODE[worlds["active_world"]].name if worlds["active_world"] else None,
            "level": active["level"] if active else 0,
            "next_upgrade": active["next_upgrade"] if active else None,
        },
        "rewards": {"next_evaluation_on": rewards.next_evaluation_on(ctx.db, ctx.child, today).isoformat(),
                    "preview_total": preview["total"]},
    }
