"""Idempotent provisioning of a freshly authenticated Supabase user.

Role is always `child` here; elevation to guardian/admin is an operator action in the database.
Supabase `user_metadata` is user-editable, so it is used for the display name only.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import local_date
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


def ensure_profile(db: Session, principal: Principal) -> Profile:
    profile = db.get(Profile, principal.user_id)
    if profile is not None:
        if principal.email and profile.email != principal.email:
            profile.email = principal.email
            db.commit()
        return profile
    try:
        profile = _provision(db, principal)
        db.commit()
        return profile
    except IntegrityError:
        # Concurrent first requests: the other one won; use its result.
        db.rollback()
        profile = db.get(Profile, principal.user_id)
        if profile is None:
            raise
        return profile


def _provision(db: Session, principal: Principal) -> Profile:
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
    db.add(profile)
    db.flush()
    for order, (code, name, icon, kind, category, objective, target, eligible, weekdays) in enumerate(
        DEFAULT_ACTIVITIES
    ):
        act = Activity(
            child_id=uid, code=code, name=name, icon=icon, kind=kind, category=category, objective=objective,
            target_seconds=target, reward_eligible=eligible, sort_order=(order + 1) * 10, created_by=None,
        )
        db.add(act)
        db.flush()
        if kind == "timed":
            db.add(TimerDraft(child_id=uid, activity_id=act.id))
        if weekdays:
            db.add(Schedule(child_id=uid, activity_id=act.id, weekdays_mask=mask_from_weekdays(weekdays),
                            starts_on=today))
    db.add(WalletAccount(child_id=uid, balance=0))
    db.add(ChildWorld(child_id=uid, theme_code=DEFAULT_THEME, position=0))
    db.flush()
    profile.active_world = DEFAULT_THEME
    db.flush()
    return profile


def linked_children(db: Session, guardian: Profile) -> list[Profile]:
    from app.db.models import GuardianChild

    rows = db.execute(
        select(Profile).join(GuardianChild, GuardianChild.child_id == Profile.id)
        .where(GuardianChild.guardian_id == guardian.id).order_by(Profile.display_name)
    ).scalars()
    return list(rows)
