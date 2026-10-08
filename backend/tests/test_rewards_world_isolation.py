from __future__ import annotations

import threading
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import GuardianChild, Profile, RewardEvaluation, WalletTransaction, WorldUnlock
from app.modules.wallet import service as wallet
from tests.conftest import FIXED_NOW, set_now


def at(day: date, hour_utc: int = 9) -> None:
    set_now(FIXED_NOW.replace(year=day.year, month=day.month, day=day.day, hour=hour_utc))


def make_guardian(make_api, engine, child) -> object:
    g = make_api()
    assert g.get("/api/v1/me").status_code == 200
    with Session(engine) as db:  # operator action: role + link are DB-only in the MVP
        db.get(Profile, g.user_id).role = "guardian"
        db.add(GuardianChild(guardian_id=g.user_id, child_id=child.user_id))
        db.commit()
    g.client.headers["X-Child-Id"] = str(child.user_id)
    return g


def grant(engine, child_id, amount: int) -> None:
    with Session(engine) as db:
        wallet.post(db, child_id=child_id, amount=amount, reason_code="adjustment", description="test grant",
                    idempotency_key=f"test:{uuid.uuid4()}")
        db.commit()


# ---- rewards --------------------------------------------------------------------------------
def fill_two_weeks(api, guardian):
    math, walk = api.activity("math")["id"], api.activity("walk")["id"]
    # lessons: 35 min baseline (Oct 6-8), 30 min current (Oct 13-15); guardian confirms quality
    for d, m in ((6, 35), (7, 35), (8, 35), (13, 30), (14, 30), (15, 30)):
        at(date(2026, 10, d))
        e = api.post(f"/api/v1/activities/{math}/entries",
                     json={"activity_date": f"2026-10-{d:02d}", "duration_seconds": m * 60}).json()
        r = guardian.put(f"/api/v1/entries/{e['id']}/quality", json={"revision": 1, "quality_status": "confirmed"})
        assert r.status_code == 200, r.text
    # walk 120 min every day of the window; chores done every day on the day itself
    for d in range(13, 20):
        day = date(2026, 10, d)
        at(day)
        api.post(f"/api/v1/activities/{walk}/entries", json={"activity_date": day.isoformat(),
                                                             "duration_seconds": 7200})
        for item in api.get("/api/v1/chores").json()["items"]:
            if item["scheduled"]:
                assert api.put(f"/api/v1/chores/{item['activity_id']}/completions/{day}",
                               json={"completed": True}).status_code == 200


def test_weekly_evaluation_pays_once(api, make_api, engine):
    guardian = make_guardian(make_api, engine, api)
    fill_two_weeks(api, guardian)
    at(date(2026, 10, 19))
    assert api.post("/api/v1/rewards/evaluate").json()["processed"] == []  # not due yet
    preview = api.get("/api/v1/rewards").json()
    assert preview["first_evaluation_on"] == "2026-10-20" and preview["preview"]["total"] > 0
    assert api.get("/api/v1/wallet").json()["balance"] == 0  # preview never pays

    at(date(2026, 10, 20))
    r = api.post("/api/v1/rewards/evaluate").json()
    by_cat = {p["category"]: p for p in r["processed"]}
    assert by_cat["walk"] == {"period_end": "2026-10-19", "category": "walk", "state": "final", "amount": 40}
    assert by_cat["chores"]["amount"] == 29  # N = 13, C = 13 → 20 + 4 + 5
    assert by_cat["lessons"]["amount"] == 20  # 35 → 30 min
    assert r["balance"] == 89

    # repeated calls, daily views and the next day never pay again
    assert api.post("/api/v1/rewards/evaluate").json() == {"processed": [], "balance": 89}
    at(date(2026, 10, 21))
    api.get("/api/v1/rewards")
    assert api.post("/api/v1/rewards/evaluate").json()["processed"] == []
    ledger = api.get("/api/v1/wallet").json()
    assert ledger["balance"] == 89 and [t["reason_code"] for t in ledger["items"]].count("reward_walk") == 1
    rewards = api.get("/api/v1/rewards").json()
    ev = rewards["evaluations"][0]
    assert ev["period_end"] == "2026-10-19" and ev["total_awarded"] == 89
    assert {c["state"] for c in ev["categories"]} == {"final"}
    assert rewards["next_evaluation_on"] == "2026-10-27"

    # late edits after finalisation do not re-pay or rewrite history
    walk = api.activity("walk")["id"]
    api.post(f"/api/v1/activities/{walk}/entries", json={"activity_date": "2026-10-13", "duration_seconds": 600})
    api.post("/api/v1/rewards/evaluate")
    assert api.get("/api/v1/wallet").json()["balance"] == 89


def test_pending_lessons_defer_then_finalize_without_reward(api, engine):
    math = api.activity("math")["id"]
    for d, m in ((6, 35), (7, 35), (8, 35), (13, 30), (14, 30), (15, 30)):
        at(date(2026, 10, d))
        api.post(f"/api/v1/activities/{math}/entries",
                 json={"activity_date": f"2026-10-{d:02d}", "duration_seconds": m * 60})
    at(date(2026, 10, 20))
    r = {p["category"]: p for p in api.post("/api/v1/rewards/evaluate").json()["processed"]}
    assert r["lessons"]["state"] == "deferred" and r["walk"]["state"] == "deferred"  # walk days missing
    assert r["chores"]["state"] == "final" and r["chores"]["amount"] == 0
    at(date(2026, 10, 27))  # grace over: finalise period 1, period 2 still waits for data
    r = api.post("/api/v1/rewards/evaluate").json()["processed"]
    p1 = {p["category"]: p for p in r if p["period_end"] == "2026-10-19"}
    assert p1["lessons"] == {"period_end": "2026-10-19", "category": "lessons", "state": "final", "amount": 0}
    assert p1["walk"]["state"] == "final" and p1["walk"]["amount"] == 0
    assert "chores" not in p1  # already final, never recomputed
    with Session(engine) as db:
        assert db.execute(select(func.count()).select_from(WalletTransaction)).scalar_one() == 0


def test_concurrent_evaluations_do_not_double_pay(api, make_api, engine):
    guardian = make_guardian(make_api, engine, api)
    fill_two_weeks(api, guardian)
    at(date(2026, 10, 20))
    results = []

    def run():
        results.append(api.post("/api/v1/rewards/evaluate").status_code)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(results) == {200}
    assert api.get("/api/v1/wallet").json()["balance"] == 89
    with Session(engine) as db:
        assert db.execute(select(func.count()).select_from(RewardEvaluation)).scalar_one() == 3


# ---- worlds ---------------------------------------------------------------------------------
def buy(api, theme, upgrade, key=None):
    return api.post(f"/api/v1/worlds/{theme}/purchases", json={"upgrade_code": upgrade},
                    headers={"Idempotency-Key": key or uuid.uuid4().hex})


def test_world_catalog_collection_and_switching(api):
    cat = api.get("/api/v1/world-catalog").json()["items"]
    assert [t["code"] for t in cat] == ["settlers", "bricks", "voxel", "helpers"]
    assert [t["in_collection"] for t in cat] == [True, False, False, False]
    found = api.get("/api/v1/world-catalog", params={"search": "КУБИЧ"}).json()["items"]
    assert [t["code"] for t in found] == ["voxel"]
    assert api.put("/api/v1/me/active-world", json={"theme_code": "bricks"}).json()["code"] == "not_in_collection"
    assert api.post("/api/v1/worlds", json={"theme_code": "bricks"}).status_code == 201
    again = api.post("/api/v1/worlds", json={"theme_code": "bricks"})
    assert again.status_code == 200 and again.json()["created"] is False
    assert api.post("/api/v1/worlds", json={"theme_code": "nope"}).status_code == 404
    assert api.put("/api/v1/me/active-world", json={"theme_code": "bricks"}).json() == {"active_world": "bricks"}
    w = api.get("/api/v1/worlds").json()
    assert w["active_world"] == "bricks" and [i["code"] for i in w["items"]] == ["settlers", "bricks"]
    d = api.get("/api/v1/worlds/bricks").json()
    assert d["level"] == 0 and d["territories"] == 1 and d["inhabitants"] == 2
    assert [u["title"] for u in d["upgrades"]] == ["Долина деталей", "Сборочная станция", "Грузовой порт",
                                                  "Башня изобретений"]
    assert d["upgrades"][0]["blocked_reason"] == "insufficient_balance"
    assert d["upgrades"][1]["blocked_reason"] == "prerequisite_missing"
    assert api.get("/api/v1/worlds/voxel").json()["code"] == "not_in_collection"


def test_purchase_flow_prerequisites_and_ledger(api, engine):
    grant(engine, api.user_id, 160)
    assert buy(api, "settlers", "workshop").json()["code"] == "prerequisite_missing"
    r = buy(api, "settlers", "meadow")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["balance"] == 100 and body["world"]["level"] == 1 and body["world"]["territories"] == 2
    assert body["world"]["events"][0]["upgrade_code"] == "meadow"
    assert buy(api, "settlers", "meadow").json()["code"] == "already_owned"
    r = buy(api, "settlers", "workshop")
    assert r.json()["balance"] == 10
    assert buy(api, "settlers", "harbor").json()["code"] == "insufficient_balance"
    ledger = api.get("/api/v1/wallet").json()
    assert [t["amount"] for t in ledger["items"]] == [-90, -60, 160]
    assert [t["balance_after"] for t in ledger["items"]] == [10, 100, 160]
    assert ledger["items"][0]["description"] == "Тихая бухта · Ветряная пекарня"
    # worlds keep independent progress; wallet is shared
    api.post("/api/v1/worlds", json={"theme_code": "voxel"})
    assert api.get("/api/v1/worlds/voxel").json()["level"] == 0
    assert api.get("/api/v1/worlds").json()["items"][0]["unlocked"] == ["meadow", "workshop"]


def test_purchase_idempotency_replay(api, engine):
    grant(engine, api.user_id, 100)
    key = uuid.uuid4().hex
    a, b = buy(api, "settlers", "meadow", key), buy(api, "settlers", "meadow", key)
    assert a.status_code == b.status_code == 201 and a.json() == b.json()
    assert api.get("/api/v1/wallet").json()["balance"] == 40


@pytest.mark.parametrize("same_upgrade", [True, False])
def test_concurrent_purchases_never_overspend(api, engine, same_upgrade):
    grant(engine, api.user_id, 100)
    api.post("/api/v1/worlds", json={"theme_code": "bricks"})
    statuses = []
    targets = [("settlers", "meadow"), ("settlers" if same_upgrade else "bricks", "meadow")]

    def run(theme, upgrade):
        statuses.append(buy(api, theme, upgrade).status_code)

    threads = [threading.Thread(target=run, args=t) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [201, 409]
    assert api.get("/api/v1/wallet").json()["balance"] == 40
    with Session(engine) as db:
        assert db.execute(select(func.count()).select_from(WorldUnlock)).scalar_one() == 1


# ---- isolation ------------------------------------------------------------------------------
def test_user_cannot_touch_another_users_data(api, make_api, engine):
    a = api
    b = make_api()
    b.get("/api/v1/me")
    math_a = a.activity("math")["id"]
    entry = a.post(f"/api/v1/activities/{math_a}/entries",
                   json={"activity_date": "2026-10-05", "duration_seconds": 900}).json()
    a.timer(math_a, "start", 0)
    bag_a = a.activity("bag")["id"]
    checks = [
        b.get(f"/api/v1/activities/{math_a}"),
        b.patch(f"/api/v1/activities/{math_a}", json={"revision": 1, "name": "x"}),
        b.get(f"/api/v1/activities/{math_a}/timer"),
        b.timer(math_a, "pause", 1),
        b.timer(math_a, "save", 1),
        b.get(f"/api/v1/activities/{math_a}/entries"),
        b.get(f"/api/v1/activities/{math_a}/daily-totals"),
        b.post(f"/api/v1/activities/{math_a}/entries", json={"activity_date": "2026-10-05", "duration_seconds": 900}),
        b.patch(f"/api/v1/entries/{entry['id']}", json={"revision": 1, "duration_seconds": 60}),
        b.delete(f"/api/v1/entries/{entry['id']}", params={"revision": 1}),
        b.put(f"/api/v1/chores/{bag_a}/completions/2026-10-06", json={"completed": True}),
    ]
    for r in checks:
        assert r.status_code == 404, (r.request.method, r.request.url, r.status_code, r.text)
        assert r.json()["code"] == "not_found"
    # pretending to be a guardian of A without a link
    b.client.headers["X-Child-Id"] = str(a.user_id)
    assert b.get("/api/v1/me").status_code == 404
    del b.client.headers["X-Child-Id"]
    # A's data is unchanged and B sees only its own
    assert a.get(f"/api/v1/activities/{math_a}/timer").json()["state"] == "running"
    assert len(a.get(f"/api/v1/activities/{math_a}/entries").json()["items"]) == 1
    assert math_a not in {x["id"] for x in b.get("/api/v1/activities").json()["items"]}
    assert b.get("/api/v1/timers").json()["items"] == []
    assert b.get("/api/v1/analytics/time").json()["total_seconds"] == 0


def test_service_layer_enforces_owner_without_http(api, make_api, engine):
    """Calling services directly (no UI/router) with another child's context is still rejected."""
    from app.core.deps import Ctx
    from app.core.errors import ApiError
    from app.modules.entries import service as entries
    from app.modules.timers import service as timers

    b = make_api()
    b.get("/api/v1/me")
    math_a = uuid.UUID(api.activity("math")["id"])
    with Session(engine) as db:
        prof_b = db.get(Profile, b.user_id)
        ctx = Ctx(db=db, actor=prof_b, child=prof_b, is_guardian=False)
        with pytest.raises(ApiError) as e1:
            timers.command(ctx, math_a, "start", 0)
        with pytest.raises(ApiError) as e2:
            entries.update_entry(ctx, uuid.uuid4(), 1, {"note": "x"})
    assert e1.value.status == 404 and e2.value.status == 404


def test_guardian_can_act_for_linked_child_only(api, make_api, engine):
    g = make_guardian(make_api, engine, api)
    me = g.get("/api/v1/me").json()
    assert me["acting_child_id"] == str(api.user_id) and me["permissions"]["can_confirm_quality"] is True
    assert me["children"] == [{"id": str(api.user_id), "display_name": me["display_name"]}]
    walk = api.activity("walk")
    r = g.patch(f"/api/v1/activities/{walk['id']}", json={"revision": walk["revision"], "target_seconds": 5400})
    assert r.status_code == 200 and r.json()["target_seconds"] == 5400
    assert g.put("/api/v1/day-statuses/walk/2026-10-05", json={"status": "excluded"}).status_code == 200
    stranger = make_api()
    stranger.get("/api/v1/me")
    g.client.headers["X-Child-Id"] = str(stranger.user_id)
    assert g.get("/api/v1/activities").status_code == 404


# ---- reward-input integrity (child cannot shape what the policy compares) ----------------------------
def test_child_changes_to_reviewed_entries(api, make_api, engine):
    g = make_guardian(make_api, engine, api)
    math = api.activity("math")["id"]
    e = api.post(f"/api/v1/activities/{math}/entries",
                 json={"activity_date": "2026-10-05", "duration_seconds": 2100}).json()
    e = g.put(f"/api/v1/entries/{e['id']}/quality", json={"revision": 1, "quality_status": "confirmed"}).json()
    # note-only edit keeps the review
    e = api.patch(f"/api/v1/entries/{e['id']}", json={"revision": e["revision"], "note": "ok"}).json()
    assert e["quality_status"] == "confirmed"
    # chain exploit: shorten / move out of the reward window / exclude / (reset→) delete — all refused
    attempts = [
        api.patch(f"/api/v1/entries/{e['id']}", json={"revision": e["revision"], "duration_seconds": 1500}),
        api.patch(f"/api/v1/entries/{e['id']}", json={"revision": e["revision"], "activity_date": "2025-01-01"}),
        api.patch(f"/api/v1/entries/{e['id']}", json={"revision": e["revision"], "workload": "excluded"}),
        api.delete(f"/api/v1/entries/{e['id']}", params={"revision": e["revision"]}),
    ]
    assert [r.status_code for r in attempts] == [403, 403, 403, 403]
    current = api.get(f"/api/v1/activities/{math}/entries").json()["items"][0]
    assert (current["duration_seconds"], current["activity_date"], current["quality_status"], current["workload"]) == \
        (2100, "2026-10-05", "confirmed", "normal")
    # rejected entries are frozen the same way
    e = g.put(f"/api/v1/entries/{e['id']}/quality",
              json={"revision": e["revision"], "quality_status": "rejected"}).json()
    assert api.patch(f"/api/v1/entries/{e['id']}",
                     json={"revision": e["revision"], "duration_seconds": 60}).status_code == 403
    assert api.delete(f"/api/v1/entries/{e['id']}", params={"revision": e["revision"]}).status_code == 403
    e = g.put(f"/api/v1/entries/{e['id']}/quality",
              json={"revision": e["revision"], "quality_status": "confirmed"}).json()
    # the guardian may do all of it, and its own measured edit keeps the review
    e = g.patch(f"/api/v1/entries/{e['id']}", json={"revision": e["revision"], "duration_seconds": 1600,
                                                     "workload": "increased"}).json()
    assert e["quality_status"] == "confirmed" and e["workload"] == "increased"
    assert g.delete(f"/api/v1/entries/{e['id']}", params={"revision": e["revision"]}).status_code == 204
    # pending entries stay deletable by the child (typos)
    p = api.post(f"/api/v1/activities/{math}/entries",
                 json={"activity_date": "2026-10-05", "duration_seconds": 600}).json()
    assert api.delete(f"/api/v1/entries/{p['id']}", params={"revision": 1}).status_code == 204


def test_child_cannot_set_non_normal_workload_on_create_or_save(api):
    math = api.activity("math")["id"]
    r = api.post(f"/api/v1/activities/{math}/entries",
                 json={"activity_date": "2026-10-05", "duration_seconds": 600, "workload": "excluded"})
    assert r.status_code == 403
    api.timer(math, "start", 0)
    set_now(FIXED_NOW + timedelta(minutes=5))
    assert api.timer(math, "save", 1, workload="increased").status_code == 403
    assert api.timer(math, "save", 1).status_code == 201
    perms = api.get("/api/v1/me").json()["permissions"]
    assert perms["can_set_workload"] is False and perms["can_delete_reviewed_entries"] is False


def test_guardian_idempotency_key_is_scoped_per_child(api, make_api, engine):
    kid2 = make_api()
    kid2.get("/api/v1/me")
    g = make_guardian(make_api, engine, api)
    with Session(engine) as db:
        db.add(GuardianChild(guardian_id=g.user_id, child_id=kid2.user_id))
        db.commit()
    grant(engine, api.user_id, 60)
    grant(engine, kid2.user_id, 60)
    key = uuid.uuid4().hex
    assert buy(g, "settlers", "meadow", key).status_code == 201
    g.client.headers["X-Child-Id"] = str(kid2.user_id)
    r = buy(g, "settlers", "meadow", key)
    assert r.status_code == 201 and r.headers.get("Idempotent-Replay") is None
    assert kid2.get("/api/v1/wallet").json()["balance"] == 0
    assert api.get("/api/v1/wallet").json()["balance"] == 0
    # a retry for kid2 with the same key is a replay of kid2's purchase, not kid1's
    again = buy(g, "settlers", "meadow", key)
    assert again.headers.get("Idempotent-Replay") == "true" and again.json() == r.json()
