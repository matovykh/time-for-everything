from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from app.core import idempotency
from app.core.deps import Ctx, get_ctx
from app.core.schemas import Note, Revision, Strict, Workload
from app.modules.activities.service import get_timed_activity
from app.modules.timers import service

router = APIRouter(tags=["timers"])


class TimerCommandIn(Strict):
    revision: Revision


class TimerSaveIn(Strict):
    revision: Revision
    activity_date: date | None = None
    confirm_long_session: bool = False
    duration_seconds: Annotated[int, Field(strict=True, ge=1, le=86400)] | None = None
    note: Note = ""
    workload: Workload = "normal"


@router.get("/timers")
def list_timers(ctx: Ctx = Depends(get_ctx)) -> dict:
    return {"items": service.active_timers(ctx)}


@router.get("/activities/{activity_id}/timer")
def get_timer(activity_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict:
    act = get_timed_activity(ctx, activity_id)
    return service.timer_dict(act.id, service.drafts_by_activity(ctx.db, ctx.child_id).get(act.id))


@router.post("/activities/{activity_id}/timer/save", status_code=201)
def save_timer(activity_id: uuid.UUID, body: TimerSaveIn, request: Request,
               ctx: Ctx = Depends(get_ctx)) -> JSONResponse:
    key = idempotency.read_key(request, required=True)
    return idempotency.run(
        ctx.db, ctx.actor_id, key, request, body.model_dump(mode="json"),
        lambda: service.save(ctx, activity_id, **body.model_dump()), child_id=ctx.child_id,
    )


@router.post("/activities/{activity_id}/timer/{cmd}")
def timer_command(activity_id: uuid.UUID, cmd: Literal["start", "pause", "reset"], body: TimerCommandIn,
                  request: Request, ctx: Ctx = Depends(get_ctx)) -> JSONResponse:
    key = idempotency.read_key(request, required=True)
    return idempotency.run(
        ctx.db, ctx.actor_id, key, request, body.model_dump(mode="json"),
        lambda: service.command(ctx, activity_id, cmd, body.revision), child_id=ctx.child_id,
    )
