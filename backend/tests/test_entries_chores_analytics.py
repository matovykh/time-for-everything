from __future__ import annotations

import uuid
from datetime import timedelta

from tests.conftest import FIXED_NOW, set_now


def add_entry(api, activity_id, day, seconds, **kw):
    return api.post(f"/api/v1/activities/{activity_id}/entries",
                    json={"activity_date": day, "duration_seconds": seconds, **kw})


# ---- provisioning ---------------------------------------------------------------------------
def test_provisioning_defaults(api):
    me = api.get("/api/v1/me").json()
    assert me["role"] == "child" and me["active_world"] == "settlers" and me["onboarding_version"] == 0
    assert me["today"] == "2026-10-06" and me["rewards_started_on"] == "2026-10-06"
    items = api.get("/api/v1/activities").json()["items"]
    assert [a["code"] for a in items] == ["math", "russian", "literature", "nature", "english", "walk", "reading",
                                          "bag", "plants", "room", "help"]
    walk = next(a for a in items if a["code"] == "walk")
    assert walk["target_seconds"] == 7200 and walk["objective"] == "reach"
    bag = next(a for a in items if a["code"] == "bag")
    assert bag["schedule"] == {"weekdays": [1, 2, 3, 4, 5], "starts_on": "2026-10-06", "ends_on": None}
    assert next(a for a in items if a["code"] == "help")["schedule"] is None
    uuid.UUID(walk["id"])
    # second request does not duplicate anything
    assert len(api.get("/api/v1/activities").json()["items"]) == 11


def test_profile_patch_and_role_not_writable(api):
    r = api.patch("/api/v1/me", json={"display_name": "Алексей", "grade": "3", "theme": "dark",
                                      "onboarding_version": 1})
    assert r.status_code == 200 and r.json()["display_name"] == "Алексей" and r.json()["theme"] == "dark"
    assert api.patch("/api/v1/me", json={"role": "admin"}).status_code == 422
    assert api.patch("/api/v1/me", json={"onboarding_version": 0}).status_code == 422
    assert api.patch("/api/v1/me", json={"onboarding_version": "2"}).status_code == 422  # strict int
    me = api.get("/api/v1/me").json()
    assert me["role"] == "child"
    # the timezone defines "today": only an adult changes it (re-sending the same value is fine)
    assert me["permissions"]["can_edit_timezone"] is False
    assert api.patch("/api/v1/me", json={"timezone": "Asia/Tokyo"}).status_code == 403
    assert api.patch("/api/v1/me", json={"timezone": "Europe/Moscow", "grade": "4"}).status_code == 200


def test_guardian_changes_timezone(api, make_api, engine):
    from tests.test_rewards_world_isolation import make_guardian

    g = make_guardian(make_api, engine, api)
    assert g.get("/api/v1/me").json()["permissions"]["can_edit_timezone"] is True
    assert g.patch("/api/v1/me", json={"timezone": "Mars/Base"}).status_code == 422
    assert g.patch("/api/v1/me", json={"timezone": "Asia/Tokyo"}).json()["timezone"] == "Asia/Tokyo"
    assert api.get("/api/v1/me").json()["timezone"] == "Asia/Tokyo"


# ---- entries --------------------------------------------------------------------------------
def test_manual_entry_rules_and_all_time_history(api):
    math = api.activity("math")["id"]
    api.timer(math, "start", 0)
    r = add_entry(api, math, "2026-10-05", 1500, note="домашка")
    assert r.status_code == 201 and r.json()["source"] == "manual" and r.json()["quality_status"] == "pending"
    assert api.get(f"/api/v1/activities/{math}/timer").json()["state"] == "running"  # draft untouched
    assert add_entry(api, math, "2026-10-07", 600).json()["code"] == "future_date"
    assert add_entry(api, math, "2026-10-05", 59).status_code == 422
    assert add_entry(api, math, "2026-10-05", 86401).status_code == 422
    # very old dates are part of the all-time history and chart
    add_entry(api, math, "2025-01-15", 1200)
    add_entry(api, math, "2025-01-15", 600)
    add_entry(api, math, "2026-06-01", 1800)
    pts = api.get(f"/api/v1/activities/{math}/daily-totals").json()["points"]
    assert pts == [{"date": "2025-01-15", "seconds": 1800, "entries": 2},
                   {"date": "2026-06-01", "seconds": 1800, "entries": 1},
                   {"date": "2026-10-05", "seconds": 1500, "entries": 1}]
    hist = api.get(f"/api/v1/activities/{math}/entries", params={"limit": 2}).json()
    assert [e["activity_date"] for e in hist["items"]] == ["2026-10-05", "2026-06-01"]
    rest = api.get(f"/api/v1/activities/{math}/entries", params={"limit": 2, "cursor": hist["next_cursor"]}).json()
    assert [e["activity_date"] for e in rest["items"]] == ["2025-01-15", "2025-01-15"]
    assert rest["next_cursor"] is None


def test_daily_total_cap(api):
    walk = api.activity("walk")["id"]
    assert add_entry(api, walk, "2026-10-05", 86000).status_code == 201
    r = add_entry(api, walk, "2026-10-05", 600)
    assert r.status_code == 422 and r.json()["code"] == "daily_total_exceeded"


def test_entry_edit_delete_with_revision_and_audit(api, engine):
    math = api.activity("math")["id"]
    e = add_entry(api, math, "2026-10-04", 1500).json()
    r = api.patch(f"/api/v1/entries/{e['id']}", json={"revision": 1, "duration_seconds": 1200, "note": "x"})
    assert r.status_code == 200 and r.json()["revision"] == 2 and r.json()["duration_seconds"] == 1200
    stale = api.patch(f"/api/v1/entries/{e['id']}", json={"revision": 1, "note": "y"})
    assert stale.status_code == 409 and stale.json()["details"]["current"]["revision"] == 2
    assert api.delete(f"/api/v1/entries/{e['id']}", params={"revision": 1}).status_code == 409
    assert api.delete(f"/api/v1/entries/{e['id']}", params={"revision": 2}).status_code == 204
    assert api.get(f"/api/v1/activities/{math}/entries").json()["items"] == []
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import AuditEvent

    with Session(engine) as db:
        actions = [a.action for a in db.execute(select(AuditEvent).order_by(AuditEvent.created_at)).scalars()]
        notes = [a.after for a in db.execute(select(AuditEvent)).scalars() if a.after]
    assert "entry.update" in actions and "entry.delete" in actions
    assert all("note" not in (n or {}) for n in notes)  # free text is not copied into audit


def test_quality_confirmation_requires_guardian(api):
    math = api.activity("math")["id"]
    e = add_entry(api, math, "2026-10-04", 1500).json()
    r = api.put(f"/api/v1/entries/{e['id']}/quality", json={"revision": 1, "quality_status": "confirmed"})
    assert r.status_code == 403


def test_manual_entry_idempotency(api):
    math = api.activity("math")["id"]
    key = uuid.uuid4().hex
    body = {"activity_date": "2026-10-04", "duration_seconds": 900}
    a = api.post(f"/api/v1/activities/{math}/entries", json=body, headers={"Idempotency-Key": key})
    b = api.post(f"/api/v1/activities/{math}/entries", json=body, headers={"Idempotency-Key": key})
    assert a.json()["id"] == b.json()["id"]
    assert len(api.get(f"/api/v1/activities/{math}/entries").json()["items"]) == 1


# ---- activities -----------------------------------------------------------------------------
def test_child_custom_activity_and_protected_fields(api):
    r = api.post("/api/v1/activities", json={"name": "  Шахматы ", "kind": "timed", "objective": "reach",
                                             "target_seconds": 1800})
    assert r.status_code == 201
    a = r.json()
    assert a["name"] == "Шахматы" and a["category"] == "custom" and a["reward_eligible"] is False
    assert a["timer"]["state"] == "idle"
    # cannot archive while its timer holds unsaved time
    api.timer(a["id"], "start", 0)
    blocked = api.patch(f"/api/v1/activities/{a['id']}", json={"revision": 1, "archived": True})
    assert blocked.status_code == 409 and blocked.json()["code"] == "invalid_timer_state"
    api.timer(a["id"], "reset", 1)
    # child may edit own non-eligible custom activity
    r = api.patch(f"/api/v1/activities/{a['id']}", json={"revision": 1, "target_seconds": 2400, "archived": True})
    assert r.status_code == 200 and r.json()["archived_at"] is not None
    assert api.timer(a["id"], "start", 0).json()["code"] == "activity_archived"
    # but not default/reward-eligible ones
    walk = api.activity("walk")
    r = api.patch(f"/api/v1/activities/{walk['id']}", json={"revision": walk["revision"], "target_seconds": 60})
    assert r.status_code == 403
    r = api.patch(f"/api/v1/activities/{walk['id']}", json={"revision": walk["revision"], "name": "Гулять"})
    assert r.status_code == 200 and r.json()["name"] == "Гулять"
    r = api.patch(f"/api/v1/activities/{a['id']}", json={"revision": 2, "reward_eligible": True})
    assert r.status_code == 403
    bad = api.post("/api/v1/activities", json={"name": "x", "kind": "timed", "objective": "decrease"})
    assert bad.status_code == 422


def test_chore_schedule_change_applies_from_future_date_only(api):
    r = api.post("/api/v1/activities", json={"name": "Покормить кота", "kind": "boolean",
                                             "schedule": {"weekdays": [1, 3, 5]}})
    assert r.status_code == 201
    cat = r.json()
    assert cat["schedule"]["starts_on"] == "2026-10-06" and cat["reward_eligible"] is False
    bad = api.patch(f"/api/v1/activities/{cat['id']}",
                    json={"revision": 1, "schedule": {"weekdays": [2], "starts_on": "2026-10-01"}})
    assert bad.status_code == 422
    ok = api.patch(f"/api/v1/activities/{cat['id']}",
                   json={"revision": 1, "schedule": {"weekdays": [2], "starts_on": "2026-10-12"}})
    assert ok.status_code == 200
    # Wed Oct 7 still follows the old schedule; Tue Oct 13 the new one
    assert next(i for i in api.get("/api/v1/chores", params={"date": "2026-10-07"}).json()["items"]
                if i["activity_id"] == cat["id"])["scheduled"] is True
    assert next(i for i in api.get("/api/v1/chores", params={"date": "2026-10-13"}).json()["items"]
                if i["activity_id"] == cat["id"])["scheduled"] is True
    assert next(i for i in api.get("/api/v1/chores", params={"date": "2026-10-14"}).json()["items"]
                if i["activity_id"] == cat["id"])["scheduled"] is False


# ---- chores ---------------------------------------------------------------------------------
def test_weekday_and_friday_schedules_with_timezone(api):
    def scheduled(day):
        items = api.get("/api/v1/chores", params={"date": day}).json()["items"]
        return {i["code"] for i in items if i["scheduled"]}

    assert scheduled("2026-10-09") == {"bag", "plants", "room"}  # Friday
    assert scheduled("2026-10-10") == {"room"}  # Saturday: weekdays chore not due
    assert scheduled("2026-10-08") == {"bag", "room"}  # Thursday
    # 22:30 UTC Thursday is already Friday in Moscow
    set_now(FIXED_NOW.replace(day=8, hour=22, minute=30))
    today = api.get("/api/v1/chores").json()
    assert today["date"] == "2026-10-09" and {i["code"] for i in today["items"] if i["scheduled"]} == {
        "bag", "plants", "room"}


def test_checkbox_toggle_never_duplicates(api, engine):
    bag = api.activity("bag")["id"]
    url = f"/api/v1/chores/{bag}/completions/2026-10-06"
    for value in (False, True, False, True, True):
        r = api.put(url, json={"completed": value})
        assert r.status_code == 200 and r.json()["completed"] is value
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app.db.models import ChoreCompletion

    with Session(engine) as db:
        assert db.execute(select(func.count()).select_from(ChoreCompletion)).scalar_one() == 1
    s = api.get("/api/v1/chores").json()["summary"]
    assert s == {"scheduled_total": 2, "scheduled_completed": 1, "voluntary_completed": 0}


def test_chore_date_rules(api):
    bag, help_ = api.activity("bag")["id"], api.activity("help")["id"]
    assert api.put(f"/api/v1/chores/{bag}/completions/2026-10-05", json={"completed": True}).json()["code"] == \
        "date_not_allowed"
    assert api.put(f"/api/v1/chores/{bag}/completions/2026-10-07", json={"completed": True}).status_code == 422
    plants = api.activity("plants")["id"]
    r = api.put(f"/api/v1/chores/{plants}/completions/2026-10-06", json={"completed": True})
    assert r.json()["code"] == "not_scheduled"
    r = api.put(f"/api/v1/chores/{help_}/completions/2026-10-06", json={"completed": True})
    assert r.status_code == 200 and r.json()["voluntary"] is True
    assert api.get("/api/v1/wallet").json()["balance"] == 0  # no instant currency


def test_walk_day_status(api):
    r = api.put("/api/v1/day-statuses/walk/2026-10-05", json={"status": "no_walk"})
    assert r.status_code == 200
    assert api.put("/api/v1/day-statuses/walk/2026-10-04", json={"status": "excluded"}).status_code == 403
    assert api.put("/api/v1/day-statuses/walk/2026-10-07", json={"status": "no_walk"}).status_code == 422
    items = api.get("/api/v1/day-statuses", params={"from": "2026-10-01", "to": "2026-10-06"}).json()["items"]
    assert items == [{"date": "2026-10-05", "status": "no_walk"}]


# ---- analytics ------------------------------------------------------------------------------
def test_weekly_analytics_and_distribution(api):
    math, walk, reading = (api.activity(c)["id"] for c in ("math", "walk", "reading"))
    add_entry(api, math, "2026-10-05", 1800)  # Monday of current week
    add_entry(api, walk, "2026-10-04", 3600)  # Sunday of previous week
    add_entry(api, reading, "2026-09-28", 1200)
    add_entry(api, math, "2026-08-01", 600)  # outside 4 weeks
    r = api.get("/api/v1/analytics/time", params={"weeks": 4}).json()
    assert r["from"] == "2026-09-14" and r["to"] == "2026-10-11"
    assert [b["start"] for b in r["buckets"]] == ["2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05"]
    assert [b["complete"] for b in r["buckets"]] == [True, True, True, False]
    assert r["buckets"][2]["totals"] == {"lessons": 0, "walk": 3600, "other": 1200}
    assert r["buckets"][3]["totals"]["lessons"] == 1800
    assert r["totals"] == {"lessons": 1800, "walk": 3600, "other": 1200} and r["total_seconds"] == 6600
    by_act = api.get("/api/v1/analytics/time", params={"group_by": "activity"}).json()
    assert by_act["totals"][math] == 1800
    day = api.get("/api/v1/analytics/time", params={"bucket": "day", "from": "2026-10-04", "to": "2026-10-05"}).json()
    assert [b["total_seconds"] for b in day["buckets"]] == [3600, 1800]
    assert api.get("/api/v1/analytics/time", params={"bucket": "day"}).status_code == 422


def test_dashboard(api):
    walk = api.activity("walk")["id"]
    add_entry(api, walk, "2026-10-06", 3600)
    api.timer(api.activity("math")["id"], "start", 0)
    set_now(FIXED_NOW + timedelta(minutes=1))
    d = api.get("/api/v1/dashboard").json()
    assert d["walk"] == {"activity_id": walk, "today_seconds": 3600, "target_seconds": 7200}
    assert d["world"]["active_world"] == "settlers" and d["world"]["next_upgrade"]["code"] == "meadow"
    assert len(d["timers"]) == 1 and d["balance"] == 0
    assert d["rewards"]["next_evaluation_on"] == "2026-10-20"
