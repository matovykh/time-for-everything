"""Living worlds: collection (shelf), catalog, details and transactional purchases.

The game never mints stars: purchases only debit the wallet. Prices and prerequisites are read
from `world_catalog` rows in the same transaction as the debit.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core import audit
from app.core.clock import clock, iso
from app.core.deps import Ctx
from app.core.errors import ApiError, not_found
from app.db.models import ChildWorld, Profile, WorldCatalogItem, WorldEvent, WorldUnlock
from app.modules.wallet import service as wallet
from app.modules.world.catalog import THEMES, THEMES_BY_CODE, UPGRADE_INDEX, UPGRADES, theme_summary


def _theme(code: str):
    t = THEMES_BY_CODE.get(code)
    if t is None:
        raise not_found("Мир не найден.")
    return t


def _unlocked(ctx: Ctx) -> dict[str, dict[str, WorldUnlock]]:
    out: dict[str, dict[str, WorldUnlock]] = {}
    for u in ctx.db.execute(select(WorldUnlock).where(WorldUnlock.child_id == ctx.child_id)).scalars():
        out.setdefault(u.theme_code, {})[u.upgrade_code] = u
    return out


def _next_upgrade(theme_code: str, owned: set[str]) -> dict[str, Any] | None:
    t = THEMES_BY_CODE[theme_code]
    for i, u in enumerate(UPGRADES):
        if u.code not in owned:
            return {"code": u.code, "title": t.titles[i], "cost": u.cost}
    return None


def _shelf_item(cw: ChildWorld, owned: dict[str, WorldUnlock]) -> dict[str, Any]:
    t = THEMES_BY_CODE[cw.theme_code]
    codes = [u.code for u in UPGRADES if u.code in owned]
    return {**theme_summary(t), "position": cw.position, "added_at": iso(cw.added_at), "level": len(codes),
            "unlocked": codes, "next_upgrade": _next_upgrade(cw.theme_code, set(codes))}


def _shelf(ctx: Ctx) -> list[ChildWorld]:
    return list(ctx.db.execute(
        select(ChildWorld).where(ChildWorld.child_id == ctx.child_id).order_by(ChildWorld.position, ChildWorld.added_at)
    ).scalars())


def collection(ctx: Ctx) -> dict[str, Any]:
    unlocked = _unlocked(ctx)
    return {"active_world": ctx.child.active_world, "balance": wallet.balance_of(ctx.db, ctx.child_id),
            "items": [_shelf_item(cw, unlocked.get(cw.theme_code, {})) for cw in _shelf(ctx)]}


def catalog(ctx: Ctx, search: str | None) -> dict[str, Any]:
    q = (search or "").strip().casefold()
    owned = {cw.theme_code for cw in _shelf(ctx)}
    unlocked = _unlocked(ctx)
    items = []
    for t in THEMES:
        if q and q not in f"{t.name} {t.type}".casefold():
            continue
        items.append({**theme_summary(t), "in_collection": t.code in owned, "level": len(unlocked.get(t.code, {}))})
    return {"items": items, "next_cursor": None}


def add_to_collection(ctx: Ctx, theme_code: str) -> tuple[int, dict[str, Any]]:
    _theme(theme_code)
    existing = ctx.db.execute(
        select(ChildWorld).where(ChildWorld.child_id == ctx.child_id, ChildWorld.theme_code == theme_code)
    ).scalar_one_or_none()
    created = False
    if existing is None:
        position = ctx.db.execute(
            select(func.coalesce(func.max(ChildWorld.position), -1)).where(ChildWorld.child_id == ctx.child_id)
        ).scalar_one() + 1
        try:
            ctx.db.add(ChildWorld(child_id=ctx.child_id, theme_code=theme_code, position=position,
                                  added_at=clock.now()))
            ctx.db.commit()
            created = True
        except IntegrityError:
            ctx.db.rollback()
        existing = ctx.db.execute(
            select(ChildWorld).where(ChildWorld.child_id == ctx.child_id, ChildWorld.theme_code == theme_code)
        ).scalar_one()
    owned = _unlocked(ctx).get(theme_code, {})
    return (201 if created else 200), {"item": _shelf_item(existing, owned), "created": created}


def set_active(ctx: Ctx, theme_code: str) -> dict[str, Any]:
    _theme(theme_code)
    cw = ctx.db.execute(
        select(ChildWorld).where(ChildWorld.child_id == ctx.child_id, ChildWorld.theme_code == theme_code)
    ).scalar_one_or_none()
    if cw is None:
        raise ApiError(409, "not_in_collection", "Сначала добавь этот мир в коллекцию.")
    profile = ctx.db.get(Profile, ctx.child_id)
    profile.active_world = theme_code
    profile.updated_at = clock.now()
    ctx.db.commit()
    return {"active_world": theme_code}


def _child_world(ctx: Ctx, theme_code: str, for_update: bool = False) -> ChildWorld:
    _theme(theme_code)
    q = select(ChildWorld).where(ChildWorld.child_id == ctx.child_id, ChildWorld.theme_code == theme_code)
    cw = ctx.db.execute(q.with_for_update() if for_update else q).scalar_one_or_none()
    if cw is None:
        raise ApiError(404, "not_in_collection", "Этого мира нет в твоей коллекции.")
    return cw


def detail(ctx: Ctx, theme_code: str) -> dict[str, Any]:
    cw = _child_world(ctx, theme_code)
    t = THEMES_BY_CODE[theme_code]
    owned = _unlocked(ctx).get(theme_code, {})
    prices = {c.code: c for c in ctx.db.execute(
        select(WorldCatalogItem).where(WorldCatalogItem.theme_code == theme_code)).scalars()}
    balance = wallet.balance_of(ctx.db, ctx.child_id)
    level = sum(1 for u in UPGRADES if u.code in owned)
    upgrades = []
    for i, u in enumerate(UPGRADES):
        row = prices.get(u.code)
        cost = row.cost if row else u.cost
        requires = row.requires_code if row else u.requires
        is_owned = u.code in owned
        reason = ("already_owned" if is_owned else "prerequisite_missing" if requires and requires not in owned
                  else "insufficient_balance" if balance < cost else None)
        upgrades.append({
            "code": u.code, "index": i, "title": t.titles[i], "effect": t.effects[i], "kind": u.kind,
            "space": u.space, "cost": cost, "requires": requires, "owned": is_owned,
            "purchased_at": iso(owned[u.code].purchased_at) if is_owned else None,
            "can_purchase": reason is None, "blocked_reason": reason,
        })
    events = ctx.db.execute(
        select(WorldEvent).where(WorldEvent.child_world_id == cw.id, WorldEvent.child_id == ctx.child_id)
        .order_by(WorldEvent.created_at.desc()).limit(50)
    ).scalars()
    return {
        "theme": theme_summary(t), "level": level, "territories": 1 + (level >= 1) + (level >= 3),
        "inhabitants": 2 + 2 * level, "balance": balance, "upgrades": upgrades,
        "events": [{"id": str(e.id), "upgrade_code": e.upgrade_code, "event_type": e.event_type,
                    "text": t.effects[UPGRADE_INDEX[e.upgrade_code]], "created_at": iso(e.created_at)}
                   for e in events],
    }


def purchase(ctx: Ctx, theme_code: str, upgrade_code: str) -> tuple[int, dict[str, Any]]:
    """One transaction: lock wallet → validate → debit → unlock → event (commit by caller)."""
    wallet.lock_account(ctx.db, ctx.child_id)
    cw = _child_world(ctx, theme_code, for_update=True)
    item = ctx.db.execute(
        select(WorldCatalogItem).where(WorldCatalogItem.theme_code == theme_code, WorldCatalogItem.code == upgrade_code)
    ).scalar_one_or_none()
    if item is None:
        raise not_found("Улучшение не найдено.")
    owned = set(ctx.db.execute(
        select(WorldUnlock.upgrade_code)
        .where(WorldUnlock.child_world_id == cw.id, WorldUnlock.child_id == ctx.child_id)
    ).scalars())
    if upgrade_code in owned:
        raise ApiError(409, "already_owned", "Это улучшение уже открыто.")
    if item.requires_code and item.requires_code not in owned:
        raise ApiError(409, "prerequisite_missing", "Сначала открой предыдущий этап.",
                       details={"requires": item.requires_code})
    t = THEMES_BY_CODE[theme_code]
    unlock_id = uuid.uuid4()
    tx = wallet.post(ctx.db, child_id=ctx.child_id, amount=-item.cost, reason_code="world_purchase",
                     description=f"{t.name} · {t.titles[UPGRADE_INDEX[upgrade_code]]}",
                     idempotency_key=f"purchase:{cw.id}:{upgrade_code}", source_type="world_unlock",
                     source_id=unlock_id, actor_id=ctx.actor_id)
    now = clock.now()
    unlock = WorldUnlock(id=unlock_id, child_id=ctx.child_id, child_world_id=cw.id, theme_code=theme_code,
                         upgrade_code=upgrade_code, cost=item.cost, transaction_id=tx.id, purchased_at=now)
    ctx.db.add(unlock)
    ctx.db.add(WorldEvent(child_id=ctx.child_id, child_world_id=cw.id, theme_code=theme_code,
                          upgrade_code=upgrade_code, event_type="upgrade_unlocked", created_at=now))
    audit.record(ctx.db, actor_id=ctx.actor_id, child_id=ctx.child_id, action="world.purchase",
                 target_type="world_unlock", target_id=unlock_id,
                 after={"theme": theme_code, "upgrade": upgrade_code, "cost": item.cost})
    ctx.db.flush()
    return 201, {
        "purchase": {"id": str(unlock_id), "upgrade_code": upgrade_code, "cost": item.cost,
                     "purchased_at": iso(now), "transaction_id": str(tx.id)},
        "balance": tx.balance_after,
        "world": detail(ctx, theme_code),
    }
