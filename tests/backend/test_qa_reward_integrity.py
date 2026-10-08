"""QA: can a CHILD manipulate inputs of the reward policy? (spec §2, §4.1, §5.2, §14 "Поручения и награды").

Timeline (API.md §8): child provisioned 2026-10-06 → A = 2026-10-06, first D = 2026-10-20,
window [10-13, 10-19], baseline [10-06, 10-12].
Tests marked FINDING-* assert the spec-required behaviour; a failure is a reproducible defect.
"""

from __future__ import annotations

from datetime import date

from conftest import at, make_guardian

D = date(2026, 10, 20)


def _entry(api, act, day: date, minutes: int):
    at(day)
    r = api.post(f"/api/v1/activities/{act}/entries",
                 json={"activity_date": day.isoformat(), "duration_seconds": minutes * 60})
    assert r.status_code == 201, r.text
    return r.json()


def _confirm(guardian, e):
    r = guardian.put(f"/api/v1/entries/{e['id']}/quality", json={"revision": e["revision"], "quality_status": "confirmed"})
    assert r.status_code == 200, r.text
    return r.json()


def _lessons_after_evaluate(api):
    at(D)
    r = api.post("/api/v1/rewards/evaluate")
    assert r.status_code == 200, r.text
    ev = api.get("/api/v1/rewards").json()["evaluations"][0]
    return next(c for c in ev["categories"] if c["category"] == "lessons")


def _flat_month(child, guardian):
    """Math: 35 min on 3 baseline days and 3 window days, all guardian-confirmed → p = 0 → 0 stars."""
    math = child.activity("math")["id"]
    entries = {}
    for d in (6, 7, 8, 13, 14, 15):
        entries[d] = _confirm(guardian, _entry(child, math, date(2026, 10, d), 35))
    return math, entries


def test_control_flat_lessons_give_zero(child, make_api, engine):
    g = make_guardian(make_api, engine, child)
    _flat_month(child, g)
    lessons = _lessons_after_evaluate(child)
    assert lessons["amount"] == 0 and lessons["state"] == "final"


def test_finding_child_edit_of_confirmed_entry_must_not_stay_confirmed(child, make_api, engine):
    """Child shortens guardian-confirmed lesson entries → must lose confirmation (or be forbidden)."""
    g = make_guardian(make_api, engine, child)
    _, entries = _flat_month(child, g)
    at(date(2026, 10, 16))
    kept = []
    for d in (13, 14, 15):
        e = entries[d]
        r = child.patch(f"/api/v1/entries/{e['id']}", json={"revision": e["revision"], "duration_seconds": 25 * 60})
        if r.status_code == 200:
            kept.append(r.json()["quality_status"])
    lessons = _lessons_after_evaluate(child)
    assert lessons["amount"] == 0 and "confirmed" not in kept, (
        f"child-edited entries kept quality={kept} and paid {lessons['amount']} stars "
        "(entries/service.py update_entry does not reset quality_status)")


def test_finding_child_cannot_mark_workload_to_drop_slow_days(child, make_api, engine):
    """Spec §5.2: workload (normal/increased/excluded) is set by the parent. A child excluding slow
    confirmed days cherry-picks the fastest results."""
    g = make_guardian(make_api, engine, child)
    math = child.activity("math")["id"]
    for d in (6, 7, 8):
        _confirm(g, _entry(child, math, date(2026, 10, d), 35))
    slow = []
    for d, m in ((13, 40), (14, 40), (15, 40), (16, 30), (17, 30), (18, 30)):  # median 35 → p = 0
        e = _confirm(g, _entry(child, math, date(2026, 10, d), m))
        if m == 40:
            slow.append(e)
    at(date(2026, 10, 19))
    statuses = []
    for e in slow:
        r = child.patch(f"/api/v1/entries/{e['id']}", json={"revision": e["revision"], "workload": "excluded"})
        statuses.append(r.status_code)
    lessons = _lessons_after_evaluate(child)
    assert lessons["amount"] == 0, f"child workload edits {statuses} produced {lessons['amount']} stars"


def test_finding_child_deleting_slow_confirmed_days_does_not_pay(child, make_api, engine):
    """Spec §5.2.3 'нельзя выбрать лишь самые быстрые результаты'."""
    g = make_guardian(make_api, engine, child)
    math = child.activity("math")["id"]
    for d in (6, 7, 8):
        _confirm(g, _entry(child, math, date(2026, 10, d), 35))
    slow = []
    for d, m in ((13, 40), (14, 40), (15, 40), (16, 30), (17, 30), (18, 30)):
        e = _confirm(g, _entry(child, math, date(2026, 10, d), m))
        if m == 40:
            slow.append(e)
    at(date(2026, 10, 19))
    codes = [child.delete(f"/api/v1/entries/{e['id']}", params={"revision": e["revision"]}).status_code for e in slow]
    lessons = _lessons_after_evaluate(child)
    assert lessons["amount"] == 0, f"child deletes {codes} produced {lessons['amount']} stars"


def test_finding_timezone_switch_cannot_backfill_missed_chore(child):
    """§4.1 'отчётная дата — локальная date с зафиксированным часовым поясом'; API.md: child may
    complete chores only for *today*. Switching the profile zone moves 'today' back a day."""
    at(date(2026, 10, 7), hour_utc=6)  # Wed 09:00 Moscow; Tuesday's daily chore was missed
    room = child.activity("room")["id"]
    assert child.put(f"/api/v1/chores/{room}/completions/2026-10-06", json={"completed": True}).status_code == 422
    me = child.get("/api/v1/me").json()
    r = child.patch("/api/v1/me", json={"timezone": "Pacific/Pago_Pago"})  # UTC-11 → still Tue 19:00
    tz_changed = r.status_code == 200
    r2 = child.put(f"/api/v1/chores/{room}/completions/2026-10-06", json={"completed": True})
    child.patch("/api/v1/me", json={"timezone": me["timezone"]})
    assert not (tz_changed and r2.status_code == 200), \
        "child backfilled a missed chore by changing profile timezone (PATCH /me + PUT completion)"


def test_voluntary_toggle_and_no_instant_stars(child):
    help_ = child.activity("help")["id"]
    for v in (True, False, True, True, False, True):
        assert child.put(f"/api/v1/chores/{help_}/completions/2026-10-06", json={"completed": v}).status_code == 200
    chores = child.get("/api/v1/chores").json()
    assert chores["summary"]["voluntary_completed"] == 1
    assert all(not (i["voluntary"] and i["scheduled"]) for i in chores["items"])
    assert child.get("/api/v1/wallet").json()["balance"] == 0
    dash = child.get("/api/v1/dashboard").json()["chores"]["summary"]
    assert dash["scheduled_total"] == sum(1 for i in chores["items"] if i["scheduled"])  # voluntary not in N


def test_child_cannot_trigger_payment_by_repeated_evaluate_or_preview(child):
    for _ in range(3):
        child.get("/api/v1/rewards")
        assert child.post("/api/v1/rewards/evaluate").status_code == 200
    assert child.get("/api/v1/wallet").json()["items"] == []


def test_child_cannot_confirm_quality_or_exclude_walk_days(child):
    math = child.activity("math")["id"]
    e = _entry(child, math, date(2026, 10, 6), 30)
    r = child.put(f"/api/v1/entries/{e['id']}/quality", json={"revision": 1, "quality_status": "confirmed"})
    assert r.status_code == 403
    assert child.put("/api/v1/day-statuses/walk/2026-10-05", json={"status": "excluded"}).status_code == 403
