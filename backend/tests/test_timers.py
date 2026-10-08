"""Spec §4 / §14 «Учёт»: independent, server-authoritative, revisioned, idempotent timers."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import TimeEntry
from tests.conftest import FIXED_NOW, set_now


def entries(api, activity_id):
    return api.get(f"/api/v1/activities/{activity_id}/entries").json()["items"]


def test_independent_timers_math_russian_math(api):
    """Math 10 min → pause → Russian 15 → pause → Math +5: saves 15 and 15, never mixed."""
    math, rus = api.activity("math")["id"], api.activity("russian")["id"]
    r = api.timer(math, "start", 0)
    assert r.status_code == 200 and r.json()["timer"]["state"] == "running"
    set_now(FIXED_NOW + timedelta(minutes=10))
    assert api.timer(math, "pause", 1).json()["timer"]["elapsed_ms"] == 600_000
    r = api.timer(rus, "start", 0)
    assert r.json()["other_running"] == []
    set_now(FIXED_NOW + timedelta(minutes=25))
    api.timer(rus, "pause", 1)
    api.timer(math, "start", 2)
    set_now(FIXED_NOW + timedelta(minutes=30))
    m = api.timer(math, "save", 3)
    assert m.status_code == 201, m.text
    assert m.json()["entry"]["duration_seconds"] == 900
    assert m.json()["entry"]["source"] == "timer"
    assert m.json()["timer"]["state"] == "idle"
    r = api.timer(rus, "save", 2)
    assert r.json()["entry"]["duration_seconds"] == 900
    assert len(entries(api, math)) == 1 and len(entries(api, rus)) == 1


def test_running_timer_survives_reload_and_overlap_warning(api):
    math, rus = api.activity("math")["id"], api.activity("russian")["id"]
    api.timer(math, "start", 0)
    set_now(FIXED_NOW + timedelta(minutes=3))
    t = api.get(f"/api/v1/activities/{math}/timer").json()
    assert t["state"] == "running" and t["elapsed_ms"] == 180_000 and t["started_on"] == "2026-10-06"
    r = api.timer(rus, "start", 0).json()
    assert [o["activity_id"] for o in r["other_running"]] == [math]  # warning, not a silent pause
    assert api.get(f"/api/v1/activities/{math}/timer").json()["state"] == "running"
    listed = api.get("/api/v1/timers").json()["items"]
    assert {t["activity_id"] for t in listed} == {math, rus}
    # embedded in the catalog as well
    act = api.activity("math")
    assert act["timer"]["state"] == "running"


def test_revision_conflict_two_devices(api, make_api):
    math = api.activity("math")["id"]
    api.timer(math, "start", 0)
    set_now(FIXED_NOW + timedelta(minutes=5))
    first = api.timer(math, "save", 1)
    second = api.timer(math, "save", 1)  # other device, stale revision
    assert first.status_code == 201
    assert second.status_code == 409 and second.json()["code"] == "revision_conflict"
    assert second.json()["details"]["current"]["state"] == "idle"
    assert len(entries(api, math)) == 1


def test_idempotent_replay_returns_same_response(api):
    math = api.activity("math")["id"]
    api.timer(math, "start", 0)
    set_now(FIXED_NOW + timedelta(minutes=5))
    key = uuid.uuid4().hex
    a = api.timer(math, "save", 1, key=key)
    b = api.timer(math, "save", 1, key=key)
    assert a.status_code == b.status_code == 201
    assert a.json() == b.json() and b.headers["Idempotent-Replay"] == "true"
    assert len(entries(api, math)) == 1
    reuse = api.timer(math, "save", 2, key=key)
    assert reuse.status_code == 422 and reuse.json()["code"] == "idempotency_key_reuse"
    # integers are strict: a numeric string is not a revision
    r = api.post(f"/api/v1/activities/{math}/timer/start", json={"revision": "2"},
                 headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 422


def test_idempotency_key_required(api):
    math = api.activity("math")["id"]
    r = api.post(f"/api/v1/activities/{math}/timer/start", json={"revision": 0})
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"


def test_invalid_state_and_reset(api):
    math = api.activity("math")["id"]
    assert api.timer(math, "pause", 0).json()["code"] == "invalid_timer_state"
    api.timer(math, "start", 0)
    set_now(FIXED_NOW + timedelta(minutes=2))
    r = api.timer(math, "reset", 1).json()["timer"]
    assert r["state"] == "idle" and r["elapsed_ms"] == 0 and r["revision"] == 2
    assert entries(api, math) == []


def test_many_pause_resume_cycles_accumulate_exactly(api):
    walk = api.activity("walk")["id"]
    rev = 0
    t = FIXED_NOW
    for _ in range(5):
        api.timer(walk, "start", rev)
        t += timedelta(seconds=61, milliseconds=500)
        set_now(t)
        api.timer(walk, "pause", rev + 1)
        rev += 2
        t += timedelta(minutes=7)  # paused time never counts
        set_now(t)
    saved = api.timer(walk, "save", rev).json()
    assert saved["entry"]["duration_seconds"] == (5 * 61500) // 1000


def test_too_short_long_and_forgotten_timer(api):
    math = api.activity("math")["id"]
    api.timer(math, "start", 0)
    r = api.timer(math, "save", 1)
    assert r.status_code == 422 and r.json()["code"] == "duration_too_short"
    set_now(FIXED_NOW + timedelta(hours=5))
    r = api.timer(math, "save", 1)
    assert r.json()["code"] == "long_session_confirmation_required"
    assert api.get(f"/api/v1/activities/{math}/timer").json()["long_session"] == "confirm"
    set_now(FIXED_NOW + timedelta(hours=25))
    r = api.timer(math, "save", 1, confirm_long_session=True)
    assert r.json()["code"] == "session_too_long"  # never trimmed silently
    r = api.timer(math, "save", 1, duration_seconds=3600)
    assert r.status_code == 201 and r.json()["entry"]["duration_seconds"] == 3600
    assert r.json()["entry"]["activity_date"] == "2026-10-06"


def test_midnight_default_date_is_session_start(api):
    """Moscow is UTC+3: start 23:50 local on Oct 6, save 00:20 on Oct 7."""
    math = api.activity("math")["id"]
    set_now(FIXED_NOW.replace(hour=20, minute=50))
    api.timer(math, "start", 0)
    set_now(FIXED_NOW.replace(hour=21, minute=20))
    saved = api.timer(math, "save", 1).json()
    assert saved["entry"]["activity_date"] == "2026-10-06"
    api.timer(math, "start", 2)
    set_now(FIXED_NOW.replace(hour=21, minute=30))
    r = api.timer(math, "save", 3, activity_date="2026-10-07")
    assert r.json()["entry"]["activity_date"] == "2026-10-07"


def test_save_rejects_date_outside_session(api):
    math = api.activity("math")["id"]
    api.timer(math, "start", 0)
    set_now(FIXED_NOW + timedelta(minutes=1))
    r = api.timer(math, "save", 1, activity_date="2026-10-05")
    assert r.status_code == 422 and r.json()["code"] == "date_not_allowed"


def test_dst_transition_counts_real_elapsed_time(make_api, engine):
    """Europe/Berlin falls back on 2026-10-25 03:00 → 02:00: 90 real minutes stay 90 minutes."""
    from tests.test_rewards_world_isolation import make_guardian

    api = make_api()
    api.get("/api/v1/me")
    guardian = make_guardian(make_api, engine, api)  # timezone is set by an adult
    assert guardian.patch("/api/v1/me", json={"timezone": "Europe/Berlin"}).status_code == 200
    math = api.activity("math")["id"]
    start = FIXED_NOW.replace(month=10, day=25, hour=0, minute=15)  # 02:15 CEST
    set_now(start)
    api.timer(math, "start", 0)
    set_now(start + timedelta(minutes=90))  # 02:45 CET after the switch
    r = api.timer(math, "save", 1).json()
    assert r["entry"]["duration_seconds"] == 5400 and r["entry"]["activity_date"] == "2026-10-25"


def test_db_failure_on_save_keeps_draft(api, engine, monkeypatch):
    math = api.activity("math")["id"]
    api.timer(math, "start", 0)
    set_now(FIXED_NOW + timedelta(minutes=7))
    import app.modules.timers.service as timers

    def boom(*a, **k):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(timers, "check_daily_total", boom)
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    client.cookies = api.client.cookies
    r = client.post(f"/api/v1/activities/{math}/timer/save", json={"revision": 1},
                    headers={**api.client.headers, "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 500 and r.json()["code"] == "internal_error"
    monkeypatch.undo()
    t = api.get(f"/api/v1/activities/{math}/timer").json()
    assert t["state"] == "running" and t["elapsed_ms"] == 420_000 and t["revision"] == 1
    with Session(engine) as db:
        assert db.execute(select(func.count()).select_from(TimeEntry)).scalar_one() == 0


def test_boolean_activity_has_no_timer(api):
    bag = api.activity("bag")["id"]
    r = api.get(f"/api/v1/activities/{bag}/timer")
    assert r.status_code == 422 and r.json()["code"] == "wrong_activity_kind"
