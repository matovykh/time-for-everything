from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import Ctx, get_ctx
from app.modules.rewards import service
from app.modules.wallet import service as wallet

router = APIRouter(tags=["rewards"])


@router.get("/rewards")
def get_rewards(ctx: Ctx = Depends(get_ctx)) -> dict:
    return service.overview(ctx)


@router.post("/rewards/evaluate")
def evaluate(ctx: Ctx = Depends(get_ctx)) -> dict:
    processed = service.evaluate_due(ctx.db, ctx.child, ctx.today, ctx.actor_id)
    return {"processed": processed, "balance": wallet.balance_of(ctx.db, ctx.child_id)}


@router.get("/wallet")
def get_wallet(limit: Annotated[int, Query(ge=1, le=200)] = 50,
               cursor: Annotated[str | None, Query(max_length=300)] = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    return wallet.ledger(ctx.db, ctx.child_id, limit, cursor)
