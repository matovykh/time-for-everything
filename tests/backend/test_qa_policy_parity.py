"""QA RWD-01: backend reward policy (app/modules/rewards/policy.py) vs the independent spec oracle
(tests/reference/reward_policy_v1.py) on spec examples + seeded random inputs (exact boundaries included)."""

from __future__ import annotations

import random
import sys
import uuid
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reference"))
import reward_policy_v1 as oracle  # noqa: E402

from app.modules.rewards import policy  # noqa: E402

D = date(2026, 10, 20)
WINDOW, BASE = policy.windows_for(D)


def test_window_semantics_match_api_and_oracle():
    cur, base = oracle.evaluation_windows(D)
    assert (WINDOW.start, WINDOW.end) == cur and (BASE.start, BASE.end) == base
    # API.md §8: D_k = A + 14 + 7k; period_end = D_k - 1 == oracle.final_period_ends
    a = date(2026, 10, 6)
    backend_ends = [d - timedelta(days=1) for d in (a + timedelta(14), a + timedelta(21), a + timedelta(28))]
    assert backend_ends == oracle.final_period_ends(a, a + timedelta(days=28))


# ---- chores ------------------------------------------------------------------------------------
def _chores_case(rng):
    chores = [uuid.uuid4() for _ in range(rng.randint(0, 4))]
    instances = {(c, d) for c in chores for d in WINDOW.days() if rng.random() < rng.choice([0.15, 0.5, 1.0])}
    p = rng.choice([0.0, 0.5, 0.6, 0.8, 1.0])
    completions = {i for i in instances if rng.random() < p}
    return instances, completions


@pytest.mark.parametrize("seed", range(400))
def test_chores_parity(seed):
    rng = random.Random(seed)
    inst, done = _chores_case(rng)
    be = policy.evaluate_chores(inst, done, WINDOW)
    n, c = len(inst), len(inst & done)
    exp = oracle.chores_award(n, c, len({d for _, d in inst & done}), len({d for _, d in inst}))
    assert be.amount == exp.amount, (n, c, be.facts, be.reason_code)
    assert (be.status == "insufficient_data") == (exp.status == "insufficient_data")


def test_chores_spec_examples_through_backend():
    c1 = uuid.uuid4()
    days = WINDOW.days()
    inst = {(c1, d) for d in days} | {(uuid.uuid4(), days[0]), (uuid.uuid4(), days[1]), (uuid.uuid4(), days[2])}
    inst = set(list(sorted(inst, key=lambda x: (x[1], str(x[0]))))[:10])
    assert len(inst) == 10
    ordered = sorted(inst, key=lambda x: (x[1], str(x[0])))
    assert policy.evaluate_chores(inst, set(ordered), WINDOW).amount == 28
    six = set(ordered[::2][:5]) | {ordered[1]}
    assert policy.evaluate_chores(inst, six, WINDOW).amount == oracle.chores_award(
        10, 6, len({d for _, d in six}), len({d for _, d in inst})).amount


# ---- walk --------------------------------------------------------------------------------------
def _walk_days(rng, rng_days, p_missing):
    seconds, statuses, oracle_days = {}, {}, []
    for d in rng_days:
        x = rng.random()
        if x < p_missing:
            oracle_days.append(oracle.WalkDay("missing"))
        elif x < p_missing + 0.1:
            statuses[d] = "excluded"
            oracle_days.append(oracle.WalkDay("excluded"))
        elif x < p_missing + 0.2:
            statuses[d] = "no_walk"
            oracle_days.append(oracle.WalkDay("no_walk"))
        else:
            m = rng.choice([1, 30, 60, 72, 90, 100, 119, 120, 121, 240])
            seconds[d] = m * 60
            oracle_days.append(oracle.WalkDay("recorded", m))
    return seconds, statuses, oracle_days


@pytest.mark.parametrize("seed", range(600))
def test_walk_parity(seed):
    rng = random.Random(10_000 + seed)
    pm = rng.choice([0.0, 0.0, 0.1])
    s1, st1, cur = _walk_days(rng, WINDOW.days(), pm)
    s2, st2, base = _walk_days(rng, BASE.days(), rng.choice([0.0, 0.2]))
    be = policy.evaluate_walk({**s1, **s2}, {**st1, **st2}, 7200, WINDOW, BASE, finalize=False)
    # API.md §8 baseline rule: usable only with E ≥ 5 and no missing day
    base_ok = all(d.status != "missing" for d in base) and sum(d.status in ("recorded", "no_walk") for d in base) >= 5
    exp = oracle.walk_award(cur, base_r=oracle.walk_ratio(base) if base_ok else None)
    assert be.amount == exp.amount, (be.reason_code, be.facts, exp)
    assert (be.status == "awaiting_data") == (exp.status == "preliminary")


# ---- lessons -----------------------------------------------------------------------------------
def _days(rng, rng_days, k, lo, hi):
    picked = rng.sample(rng_days, k)
    return {d: rng.randint(lo, hi) * 60 for d in picked}


@pytest.mark.parametrize("seed", range(600))
def test_lessons_parity(seed):
    rng = random.Random(50_000 + seed)
    subjects, expected = [], []
    for _ in range(rng.randint(1, 5)):
        base = _days(rng, BASE.days(), rng.randint(0, 7), 20, 50)
        cur = _days(rng, WINDOW.days(), rng.randint(0, 7), 15, 50)
        entries = [policy.LessonEntry(d, s, "confirmed", "normal") for d, s in {**base, **cur}.items()]
        subjects.append(policy.SubjectInput(uuid.uuid4(), "s", None, entries))
        expected.append(oracle.lesson_subject_award(list(base.values()), list(cur.values())).amount)
    be = policy.evaluate_lessons(subjects, WINDOW, BASE, finalize=False)
    assert [r["amount"] for r in be.facts["subjects"]] == expected
    assert be.amount == oracle.lessons_total(expected)


@pytest.mark.parametrize("b,c,amount", [(20, 19, 10), (100, 90, 20), (60, 51, 30), (2100, 1785, 30), (2100, 1786, 20),
                                        (35, 30, 20), (35, 35, 0), (30, 40, 0)])
def test_lesson_boundaries_exact(b, c, amount):
    entries = [policy.LessonEntry(d, b, "confirmed", "normal") for d in BASE.days()[:3]] + \
              [policy.LessonEntry(d, c, "confirmed", "normal") for d in WINDOW.days()[:3]]
    r = policy.evaluate_lessons([policy.SubjectInput(uuid.uuid4(), "m", None, entries)], WINDOW, BASE, False)
    assert r.amount == amount == oracle.lesson_subject_award([b] * 3, [c] * 3).amount


def test_lessons_no_current_data_is_not_improvement():
    entries = [policy.LessonEntry(d, 2100, "confirmed", "normal") for d in BASE.days()]
    r = policy.evaluate_lessons([policy.SubjectInput(uuid.uuid4(), "m", None, entries)], WINDOW, BASE, False)
    assert r.amount == 0 and r.status == "insufficient_data"


def test_walk_ratio_uses_exact_fraction():
    assert oracle.walk_ratio([oracle.WalkDay("recorded", 72)] * 5) == Fraction(3, 5)
