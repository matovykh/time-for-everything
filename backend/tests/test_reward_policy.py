"""Pure policy v1 unit tests (spec §5 examples and edge cases)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.modules.rewards import policy
from app.modules.rewards.policy import LessonEntry, SubjectInput

D = date(2026, 10, 20)
WINDOW, BASELINE = policy.windows_for(D)


def test_windows():
    assert (WINDOW.start, WINDOW.end) == (date(2026, 10, 13), date(2026, 10, 19))
    assert (BASELINE.start, BASELINE.end) == (date(2026, 10, 6), date(2026, 10, 12))


def subject(base_minutes, cur_minutes, quality="confirmed", workload="normal", floor=None):
    entries = [LessonEntry(BASELINE.start + timedelta(days=i), m * 60, quality, workload)
               for i, m in enumerate(base_minutes)]
    entries += [LessonEntry(WINDOW.start + timedelta(days=i), m * 60, quality, workload)
                for i, m in enumerate(cur_minutes)]
    return SubjectInput(uuid.uuid4(), "Математика", floor, entries)


def lessons(*subjects, finalize=False):
    return policy.evaluate_lessons(list(subjects), WINDOW, BASELINE, finalize)


def test_lessons_spec_examples():
    r = lessons(subject([35, 35, 35], [30, 30, 30]))  # p ≈ 14.3 %
    assert r.amount == 20 and r.status == "eligible"
    assert r.facts["subjects"][0]["progress_percent"] == 14.3
    assert lessons(subject([35] * 3, [35] * 3)).amount == 0
    nodata = lessons(subject([35] * 3, []))
    assert nodata.status == "insufficient_data" and nodata.amount == 0  # not a 100 % improvement


def test_lessons_tiers_exact_thresholds_and_cap():
    assert lessons(subject([100] * 3, [95] * 3)).amount == 10  # exactly 5 %
    assert lessons(subject([100] * 3, [90] * 3)).amount == 20
    assert lessons(subject([100] * 3, [85] * 3)).amount == 30
    assert lessons(subject([100] * 3, [96] * 3)).amount == 0
    five = [subject([35] * 3, [25] * 3) for _ in range(5)]
    assert lessons(*five).amount == 100  # 5 × 30 capped at 100


def test_lessons_need_confirmation_and_comparable_workload():
    waiting = lessons(subject([35] * 3, [30] * 3, quality="pending"))
    assert waiting.status == "awaiting_data"
    final = lessons(subject([35] * 3, [30] * 3, quality="pending"), finalize=True)
    assert final.status == "insufficient_data" and final.amount == 0  # unconfirmed never counts
    assert lessons(subject([35] * 3, [30] * 3, workload="increased")).amount == 0
    excluded = subject([35] * 3, [30] * 3)
    excluded.entries.append(LessonEntry(WINDOW.start, 5 * 60, "pending", "excluded"))
    assert lessons(excluded).amount == 20  # excluded work is ignored, even if unconfirmed


def test_lessons_floor_prevents_rewarding_rush():
    r = lessons(subject([35] * 3, [10] * 3, floor=15 * 60))
    assert r.amount == 0 and r.facts["subjects"][0]["status"] == "below_floor"


def walk_eval(minutes_by_offset, statuses=None, baseline_minutes=None, finalize=False):
    seconds = {WINDOW.start + timedelta(days=i): m * 60 for i, m in enumerate(minutes_by_offset) if m is not None}
    if baseline_minutes:
        seconds.update({BASELINE.start + timedelta(days=i): m * 60 for i, m in enumerate(baseline_minutes)})
    st = {WINDOW.start + timedelta(days=i): s for i, s in (statuses or {}).items()}
    return policy.evaluate_walk(seconds, st, 7200, WINDOW, BASELINE, finalize)


def test_walk_goal_regular_and_cap():
    r = walk_eval([120, 130, 240, 120, 125, 60, 30])
    assert r.amount == 40 and r.facts["goal_days"] == 5 and r.facts["required_goal_days"] == 5
    assert walk_eval([240] * 7).amount == 40  # 240 minutes do not double


def test_walk_missing_blocks_then_finalizes_without_reward():
    r = walk_eval([120] * 6 + [None])
    assert r.status == "awaiting_data" and r.facts["missing_dates"] == ["2026-10-19"]
    f = walk_eval([120] * 6 + [None], finalize=True)
    assert f.status == "insufficient_data" and f.amount == 0


def test_walk_no_walk_and_excluded_days():
    r = walk_eval([120, 120, 120, 120, None, None, 120], statuses={4: "no_walk", 5: "excluded"})
    # E = 6 (excluded removed), K = 5 ≥ ceil(6·5/7) = 5
    assert r.facts["included_days"] == 6 and r.facts["required_goal_days"] == 5 and r.amount == 40
    sick = walk_eval([None] * 7, statuses={i: "excluded" for i in range(7)})
    assert sick.status == "insufficient_data" and sick.amount == 0  # illness never penalised or rewarded


def test_walk_improvement_branch():
    r = walk_eval([90, 90, 90, 90, 90, 90, 90], baseline_minutes=[60] * 7)
    # R = 0.75, R_base = 0.5 → +0.25 ≥ 0.10 and R ≥ 0.60
    assert r.amount == 20 and r.reason_code == "walk_improved"
    assert walk_eval([90] * 7).amount == 0  # unknown baseline → no improvement reward


def chores_eval(n, c, days=7):
    aid = [uuid.uuid4() for _ in range(n)]
    inst = {(aid[i], WINDOW.start + timedelta(days=i % days)) for i in range(n)}
    done = set(list(sorted(inst, key=lambda x: (x[1], str(x[0]))))[:c])
    return policy.evaluate_chores(inst, done, WINDOW)


def test_chores_spec_examples():
    assert chores_eval(10, 10).amount == 28
    assert chores_eval(10, 6).amount == 14
    r = chores_eval(10, 5)
    assert r.amount == 0 and r.reason_code == "chores_low_ratio"
    assert policy.evaluate_chores(set(), set(), WINDOW).status == "insufficient_data"  # N = 0 is not 100 %


def test_chores_cap_and_regularity():
    assert chores_eval(60, 60).amount == 40
    a = uuid.uuid4()
    friday = WINDOW.start + timedelta(days=4)
    one = policy.evaluate_chores({(a, friday)}, {(a, friday)}, WINDOW)
    assert one.amount == 25 and one.facts["required_days"] == 1  # 20 + 0 + 5;  # single weekly chore qualifies
    # all completions crammed into one day of a multi-day schedule do not qualify
    acts = [uuid.uuid4() for _ in range(3)]
    inst = {(x, WINDOW.start + timedelta(days=d)) for x in acts for d in range(3)}
    crammed = {(x, WINDOW.start) for x in acts} | {(acts[0], WINDOW.start + timedelta(days=1))}
    assert policy.evaluate_chores(inst, crammed, WINDOW).amount == 0


def test_explanations_never_empty():
    for r in (chores_eval(10, 10), walk_eval([120] * 7), lessons(subject([35] * 3, [30] * 3))):
        assert r.explanation
