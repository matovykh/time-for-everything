"""Reward evaluation: gathers a data snapshot, applies policy v1, persists final results and pays
through the wallet exactly once per (child, period_end, category)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import clock, iso
from app.core.deps import Ctx
from app.db.models import Activity, ChoreCompletion, DayStatus, Profile, RewardEvaluation, TimeEntry
from app.modules.activities import schedules as sched
from app.modules.rewards import policy
from app.modules.rewards.policy import CategoryResult, LessonEntry, SubjectInput
from app.modules.wallet import service as wallet

FIRST_AFTER = timedelta(days=policy.PARAMETERS["first_evaluation_after_days"])
PERIOD = timedelta(days=policy.PARAMETERS["period_days"])
GRACE = timedelta(days=policy.PARAMETERS["deferral_grace_days"])
REASON_BY_CATEGORY = {"lessons": "reward_lessons", "walk": "reward_walk", "chores": "reward_chores"}
LABEL = {"lessons": "Уроки", "walk": "Прогулки", "chores": "Поручения"}


def first_evaluation_on(profile: Profile) -> date:
    return profile.rewards_started_on + FIRST_AFTER


def evaluation_dates(profile: Profile, until: date) -> list[date]:
    d, out = first_evaluation_on(profile), []
    while d <= until:
        out.append(d)
        d += PERIOD
    return out


def compute(db: Session, child: Profile, d: date, finalize: bool) -> dict[str, CategoryResult]:
    window, baseline = policy.windows_for(d)
    start, end = baseline.start, window.end
    acts = db.execute(select(Activity).where(Activity.child_id == child.id)).scalars().all()

    # lessons
    lesson_acts = [a for a in acts if a.category == "lesson" and a.reward_eligible]
    entries_by_act: dict[uuid.UUID, list[LessonEntry]] = defaultdict(list)
    if lesson_acts:
        for e in db.execute(
            select(TimeEntry).where(TimeEntry.child_id == child.id, TimeEntry.deleted_at.is_(None),
                                    TimeEntry.activity_id.in_([a.id for a in lesson_acts]),
                                    TimeEntry.activity_date >= start, TimeEntry.activity_date <= end)
        ).scalars():
            entries_by_act[e.activity_id].append(
                LessonEntry(e.activity_date, e.duration_seconds, e.quality_status, e.workload))
    subjects = [SubjectInput(a.id, a.name, a.target_seconds, entries_by_act.get(a.id, [])) for a in lesson_acts]
    lessons = policy.evaluate_lessons(subjects, window, baseline, finalize)

    # walk
    walk_act = next((a for a in acts if a.category == "walk" and a.reward_eligible), None)
    if walk_act is None:
        walk = CategoryResult("walk", "insufficient_data", 0, "walk_insufficient_days", {"missing_dates": []})
    else:
        seconds = {
            day: int(total) for day, total in db.execute(
                select(TimeEntry.activity_date, func.sum(TimeEntry.duration_seconds))
                .where(TimeEntry.child_id == child.id, TimeEntry.activity_id == walk_act.id,
                       TimeEntry.deleted_at.is_(None), TimeEntry.activity_date >= start,
                       TimeEntry.activity_date <= end)
                .group_by(TimeEntry.activity_date)
            ).all()
        }
        statuses = {
            s.local_date: s.status for s in db.execute(
                select(DayStatus).where(DayStatus.child_id == child.id, DayStatus.category == "walk",
                                        DayStatus.local_date >= start, DayStatus.local_date <= end)
            ).scalars()
        }
        target = walk_act.target_seconds or policy.PARAMETERS["walk"]["default_target_seconds"]
        walk = policy.evaluate_walk(seconds, statuses, target, window, baseline, finalize)

    # chores (reward-eligible scheduled chores, archived included for past dates)
    chore_ids = [a.id for a in acts if a.kind == "boolean" and a.reward_eligible]
    versions = sched.load_versions(db, child.id, chore_ids)
    instances = {(aid, day) for aid in chore_ids for day in window.days()
                 if sched.is_scheduled(versions.get(aid, []), day)}
    completions = {
        (c.activity_id, c.local_date) for c in db.execute(
            select(ChoreCompletion).where(ChoreCompletion.child_id == child.id,
                                          ChoreCompletion.local_date >= window.start,
                                          ChoreCompletion.local_date <= window.end)
        ).scalars()
    }
    chores = policy.evaluate_chores(instances, completions, window)
    return {"lessons": lessons, "walk": walk, "chores": chores}


def preview(ctx: Ctx) -> dict[str, Any]:
    today = ctx.today
    window, baseline = policy.windows_for(today)
    results = compute(ctx.db, ctx.child, today, finalize=False)
    cats = [results[c].as_dict() for c in policy.CATEGORIES]
    return {"as_of": today.isoformat(), "window": window.as_dict(), "baseline": baseline.as_dict(),
            "categories": cats, "total": sum(c["amount"] for c in cats)}


def _eval_dict(rows: list[RewardEvaluation]) -> dict[str, Any]:
    r0 = rows[0]
    order = {c: i for i, c in enumerate(policy.CATEGORIES)}
    cats = []
    for r in sorted(rows, key=lambda r: order[r.category]):
        cats.append({"category": r.category, "status": r.status, "amount": r.amount, "reason_code": r.reason_code,
                     "explanation": r.explanation, "facts": (r.snapshot or {}).get("facts", {}), "state": r.state,
                     "evaluated_at": iso(r.evaluated_at)})
    return {
        "period_end": r0.period_end.isoformat(),
        "window": {"start": r0.window_start.isoformat(), "end": r0.window_end.isoformat()},
        "baseline": {"start": r0.baseline_start.isoformat(), "end": r0.baseline_end.isoformat()},
        "categories": cats,
        "total_awarded": sum(r.amount for r in rows if r.state == "final"),
    }


def next_evaluation_on(db: Session, child: Profile, today: date) -> date:
    finals = {
        (r.period_end, r.category) for r in db.execute(
            select(RewardEvaluation).where(RewardEvaluation.child_id == child.id, RewardEvaluation.state == "final")
        ).scalars()
    }
    for d in evaluation_dates(child, today):
        if any((d - timedelta(days=1), c) not in finals for c in policy.CATEGORIES):
            return d
    d = first_evaluation_on(child)
    while d <= today:
        d += PERIOD
    return d


def overview(ctx: Ctx) -> dict[str, Any]:
    child = ctx.child
    rows = ctx.db.execute(
        select(RewardEvaluation).where(RewardEvaluation.child_id == child.id)
        .order_by(RewardEvaluation.period_end.desc())
    ).scalars().all()
    by_period: dict[date, list[RewardEvaluation]] = defaultdict(list)
    for r in rows:
        by_period[r.period_end].append(r)
    periods = sorted(by_period, reverse=True)[:10]
    return {
        "policy_version": policy.POLICY_VERSION,
        "mode": "deterministic",
        "rewards_started_on": child.rewards_started_on.isoformat(),
        "first_evaluation_on": first_evaluation_on(child).isoformat(),
        "next_evaluation_on": next_evaluation_on(ctx.db, child, ctx.today).isoformat(),
        "preview": preview(ctx),
        "evaluations": [_eval_dict(by_period[p]) for p in periods],
    }


def evaluate_due(db: Session, child: Profile, today: date, actor_id: uuid.UUID | None) -> list[dict[str, Any]]:
    """Process every due period. Safe to repeat: final rows are never recomputed and the wallet
    idempotency key `reward:{child}:{period_end}:{category}` is unique."""
    processed: list[dict[str, Any]] = []
    try:
        wallet.lock_account(db, child.id)  # serialises concurrent evaluations of the same child
        existing = {
            (r.period_end, r.category): r for r in db.execute(
                select(RewardEvaluation).where(RewardEvaluation.child_id == child.id)
            ).scalars()
        }
        now = clock.now()
        for d in evaluation_dates(child, today):
            period_end = d - timedelta(days=1)
            todo = [c for c in policy.CATEGORIES
                    if existing.get((period_end, c)) is None or existing[(period_end, c)].state == "deferred"]
            if not todo:
                continue
            finalize = today >= d + GRACE
            results = compute(db, child, d, finalize)
            window, baseline = policy.windows_for(d)
            for cat in todo:
                res = results[cat]
                state = "deferred" if res.status == "awaiting_data" and not finalize else "final"
                amount = res.amount if state == "final" and res.status == "eligible" else 0
                row = existing.get((period_end, cat))
                is_new = row is None
                if row is None:
                    row = RewardEvaluation(id=uuid.uuid4(), child_id=child.id, policy_version=policy.POLICY_VERSION,
                                           category=cat, period_end=period_end, window_start=window.start,
                                           window_end=window.end, baseline_start=baseline.start,
                                           baseline_end=baseline.end, mode="deterministic")
                tx = None
                if state == "final" and amount > 0:
                    # Ledger first, then the evaluation row is written exactly once in its final form
                    # (final rows are immutable at the DB level).
                    tx = wallet.post(db, child_id=child.id, amount=amount, reason_code=REASON_BY_CATEGORY[cat],
                                     description=f"{LABEL[cat]} · {window.start:%d.%m}–{window.end:%d.%m}",
                                     idempotency_key=f"reward:{child.id}:{period_end.isoformat()}:{cat}",
                                     source_type="reward_evaluation", source_id=row.id, period_end=period_end,
                                     actor_id=actor_id)
                row.state, row.status, row.amount = state, res.status, amount
                row.reason_code, row.explanation = res.reason_code, res.explanation
                row.snapshot = {"facts": res.facts, "policy": policy.PARAMETERS, "finalize": finalize}
                row.evaluated_at = now
                row.finalized_at = now if state == "final" else None
                row.wallet_transaction_id = tx.id if tx else None
                if is_new:
                    db.add(row)
                db.flush()
                processed.append({"period_end": period_end.isoformat(), "category": cat, "state": state,
                                  "amount": amount})
        db.commit()
    except IntegrityError:
        # A concurrent evaluation finished first; its result stands, nothing is paid twice.
        db.rollback()
        return []
    return processed
