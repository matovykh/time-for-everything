from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field

from app.core import idempotency
from app.core.deps import Ctx, get_ctx
from app.core.schemas import Note, Revision, Strict, Workload
from app.modules.activities.service import ensure_active, get_timed_activity
from app.modules.entries import service

router = APIRouter(tags=["entries"])


class EntryCreate(Strict):
    activity_date: date
    duration_seconds: Annotated[int, Field(strict=True, ge=60, le=86400)]
    note: Note = ""
    workload: Workload = "normal"


class EntryPatch(Strict):
    revision: Revision
    activity_date: date | None = None
    duration_seconds: Annotated[int, Field(strict=True, ge=1, le=86400)] | None = None
    note: Note | None = None
    workload: Workload | None = None


class QualityIn(Strict):
    revision: Revision
    quality_status: Literal["confirmed", "rejected", "pending"]


@router.get("/activities/{activity_id}/entries")
def list_entries(activity_id: uuid.UUID, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                 cursor: Annotated[str | None, Query(max_length=300)] = None,
                 ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.list_entries(ctx, get_timed_activity(ctx, activity_id), limit, cursor)


@router.get("/activities/{activity_id}/daily-totals")
def daily_totals(activity_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.daily_totals(ctx, get_timed_activity(ctx, activity_id))


@router.post("/activities/{activity_id}/entries", status_code=201)
def create_entry(activity_id: uuid.UUID, body: EntryCreate, request: Request,
                 ctx: Ctx = Depends(get_ctx)) -> JSONResponse:
    key = idempotency.read_key(request, required=False)

    def action() -> tuple[int, dict]:
        act = get_timed_activity(ctx, activity_id)
        ensure_active(act)
        return service.create_manual(ctx, act, **body.model_dump())

    return idempotency.run(ctx.db, ctx.actor_id, key, request, body.model_dump(mode="json"), action,
                           child_id=ctx.child_id)


@router.patch("/entries/{entry_id}")
def patch_entry(entry_id: uuid.UUID, body: EntryPatch, ctx: Ctx = Depends(get_ctx)) -> dict:
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    revision = changes.pop("revision")
    return service.update_entry(ctx, entry_id, revision, changes)


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: uuid.UUID, revision: Annotated[int, Query(ge=0)], ctx: Ctx = Depends(get_ctx)) -> Response:
    service.delete_entry(ctx, entry_id, revision)
    return Response(status_code=204)


@router.put("/entries/{entry_id}/quality")
def set_quality(entry_id: uuid.UUID, body: QualityIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.set_quality(ctx, entry_id, body.revision, body.quality_status)
