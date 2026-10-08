from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import StringConstraints

from app.core import idempotency
from app.core.deps import Ctx, get_ctx
from app.core.schemas import Strict
from app.modules.world import service

router = APIRouter(tags=["world"])

Code = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{1,32}$")]


class ThemeIn(Strict):
    theme_code: Code


class PurchaseIn(Strict):
    upgrade_code: Code


@router.get("/world-catalog")
def world_catalog(search: Annotated[str | None, Query(max_length=100)] = None,
                  cursor: Annotated[str | None, Query(max_length=100)] = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.catalog(ctx, search)


@router.get("/worlds")
def worlds(ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.collection(ctx)


@router.post("/worlds", status_code=201)
def add_world(body: ThemeIn, ctx: Ctx = Depends(get_ctx)) -> JSONResponse:
    status, payload = service.add_to_collection(ctx, body.theme_code)
    return JSONResponse(payload, status_code=status)


@router.put("/me/active-world")
def set_active_world(body: ThemeIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.set_active(ctx, body.theme_code)


@router.get("/worlds/{theme_code}")
def world_detail(theme_code: Code, ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.detail(ctx, theme_code)


@router.post("/worlds/{theme_code}/purchases", status_code=201)
def purchase(theme_code: Code, body: PurchaseIn, request: Request, ctx: Ctx = Depends(get_ctx)) -> JSONResponse:
    key = idempotency.read_key(request, required=True)
    return idempotency.run(ctx.db, ctx.actor_id, key, request, body.model_dump(),
                           lambda: service.purchase(ctx, theme_code, body.upgrade_code), child_id=ctx.child_id)
