"""QA TMR/ENT/PUR/CHR contract + concurrency tests against API.md (real cookie auth).
Concurrency is meaningful on PostgreSQL (QA_TEST_DATABASE_URL); on SQLite writers serialise."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, date, datetime, timedelta

from conftest import FIXED_NOW, at, grant, make_guardian, set_now


def _parallel(n, fn):
    out, barrier = [None] * n, threading.Barrier(n)

    def run(i):
        barrier.wait()
        out[i] = fn(i)
    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


# ---- timers ---------------------------------------------------------------------------------
def test_tmr01_spec_scenario_math_russian_math(child):
    m, r = child.activity("math"), child.activity("russian")
    t = child.timer(m["id"], "start", 0).json()["timer"]
    set_now(FIXED_NOW + timedelta(minutes=10))
    t = child.timer(m["id"], "pause", t["revision"]).json()["timer"]
    tr = child.timer(r["id"], "start", 0).json()
    assert tr["other_running"] == []  # math is paused
    set_now(FIXED_NOW + timedelta(minutes=25))
    tr = child.timer(r["id"], "pause", tr["timer"]["revision"]).json()["timer"]
    t = child.timer(m["id"], "start", t["revision"]).json()["timer"]
    set_now(FIXED_NOW + timedelta(minutes=30))
    sm = child.timer(m["id"], "save", t["revision"]).json()
    sr = child.timer(r["id"], "save", tr["revision"]).json()
    assert sm["entry"]["duration_seconds"] == 900 and sr["entry"]["duration_seconds"] == 900
    assert sm["timer"]["state"] == sr["timer"]["state"] == "idle"


def test_tmr02_concurrent_saves_create_one_entry(child):
    m = child.activity("math")
    t = child.timer(m["id"], "start", 0).json()["timer"]
    set_now(FIXED_NOW + timedelta(minutes=5))
    codes = _parallel(6, lambda i: child.timer(m["id"], "save", t["revision"]).status_code)
    assert codes.count(201) == 1 and set(codes) <= {201, 409}, codes
    items = child.get(f"/api/v1/activities/{m['id']}/entries").json()["items"]
    assert len(items) == 1 and items[0]["source"] == "timer"


def test_tmr02_same_key_concurrent_replay_one_entry(child):
    m = child.activity("math")
    t = child.timer(m["id"], "start", 0).json()["timer"]
    set_now(FIXED_NOW + timedelta(minutes=5))
    key = uuid.uuid4().hex
    res = _parallel(5, lambda i: child.timer(m["id"], "save", t["revision"], key=key))
    assert sorted({r.status_code for r in res}) in ([201], [201, 409]), [r.status_code for r in res]
    ok = [r.json()["entry"]["id"] for r in res if r.status_code == 201]
    assert len(set(ok)) == 1
    assert len(child.get(f"/api/v1/activities/{m['id']}/entries").json()["items"]) == 1


def test_tmr03_key_reuse_with_other_body_rejected(child):
    m = child.activity("math")
    key = uuid.uuid4().hex
    assert child.timer(m["id"], "start", 0, key=key).status_code == 200
    r = child.timer(m["id"], "start", 5, key=key)
    assert r.status_code == 422 and r.json()["code"] == "idempotency_key_reuse"


def test_tmr05_client_cannot_post_elapsed(child):
    m = child.activity("math")
    r = child.timer(m["id"], "start", 0, accumulated_ms=10_000_000)
    assert r.status_code == 422


def test_tmr07_long_and_forgotten_sessions(child):
    m = child.activity("math")
    t = child.timer(m["id"], "start", 0).json()["timer"]
    set_now(FIXED_NOW + timedelta(hours=4, seconds=1))
    r = child.timer(m["id"], "save", t["revision"])
    assert r.status_code == 422 and r.json()["code"] == "long_session_confirmation_required"
    assert child.get(f"/api/v1/activities/{m['id']}/timer").json()["state"] == "running"  # nothing truncated
    set_now(FIXED_NOW + timedelta(hours=25))
    r = child.timer(m["id"], "save", t["revision"], confirm_long_session=True)
    assert r.status_code == 422 and r.json()["code"] == "session_too_long"
    r = child.timer(m["id"], "save", t["revision"], duration_seconds=3600, activity_date="2026-10-06")
    assert r.status_code == 201 and r.json()["entry"]["duration_seconds"] == 3600


def test_tmr12_midnight_default_is_session_start_per_api(child):
    m = child.activity("math")
    set_now(datetime(2026, 10, 6, 20, 50, tzinfo=UTC))  # 23:50 Moscow
    t = child.timer(m["id"], "start", 0).json()["timer"]
    assert t["started_on"] == "2026-10-06"
    set_now(datetime(2026, 10, 6, 21, 20, tzinfo=UTC))  # 00:20 next day
    e = child.timer(m["id"], "save", t["revision"]).json()["entry"]
    assert e["activity_date"] == "2026-10-06" and e["duration_seconds"] == 1800


def test_tmr08_manual_entry_does_not_touch_draft(child):
    m = child.activity("math")
    t = child.timer(m["id"], "start", 0).json()["timer"]
    child.post(f"/api/v1/activities/{m['id']}/entries", json={"activity_date": "2026-10-05", "duration_seconds": 600})
    t2 = child.get(f"/api/v1/activities/{m['id']}/timer").json()
    assert t2["revision"] == t["revision"] and t2["state"] == "running"


def test_tmr11_manual_endpoint_cannot_forge_timer_source(child):
    m = child.activity("math")
    r = child.post(f"/api/v1/activities/{m['id']}/entries",
                   json={"activity_date": "2026-10-05", "duration_seconds": 600, "source": "timer"})
    assert r.status_code == 422


# ---- entries / history --------------------------------------------------------------------
def test_ent01_future_date_in_child_timezone(child):
    m = child.activity("math")["id"]
    set_now(datetime(2026, 10, 6, 22, 30, tzinfo=UTC))  # Moscow: already 10-07
    ok = child.post(f"/api/v1/activities/{m}/entries", json={"activity_date": "2026-10-07", "duration_seconds": 600})
    assert ok.status_code == 201
    bad = child.post(f"/api/v1/activities/{m}/entries", json={"activity_date": "2026-10-08", "duration_seconds": 600})
    assert bad.status_code == 422 and bad.json()["code"] == "future_date"


def test_ent02_manual_bounds(child):
    m = child.activity("math")["id"]
    for v in (0, 59, 86401, -60, 60.5, None, True):
        r = child.post(f"/api/v1/activities/{m}/entries", json={"activity_date": "2026-10-05", "duration_seconds": v})
        assert r.status_code == 422, v


def test_finding_low_numeric_string_coerced(child):
    """API.md: durations are integer seconds. Pydantic lax mode accepts the JSON string "600"."""
    m = child.activity("math")["id"]
    r = child.post(f"/api/v1/activities/{m}/entries", json={"activity_date": "2026-10-05", "duration_seconds": "600"})
    assert r.status_code == 422


def test_ent03_ent04_all_time_history_pagination_and_gaps(child):
    m = child.activity("math")["id"]
    dates = ["2023-03-01", "2023-03-01", "2025-01-15", "2026-10-05"] + [f"2024-0{i}-1{i}" for i in range(1, 10)]
    for d in dates:
        assert child.post(f"/api/v1/activities/{m}/entries",
                          json={"activity_date": d, "duration_seconds": 600}).status_code == 201
    seen, cursor = [], None
    while True:
        page = child.get(f"/api/v1/activities/{m}/entries", params={"limit": 3, **({"cursor": cursor} if cursor else {})}).json()
        seen += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(dates) and len({e["id"] for e in seen}) == len(dates)
    assert [e["activity_date"] for e in seen] == sorted([e["activity_date"] for e in seen], reverse=True)
    pts = child.get(f"/api/v1/activities/{m}/daily-totals").json()["points"]
    assert [p["date"] for p in pts] == sorted(set(dates))  # gaps omitted, chronological
    assert pts[0] == {"date": "2023-03-01", "seconds": 1200, "entries": 2}
    assert all(p["seconds"] > 0 for p in pts)


def test_ent06_week_buckets_monday_sunday(child):
    w = child.get("/api/v1/analytics/time", params={"bucket": "week", "weeks": 4}).json()
    for b in w["buckets"]:
        s, e = date.fromisoformat(b["start"]), date.fromisoformat(b["end"])
        assert s.isoweekday() == 1 and e.isoweekday() == 7
    assert w["buckets"][-1]["complete"] is False and all(b["complete"] for b in w["buckets"][:-1])


# ---- chores --------------------------------------------------------------------------------
def test_chr01_weekday_and_friday_in_child_timezone(child):
    # 2026-10-09 is Friday in Moscow from 21:00 UTC Thursday
    set_now(datetime(2026, 10, 8, 21, 30, tzinfo=UTC))
    items = {i["code"]: i for i in child.get("/api/v1/chores").json()["items"]}
    assert items["plants"]["scheduled"] is True and items["bag"]["scheduled"] is True
    at(date(2026, 10, 10))  # Saturday
    items = {i["code"]: i for i in child.get("/api/v1/chores").json()["items"]}
    assert items["bag"]["scheduled"] is False and items["plants"]["scheduled"] is False
    r = child.put(f"/api/v1/chores/{items['bag']['activity_id']}/completions/2026-10-10", json={"completed": True})
    assert r.status_code == 422 and r.json()["code"] == "not_scheduled"


# ---- purchases -----------------------------------------------------------------------------
def test_pur01_price_from_server_only(child, engine):
    grant(engine, child.user_id, 60)
    for extra in ({"cost": 0}, {"price": 0}, {"amount": 0}):
        r = child.post("/api/v1/worlds/settlers/purchases", json={"upgrade_code": "meadow", **extra},
                       headers={"Idempotency-Key": uuid.uuid4().hex})
        assert r.status_code == 422, extra
    r = child.post("/api/v1/worlds/settlers/purchases", json={"upgrade_code": "workshop"},
                   headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 409 and r.json()["code"] == "prerequisite_missing"


def test_pur03_concurrent_same_item_one_debit(child, engine):
    grant(engine, child.user_id, 100)
    res = _parallel(6, lambda i: child.post("/api/v1/worlds/settlers/purchases", json={"upgrade_code": "meadow"},
                                            headers={"Idempotency-Key": uuid.uuid4().hex}).status_code)
    assert res.count(201) == 1, res
    w = child.get("/api/v1/wallet").json()
    assert w["balance"] == 40 and sum(1 for i in w["items"] if i["reason_code"] == "world_purchase") == 1


def test_pur03_concurrent_different_worlds_never_negative(child, engine):
    for code in ("bricks", "voxel", "helpers"):
        assert child.post("/api/v1/worlds", json={"theme_code": code}).status_code in (200, 201)
    grant(engine, child.user_id, 130)  # enough for two meadows (60 each), not four
    themes = ["settlers", "bricks", "voxel", "helpers"]
    res = _parallel(4, lambda i: child.post(f"/api/v1/worlds/{themes[i]}/purchases", json={"upgrade_code": "meadow"},
                                            headers={"Idempotency-Key": uuid.uuid4().hex}).status_code)
    assert res.count(201) == 2, res
    w = child.get("/api/v1/wallet").json()
    assert w["balance"] == 10 and w["items"][0]["balance_after"] >= 0
    assert sum(i["amount"] for i in w["items"]) == w["balance"]


def test_pur05_progress_per_world_and_free_add(child, engine):
    grant(engine, child.user_id, 60)
    child.post("/api/v1/worlds/settlers/purchases", json={"upgrade_code": "meadow"},
               headers={"Idempotency-Key": uuid.uuid4().hex})
    assert child.post("/api/v1/worlds", json={"theme_code": "bricks"}).status_code == 201
    assert child.post("/api/v1/worlds", json={"theme_code": "bricks"}).status_code == 200
    worlds = {w["code"]: w for w in child.get("/api/v1/worlds").json()["items"]}
    assert worlds["settlers"]["level"] == 1 and worlds["bricks"]["level"] == 0
    assert child.get("/api/v1/wallet").json()["balance"] == 0


def test_guardian_idempotency_key_scoped_per_child(make_api, engine):
    """API.md §1.5 scope is (user, key). A guardian retrying with the same key for a DIFFERENT
    child must not receive the first child's stored response."""
    kid1, kid2 = make_api(), make_api()
    g = make_guardian(make_api, engine, kid1)
    from sqlalchemy.orm import Session

    from app.db.models import GuardianChild
    with Session(engine) as db:
        db.add(GuardianChild(guardian_id=g.user_id, child_id=kid2.user_id))
        db.commit()
    grant(engine, kid1.user_id, 60)
    grant(engine, kid2.user_id, 60)
    key = uuid.uuid4().hex
    r1 = g.post("/api/v1/worlds/settlers/purchases", json={"upgrade_code": "meadow"}, headers={"Idempotency-Key": key})
    assert r1.status_code == 201
    g.client.headers["X-Child-Id"] = str(kid2.user_id)
    r2 = g.post("/api/v1/worlds/settlers/purchases", json={"upgrade_code": "meadow"}, headers={"Idempotency-Key": key})
    assert r2.headers.get("Idempotent-Replay") != "true", "kid2 request answered with kid1's stored purchase"
    assert kid2.get("/api/v1/wallet").json()["balance"] == 0
