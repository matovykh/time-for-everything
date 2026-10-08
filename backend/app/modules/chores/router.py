from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.core.deps import Ctx, get_ctx
from app.core.errors import validation
from app.core.schemas import Strict
from app.modules.chores import service

router = APIRouter(tags=["chores"])


class CompletionIn(Strict):
    completed: bool


class DayStatusIn(Strict):
    status: Literal["no_walk", "excluded"] | None


@router.get("/chores")
def list_chores(day: Annotated[date | None, Query(alias="date")] = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.chores_for(ctx, day or ctx.today)


@router.put("/chores/{activity_id}/completions/{day}")
def put_completion(activity_id: uuid.UUID, day: date, body: CompletionIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.set_completion(ctx, activity_id, day, body.completed)


@router.get("/day-statuses")
def list_day_statuses(category: Literal["walk"] = "walk",
                      from_: Annotated[date | None, Query(alias="from")] = None, to: date | None = None,
                      ctx: Ctx = Depends(get_ctx)) -> dict:
    end = to or ctx.today
    start = from_ or end - timedelta(days=27)
    if start > end or (end - start).days > 366:
        raise validation("validation_error", "Диапазон до 366 дней.", "from")
    return {"items": service.list_day_statuses(ctx, category, start, end)}


@router.put("/day-statuses/{category}/{day}")
def put_day_status(category: Literal["walk"], day: date, body: DayStatusIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.set_day_status(ctx, category, day, body.status)
