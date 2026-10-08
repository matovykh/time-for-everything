from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from app.core.deps import Ctx, get_ctx
from app.core.schemas import Icon, Name, Revision, ScheduleIn, Strict
from app.modules.activities import service

router = APIRouter(tags=["activities"])

TargetSeconds = Annotated[int, Field(strict=True, ge=60, le=86400)]


class ActivityCreate(Strict):
    name: Name
    kind: Literal["timed", "boolean"]
    icon: Icon | None = None
    objective: Literal["none", "reach", "maintain"] | None = None
    target_seconds: TargetSeconds | None = None
    sort_order: Annotated[int, Field(strict=True, ge=0, le=100000)] | None = None
    schedule: ScheduleIn | None = None


class ActivityPatch(Strict):
    revision: Revision
    name: Name | None = None
    icon: Icon | None = None
    sort_order: Annotated[int, Field(strict=True, ge=0, le=100000)] | None = None
    objective: Literal["decrease", "reach", "maintain", "none"] | None = None
    target_seconds: TargetSeconds | None = None
    archived: bool | None = None
    schedule: ScheduleIn | None = None
    reward_eligible: bool | None = None


@router.get("/activities")
def list_activities(include_archived: bool = False, ctx: Ctx = Depends(get_ctx)) -> dict:
    return {"items": service.list_activities(ctx, include_archived)}


@router.get("/activities/{activity_id}")
def get_activity(activity_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.serialize(ctx, service.get_activity(ctx, activity_id))


@router.post("/activities", status_code=201)
def create_activity(body: ActivityCreate, ctx: Ctx = Depends(get_ctx)) -> JSONResponse:
    data = body.model_dump()
    return JSONResponse(service.create_activity(ctx, data), status_code=201)


@router.patch("/activities/{activity_id}")
def patch_activity(activity_id: uuid.UUID, body: ActivityPatch, ctx: Ctx = Depends(get_ctx)) -> dict:
    changes = body.model_dump(exclude_unset=True)
    revision = changes.pop("revision")
    for nullable_forbidden in ("name", "objective", "archived", "reward_eligible"):
        if nullable_forbidden in changes and changes[nullable_forbidden] is None:
            changes.pop(nullable_forbidden)
    return service.update_activity(ctx, activity_id, revision, changes)
