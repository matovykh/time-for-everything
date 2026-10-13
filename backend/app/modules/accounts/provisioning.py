"""Idempotent provisioning of a freshly authenticated Supabase user.

Role is always `child` here; elevation to guardian/admin is an operator action in the database.
Supabase `user_metadata` is user-editable, so it is used for the display name only.

Login diagnostics (value-free; app.core.login_stages). Only when the caller passes `login_request_id` (only POST
/auth/login does) is each DB operation below wrapped in an `ensure_profile.*` sub-stage. Without it the wrappers are
no-ops. Either way the Session calls are exactly the same, in the same order and number:
  * new profile:             get, then 14 explicit flush() calls (1 profile + 11 activities + final + active_world),
                             then commit
  * existing, email changed: get, commit (NO explicit flush: the UPDATE is flushed implicitly by commit)
  * existing, same email:    get only

What each sub-stage covers:
  profile_get          Session.get(Profile). On an identity-map miss this is a SELECT. In /auth/login it is the first
                       statement on the request Session, so it also covers connection checkout and transaction begin.
  email_commit         existing profile with a changed email: commit() = implicit flush (UPDATE profiles) + COMMIT.
  profile_add          Session.add(profile): in-memory only, no SQL.
  profile_flush        INSERT profiles. On PostgreSQL, a concurrent first login for the same user that has inserted
                       but not yet committed the same primary key makes this INSERT WAIT for that transaction; it
                       then fails with IntegrityError (other side committed) or proceeds (other side rolled back).
  activity_add i       Session.add(activity #i): in-memory only.
  activity_flush i     Session.flush() flushes the WHOLE session, not just activity #i: it INSERTs activity #i AND
                       the TimerDraft/Schedule rows still pending from activity_children_add i-1. So a slow or
                       failing activity_flush i may be caused by the previous activity's timer draft or schedule.
  activity_children_add i
                       Session.add of activity #i's TimerDraft (timed) and/or Schedule (has weekdays): in-memory
                       only; logged even when the activity has neither, so the sequence is fixed.
  wallet_world_add     Session.add(WalletAccount), Session.add(ChildWorld): in-memory only.
  final_flush          INSERT wallet_accounts, child_worlds, plus whatever activity_children_add of the LAST activity
                       left pending (nothing for the current table: its last entry has no timer draft or schedule).
  active_world_flush   UPDATE profiles SET active_world (needs the child_worlds row from final_flush).
  commit               COMMIT (its implicit flush has nothing left to write after active_world_flush).
  integrity_rollback   IntegrityError from any flush/commit above (concurrent first login): rollback().
  integrity_reread     Session.get(Profile) again after the rollback; if it finds nothing, the IntegrityError is
                       re-raised and shows at the enclosing `ensure_profile` stage.
A failing stage identifies WHICH flush/commit statement batch waited or failed, not which object caused it.
Index i is the position in DEFAULT_ACTIVITIES (0..10). No values (ids, emails, names, codes) are logged.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import local_date
from app.core.login_stages import optional_stage
from app.db.models import Activity, ChildWorld, Profile, Schedule, TimerDraft, WalletAccount
from app.integrations.supabase_auth import Principal
from app.modules.activities.schedules import mask_from_weekdays
from app.modules.world.catalog import DEFAULT_THEME

DEFAULT_TIMEZONE = "Europe/Moscow"

# code, name, icon, kind, category, objective, target_seconds, reward_eligible, weekdays (None = voluntary)
DEFAULT_ACTIVITIES: tuple[tuple, ...] = (
    ("math", "Математика", "∑", "timed", "lesson", "decrease", None, True, None),
    ("russian", "Русский язык", "Аа", "timed", "lesson", "decrease", None, True, None),
    ("literature", "Литературное чтение", "▤", "timed", "lesson", "decrease", None, True, None),
    ("nature", "Окружающий мир", "❀", "timed", "lesson", "decrease", None, True, None),
    ("english", "Английский язык", "En", "timed", "lesson", "decrease", None, True, None),
    ("walk", "Прогулка", "☀", "timed", "walk", "reach", 7200, True, None),
    ("reading", "Внеклассное чтение", "▥", "timed", "reading", "reach", 1200, False, None),
    ("bag", "Собрать рюкзак на завтра", None, "boolean", "chore", "none", None, True, [1, 2, 3, 4, 5]),
    ("plants", "Полить цветы", None, "boolean", "chore", "none", None, True, [5]),
    ("room", "Навести порядок на столе", None, "boolean", "chore", "none", None, True, [1, 2, 3, 4, 5, 6, 7]),
    ("help", "Помочь дома", None, "boolean", "chore", "none", None, False, None),
)


def _display_name(principal: Principal) -> str:
    for key in ("display_name", "full_name", "name"):
        value = principal.user_metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:40]
    if principal.email and "@" in principal.email:
        local = principal.email.split("@", 1)[0].strip()
        if local:
            return local[:40]
    return "Исследователь"


def ensure_profile(db: Session, principal: Principal, *, login_request_id: str | None = None) -> Profile:
    """`login_request_id`: pass only from POST /auth/login to log value-free sub-stages (see module docstring)."""
    rid = login_request_id
    with optional_stage(rid, "ensure_profile.profile_get"):
        profile = db.get(Profile, principal.user_id)
    if profile is not None:
        if principal.email and profile.email != principal.email:
            profile.email = principal.email
            with optional_stage(rid, "ensure_profile.email_commit"):
                db.commit()  # implicit flush of the UPDATE; deliberately no explicit flush
        return profile
    try:
        profile = _provision(db, principal, rid)
        with optional_stage(rid, "ensure_profile.commit"):
            db.commit()
        return profile
    except IntegrityError:
        # Concurrent first requests: the other one won; use its result.
        with optional_stage(rid, "ensure_profile.integrity_rollback"):
            db.rollback()
        with optional_stage(rid, "ensure_profile.integrity_reread"):
            profile = db.get(Profile, principal.user_id)
        if profile is None:
            raise
        return profile


def _provision(db: Session, principal: Principal, rid: str | None = None) -> Profile:
    today = local_date(DEFAULT_TIMEZONE)
    uid = principal.user_id
    profile = Profile(
        id=uid,
        email=principal.email,
        display_name=_display_name(principal),
        role="child",
        timezone=DEFAULT_TIMEZONE,
        theme="system",
        active_world=None,
        onboarding_version=0,
        rewards_started_on=today,
    )
    with optional_stage(rid, "ensure_profile.profile_add"):
        db.add(profile)
    with optional_stage(rid, "ensure_profile.profile_flush"):
        db.flush()
    for order, (code, name, icon, kind, category, objective, target, eligible, weekdays) in enumerate(
        DEFAULT_ACTIVITIES
    ):
        act = Activity(
            child_id=uid, code=code, name=name, icon=icon, kind=kind, category=category, objective=objective,
            target_seconds=target, reward_eligible=eligible, sort_order=(order + 1) * 10, created_by=None,
        )
        with optional_stage(rid, "ensure_profile.activity_add", order):
            db.add(act)
        # Whole-session flush: also writes the previous activity's still-pending TimerDraft/Schedule.
        with optional_stage(rid, "ensure_profile.activity_flush", order):
            db.flush()
        with optional_stage(rid, "ensure_profile.activity_children_add", order):
            if kind == "timed":
                db.add(TimerDraft(child_id=uid, activity_id=act.id))
            if weekdays:
                db.add(Schedule(child_id=uid, activity_id=act.id, weekdays_mask=mask_from_weekdays(weekdays),
                                starts_on=today))
    with optional_stage(rid, "ensure_profile.wallet_world_add"):
        db.add(WalletAccount(child_id=uid, balance=0))
        db.add(ChildWorld(child_id=uid, theme_code=DEFAULT_THEME, position=0))
    with optional_stage(rid, "ensure_profile.final_flush"):
        db.flush()  # also the last activity's pending children, if any
    profile.active_world = DEFAULT_THEME
    with optional_stage(rid, "ensure_profile.active_world_flush"):
        db.flush()
    return profile


def linked_children(db: Session, guardian: Profile) -> list[Profile]:
    from app.db.models import GuardianChild

    rows = db.execute(
        select(Profile).join(GuardianChild, GuardianChild.child_id == Profile.id)
        .where(GuardianChild.guardian_id == guardian.id).order_by(Profile.display_name)
    ).scalars()
    return list(rows)
