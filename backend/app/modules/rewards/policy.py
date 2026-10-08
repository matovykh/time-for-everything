"""Deterministic reward policy v1 (spec §5.1–5.4) as pure functions.

Exact rational arithmetic (fractions.Fraction) is used so thresholds such as 5/10/15 % or
"R ≥ 0.60" never flip because of floating-point rounding.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction
from typing import Any

POLICY_VERSION = 1
PARAMETERS: dict[str, Any] = {
    "version": 1,
    "first_evaluation_after_days": 14,
    "period_days": 7,
    "deferral_grace_days": 7,
    "lessons": {"min_days": 3, "tiers_percent": [[15, 30], [10, 20], [5, 10]], "cap": 100},
    "walk": {"default_target_seconds": 7200, "min_included_days": 5, "goal_share": [5, 7], "goal_reward": 40,
             "improvement_delta": "0.10", "improvement_min_ratio": "0.60", "improvement_min_recorded_days": 4,
             "improvement_reward": 20},
    "chores": {"min_ratio": "0.60", "base": 20, "count_bonus_cap": 15, "count_bonus_per": 3,
               "perfect_bonus": 5, "cap": 40, "min_distinct_days": 3},
}
CATEGORIES = ("lessons", "walk", "chores")

LESSON_TIERS = [(Fraction(15, 100), 30), (Fraction(10, 100), 20), (Fraction(5, 100), 10)]
LESSON_CAP = 100
LESSON_MIN_DAYS = 3
WALK_GOAL_REWARD = 40
WALK_IMPROVEMENT_REWARD = 20
CHORES_CAP = 40


@dataclass(frozen=True)
class Range:
    start: date
    end: date

    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range((self.end - self.start).days + 1)]

    def __contains__(self, d: object) -> bool:
        return isinstance(d, date) and self.start <= d <= self.end

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def windows_for(d: date) -> tuple[Range, Range]:
    """Window [D−7, D−1] and baseline [D−14, D−8]."""
    return Range(d - timedelta(days=7), d - timedelta(days=1)), Range(d - timedelta(days=14), d - timedelta(days=8))


@dataclass
class CategoryResult:
    category: str
    status: str  # eligible | no_reward | insufficient_data | awaiting_data
    amount: int
    reason_code: str
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def explanation(self) -> str:
        return explain(self)

    def as_dict(self) -> dict[str, Any]:
        return {"category": self.category, "status": self.status, "amount": self.amount,
                "reason_code": self.reason_code, "explanation": self.explanation, "facts": self.facts}


def _median(values: list[int]) -> Fraction:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return Fraction(s[mid]) if n % 2 else Fraction(s[mid - 1] + s[mid], 2)


# ---- lessons ----------------------------------------------------------------------------------
@dataclass
class LessonEntry:
    day: date
    seconds: int
    quality: str
    workload: str


@dataclass
class SubjectInput:
    activity_id: uuid.UUID
    name: str
    floor_seconds: int | None
    entries: list[LessonEntry]


def _lesson_days(entries: Iterable[LessonEntry], rng: Range, finalize: bool) -> tuple[list[int], bool]:
    """Returns (comparable daily totals, has_pending)."""
    by_day: dict[date, list[LessonEntry]] = {}
    pending = False
    for e in entries:
        if e.day not in rng or e.workload == "excluded":
            continue
        by_day.setdefault(e.day, []).append(e)
        if e.quality == "pending":
            pending = True
    totals = []
    for day_entries in by_day.values():
        if all(e.quality == "confirmed" and e.workload == "normal" for e in day_entries):
            totals.append(sum(e.seconds for e in day_entries))
    return totals, pending and not finalize


def evaluate_lessons(subjects: list[SubjectInput], window: Range, baseline: Range, finalize: bool) -> CategoryResult:
    rows = []
    total = 0
    any_waiting = False
    for s in subjects:
        cur, cur_pending = _lesson_days(s.entries, window, finalize)
        base, base_pending = _lesson_days(s.entries, baseline, finalize)
        row: dict[str, Any] = {
            "activity_id": str(s.activity_id), "name": s.name, "baseline_days": len(base), "current_days": len(cur),
            "baseline_median_seconds": None, "current_median_seconds": None, "progress_percent": None, "amount": 0,
        }
        if cur_pending or base_pending:
            row["status"] = "awaiting_data"
            any_waiting = True
        elif len(cur) < LESSON_MIN_DAYS or len(base) < LESSON_MIN_DAYS:
            row["status"] = "insufficient_data"
        else:
            b, c = _median(base), _median(cur)
            p = (b - c) / b
            row.update(baseline_median_seconds=round(float(b), 1), current_median_seconds=round(float(c), 1),
                       progress_percent=round(float(p * 100), 1))
            if s.floor_seconds is not None and c < s.floor_seconds:
                row["status"] = "below_floor"
            else:
                amount = next((a for threshold, a in LESSON_TIERS if p >= threshold), 0)
                row["amount"] = amount
                row["status"] = "eligible" if amount else "no_progress"
                total += amount
        rows.append(row)
    amount = min(LESSON_CAP, total)
    facts = {"subjects": rows, "cap": LESSON_CAP}
    if any_waiting:
        return CategoryResult("lessons", "awaiting_data", amount, "lessons_awaiting_confirmation", facts)
    if amount > 0:
        return CategoryResult("lessons", "eligible", amount, "lessons_progress", facts)
    if all(r["status"] == "insufficient_data" for r in rows):
        return CategoryResult("lessons", "insufficient_data", 0, "lessons_insufficient_data", facts)
    return CategoryResult("lessons", "no_reward", 0, "lessons_no_progress", facts)


# ---- walk -------------------------------------------------------------------------------------
@dataclass
class WalkStats:
    included: int
    recorded: int
    goal_days: int
    mean_ratio: Fraction | None
    missing: list[date]


def _walk_stats(seconds: dict[date, int], statuses: dict[date, str], rng: Range, target: int) -> WalkStats:
    ratios: list[Fraction] = []
    recorded = goal = 0
    missing = []
    for d in rng.days():
        s = seconds.get(d, 0)
        if s > 0:
            recorded += 1
            ratios.append(min(Fraction(s, target), Fraction(1)))
            goal += s >= target
        elif statuses.get(d) == "excluded":
            continue
        elif statuses.get(d) == "no_walk":
            ratios.append(Fraction(0))
        else:
            missing.append(d)
    mean = sum(ratios, Fraction(0)) / len(ratios) if ratios else None
    return WalkStats(len(ratios), recorded, goal, mean, missing)


def evaluate_walk(seconds: dict[date, int], statuses: dict[date, str], target: int, window: Range,
                  baseline: Range, finalize: bool) -> CategoryResult:
    cur = _walk_stats(seconds, statuses, window, target)
    base = _walk_stats(seconds, statuses, baseline, target)
    required = math.ceil(Fraction(5 * cur.included, 7)) if cur.included else 0
    base_ok = not base.missing and base.included >= 5 and base.mean_ratio is not None
    facts = {
        "target_seconds": target, "included_days": cur.included, "recorded_days": cur.recorded,
        "goal_days": cur.goal_days, "required_goal_days": required,
        "mean_ratio": round(float(cur.mean_ratio), 3) if cur.mean_ratio is not None else None,
        "baseline_mean_ratio": round(float(base.mean_ratio), 3) if base_ok and base.mean_ratio is not None else None,
        "missing_dates": [d.isoformat() for d in cur.missing],
    }
    if cur.missing:
        if not finalize:
            return CategoryResult("walk", "awaiting_data", 0, "walk_missing_days", facts)
        return CategoryResult("walk", "insufficient_data", 0, "walk_missing_data", facts)
    if cur.included < 5:
        return CategoryResult("walk", "insufficient_data", 0, "walk_insufficient_days", facts)
    if cur.goal_days >= required:
        return CategoryResult("walk", "eligible", WALK_GOAL_REWARD, "walk_goal_regular", facts)
    if (base_ok and cur.mean_ratio is not None and base.mean_ratio is not None
            and cur.mean_ratio - base.mean_ratio >= Fraction(1, 10)
            and cur.mean_ratio >= Fraction(6, 10) and cur.recorded >= 4):
        return CategoryResult("walk", "eligible", WALK_IMPROVEMENT_REWARD, "walk_improved", facts)
    return CategoryResult("walk", "no_reward", 0, "walk_no_progress", facts)


# ---- chores -----------------------------------------------------------------------------------
def evaluate_chores(instances: set[tuple[uuid.UUID, date]], completions: set[tuple[uuid.UUID, date]],
                    window: Range) -> CategoryResult:
    inst = {i for i in instances if i[1] in window}
    done = inst & completions
    n, c = len(inst), len(done)
    scheduled_days = {d for _, d in inst}
    completion_days = {d for _, d in done}
    required_days = min(3, len(scheduled_days))
    facts = {"scheduled": n, "completed": c, "completion_days": len(completion_days), "required_days": required_days}
    if n == 0:
        return CategoryResult("chores", "insufficient_data", 0, "chores_none_scheduled", facts)
    if Fraction(c, n) < Fraction(6, 10):
        return CategoryResult("chores", "no_reward", 0, "chores_low_ratio", facts)
    if len(completion_days) < required_days:
        return CategoryResult("chores", "no_reward", 0, "chores_not_regular", facts)
    amount = (20 * c) // n + min(15, c // 3) + (5 if c == n else 0)
    amount = min(CHORES_CAP, amount)
    return CategoryResult("chores", "eligible", amount, "chores_all_done" if c == n else "chores_regular", facts)


# ---- explanations (fixed templates; no AI in MVP) ----------------------------------------------
def explain(r: CategoryResult) -> str:
    f = r.facts
    match r.reason_code:
        case "lessons_progress":
            return f"Время на уроки стало короче при подтверждённом качестве. Начислено {r.amount} ✦."
        case "lessons_awaiting_confirmation":
            return "Ждём, когда взрослый подтвердит качество домашних заданий."
        case "lessons_insufficient_data":
            return "Пока знакомимся с твоим ритмом: нужно не меньше 3 подтверждённых учебных дней в каждой неделе."
        case "lessons_no_progress":
            return "Время на уроки пока не сократилось — это нормально. Главное — качество."
        case "walk_goal_regular":
            return f"Цель прогулки достигнута в {f['goal_days']} из {f['included_days']} дней. Начислено {r.amount} ✦."
        case "walk_improved":
            return f"Прогулки стали заметно длиннее, чем неделей раньше. Начислено {r.amount} ✦."
        case "walk_missing_days":
            return "Не хватает отметок о прогулках за некоторые дни. Отметь «не гулял» или добавь время."
        case "walk_missing_data":
            return "За период не хватило отметок о прогулках, поэтому оценка не проводилась."
        case "walk_insufficient_days":
            return "Для оценки нужно хотя бы 5 учтённых дней прогулок."
        case "walk_no_progress":
            return "В этот раз прогулки не дошли до цели. В следующую неделю всё получится!"
        case "chores_all_done":
            return f"Выполнено {f['completed']} из {f['scheduled']} запланированных дел. Начислено {r.amount} ✦."
        case "chores_regular":
            return f"Выполнено {f['completed']} из {f['scheduled']} запланированных дел. Начислено {r.amount} ✦."
        case "chores_low_ratio":
            return f"Выполнено {f['completed']} из {f['scheduled']} дел. Для награды нужно не меньше 60%."
        case "chores_not_regular":
            return "Дела стоит делать в разные дни, а не все сразу."
        case "chores_none_scheduled":
            return "В этот период не было запланированных дел."
    return ""
