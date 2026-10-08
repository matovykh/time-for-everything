"""Independent QA reference oracle for reward policy v1 (docs/SPECIFICATION.md §5).

Written by QA from the specification text only, NOT from backend code. It exists so
backend reward services can be compared against an independent reading of the spec.
Exact rational arithmetic (fractions.Fraction) is used on purpose: float boundary
errors at 5% / 10% / 15% / 0.10 / 0.60 / 5/7 are a known risk class.

Where the spec is ambiguous, the interpretation is marked AMBIGUOUS and listed in
docs/MVP-QA.md so engineers/product can confirm it instead of silently diverging.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import ceil, floor
from statistics import median
from typing import Iterable, Optional, Sequence

LESSON_TIERS = ((Fraction(15, 100), 30), (Fraction(10, 100), 20), (Fraction(5, 100), 10))
LESSONS_PERIOD_CAP = 100
LESSONS_MIN_DAYS_PER_WINDOW = 3

WALK_TARGET_MINUTES = 120
WALK_MIN_INCLUDED_DAYS = 5
WALK_REGULAR_AWARD = 40
WALK_IMPROVEMENT_AWARD = 20
WALK_IMPROVEMENT_DELTA = Fraction(10, 100)
WALK_IMPROVEMENT_MIN_R = Fraction(60, 100)
WALK_IMPROVEMENT_MIN_WALK_DAYS = 4

CHORES_THRESHOLD = Fraction(60, 100)
CHORES_CAP = 40

VOLUNTARY_PER_FACT = 2
VOLUNTARY_DAY_CAP = 6
VOLUNTARY_PERIOD_CAP = 20


@dataclass(frozen=True)
class Result:
    """status: 'final' | 'insufficient_data' | 'preliminary' (blocked by missing data)."""

    status: str
    amount: int = 0
    reason: str = ""


def _frac_median(values: Sequence[int]) -> Fraction:
    ordered = sorted(Fraction(v) for v in values)
    return Fraction(median(ordered))


def lesson_progress(base_daily: Sequence[int], current_daily: Sequence[int]) -> Optional[Fraction]:
    """p=(B-C)/B on confirmed comparable daily totals (seconds or minutes, same unit).

    Days without data must simply be absent from the sequences (never zeros).
    Returns None when data is insufficient or B == 0.
    """
    if len(base_daily) < LESSONS_MIN_DAYS_PER_WINDOW or len(current_daily) < LESSONS_MIN_DAYS_PER_WINDOW:
        return None
    b = _frac_median(base_daily)
    c = _frac_median(current_daily)
    if b <= 0:
        return None
    return (b - c) / b


def lesson_subject_award(base_daily: Sequence[int], current_daily: Sequence[int]) -> Result:
    p = lesson_progress(base_daily, current_daily)
    if p is None:
        return Result("insufficient_data", 0, "need>=3 confirmed days in both windows and B>0")
    for threshold, amount in LESSON_TIERS:
        if p >= threshold:
            return Result("final", amount, f"p={p}")
    return Result("final", 0, f"p={p} below 5%")


def lessons_total(subject_amounts: Iterable[int]) -> int:
    return min(LESSONS_PERIOD_CAP, sum(subject_amounts))


@dataclass(frozen=True)
class WalkDay:
    status: str  # recorded | no_walk | excluded | missing
    minutes: int = 0


def walk_ratio(days: Sequence[WalkDay], target: int = WALK_TARGET_MINUTES) -> Optional[Fraction]:
    included = [d for d in days if d.status in ("recorded", "no_walk")]
    if not included:
        return None
    return sum(min(Fraction(d.minutes if d.status == "recorded" else 0, target), 1) for d in included) / len(included)


def walk_award(days: Sequence[WalkDay], base_r: Optional[Fraction] = None, target: int = WALK_TARGET_MINUTES) -> Result:
    if any(d.status == "missing" for d in days):
        return Result("preliminary", 0, "missing walk day blocks final evaluation")
    included = [d for d in days if d.status in ("recorded", "no_walk")]
    e = len(included)
    if e < WALK_MIN_INCLUDED_DAYS:
        return Result("insufficient_data", 0, f"E={e}<5")
    k = sum(1 for d in included if d.status == "recorded" and d.minutes >= target)
    if k >= ceil(Fraction(e * 5, 7)):
        return Result("final", WALK_REGULAR_AWARD, f"K={k},E={e}")
    r = walk_ratio(days, target)
    walk_days = sum(1 for d in included if d.status == "recorded" and d.minutes > 0)
    if (
        base_r is not None
        and r is not None
        and r - base_r >= WALK_IMPROVEMENT_DELTA
        and r >= WALK_IMPROVEMENT_MIN_R
        and walk_days >= WALK_IMPROVEMENT_MIN_WALK_DAYS
    ):
        return Result("final", WALK_IMPROVEMENT_AWARD, f"R={r},base={base_r}")
    return Result("final", 0, f"K={k},E={e},R={r},base={base_r}")


def chores_award(n: int, c: int, completion_days: int, scheduled_days: int) -> Result:
    """n/c count scheduled OCCURRENCES (not chore names).

    AMBIGUOUS: failure of the regularity rule (completions on >= min(3, scheduled_days)
    distinct days) is interpreted as award 0.
    """
    if c < 0 or n < 0 or c > n:
        raise ValueError("invalid counts")
    if n == 0:
        return Result("insufficient_data", 0, "N=0: no evaluation, not 100%")
    if Fraction(c, n) < CHORES_THRESHOLD:
        return Result("final", 0, "C/N<0.6")
    if completion_days < min(3, scheduled_days):
        return Result("final", 0, "regularity: too few distinct days")
    amount = floor(Fraction(20 * c, n)) + min(15, c // 3)
    if c == n:
        amount += 5
    return Result("final", min(CHORES_CAP, amount), "")


def voluntary_award(facts_per_day: Sequence[Sequence[str]]) -> int:
    """facts_per_day: per local day, list of chore ids confirmed that day (duplicates ignored)."""
    total = 0
    for day in facts_per_day:
        day_amount = min(VOLUNTARY_DAY_CAP, VOLUNTARY_PER_FACT * len(set(day)))
        total += day_amount
    return min(VOLUNTARY_PERIOD_CAP, total)


def ai_allowed_range(category: str, base_amount: int, category_cap: int, lesson_progress_positive: bool = True) -> tuple[int, int]:
    """§6: [base, floor(base*1.1)] clipped by category cap; lessons without progress -> [0,0]."""
    if category == "lessons" and not lesson_progress_positive:
        return (0, 0)
    upper = min(category_cap, floor(Fraction(base_amount * 11, 10)))
    return (min(base_amount, category_cap), upper)


def evaluation_windows(local_date: "date") -> tuple[tuple["date", "date"], tuple["date", "date"]]:
    """§5.1: current=[D-7, D-1] (today excluded), base=[D-14, D-8]; inclusive bounds."""
    from datetime import timedelta

    current = (local_date - timedelta(days=7), local_date - timedelta(days=1))
    base = (local_date - timedelta(days=14), local_date - timedelta(days=8))
    return current, base


def final_period_ends(policy_activation: "date", up_to: "date") -> list["date"]:
    """§5.1: first final after 14 observed days, then every 7 days; periods never overlap.

    AMBIGUOUS: interpreted as period_end = activation + 13 + 7k (inclusive end date),
    evaluated on the following local day.
    """
    from datetime import timedelta

    ends = []
    end = policy_activation + timedelta(days=13)
    while end < up_to:
        ends.append(end)
        end += timedelta(days=7)
    return ends


def clamp_ai_amount(proposed: object, low: int, high: int, fallback: int) -> int:
    """Server-side validation of an AI proposal: non-int / out-of-range -> deterministic fallback."""
    if isinstance(proposed, bool) or not isinstance(proposed, int):
        return fallback
    if proposed < low or proposed > high:
        return fallback
    return proposed
