"""ORM mapping of the application schema.

The authoritative production DDL (RLS, grants, triggers, auth.users FK) lives in
`supabase/migrations/*.sql`. This module mirrors it closely enough for the backend and for
SQLite-based tests (`Base.metadata.create_all` is used **only** by tests). The Postgres test
run (TEST_DATABASE_URL) applies the real SQL migration instead and therefore detects drift.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.clock import clock

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return clock.now()


class Base(DeclarativeBase):
    pass


TS = DateTime(timezone=True)


class SchemaMigration(Base):
    __tablename__ = "app_schema_migrations"
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(TS, default=_now)


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("role in ('child','guardian','admin')", name="profiles_role_check"),
        CheckConstraint("theme in ('light','dark','system')", name="profiles_theme_check"),
        CheckConstraint("char_length(display_name) between 1 and 40", name="profiles_display_name_check"),
        CheckConstraint("onboarding_version >= 0", name="profiles_onboarding_check"),
    )
    # FK to auth.users(id) exists in the SQL migration only (managed Supabase schema).
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    grade: Mapped[str | None] = mapped_column(String(2))
    role: Mapped[str] = mapped_column(String(16), default="child")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    theme: Mapped[str] = mapped_column(String(8), default="system")
    active_world: Mapped[str | None] = mapped_column(ForeignKey("world_themes.code"))
    onboarding_version: Mapped[int] = mapped_column(Integer, default=0)
    rewards_started_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[datetime] = mapped_column(TS, default=_now, onupdate=_now)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class GuardianChild(Base):
    __tablename__ = "guardian_children"
    __table_args__ = (CheckConstraint("guardian_id <> child_id", name="guardian_children_distinct"),)
    guardian_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("id", "child_id", name="activities_id_child_key"),
        UniqueConstraint("child_id", "code", name="activities_child_code_key"),
        CheckConstraint("kind in ('timed','boolean')", name="activities_kind_check"),
        CheckConstraint(
            "(kind = 'timed' and category in ('lesson','walk','reading','custom'))"
            " or (kind = 'boolean' and category = 'chore')",
            name="activities_kind_category_check",
        ),
        CheckConstraint("objective in ('decrease','reach','maintain','none')", name="activities_objective_check"),
        CheckConstraint(
            "target_seconds is null or target_seconds between 60 and 86400", name="activities_target_check"
        ),
        CheckConstraint("char_length(name) between 1 and 70", name="activities_name_check"),
        Index("activities_child_idx", "child_id", "sort_order"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    code: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(8))
    category: Mapped[str] = mapped_column(String(8))
    objective: Mapped[str] = mapped_column(String(8), default="none")
    target_seconds: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    reward_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(TS)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[datetime] = mapped_column(TS, default=_now, onupdate=_now)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_id", "child_id"], ["activities.id", "activities.child_id"], ondelete="CASCADE"
        ),
        CheckConstraint("weekdays_mask between 1 and 127", name="schedules_mask_check"),
        CheckConstraint("ends_on is null or ends_on >= starts_on", name="schedules_range_check"),
        Index("schedules_activity_idx", "activity_id", "starts_on"),
        Index("schedules_child_idx", "child_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    activity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    weekdays_mask: Mapped[int] = mapped_column(Integer)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class ChoreCompletion(Base):
    __tablename__ = "chore_completions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_id", "child_id"], ["activities.id", "activities.child_id"], ondelete="CASCADE"
        ),
        UniqueConstraint("activity_id", "local_date", name="chore_completions_activity_date_key"),
        Index("chore_completions_child_date_idx", "child_id", "local_date"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    activity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    local_date: Mapped[date] = mapped_column(Date)
    scheduled: Mapped[bool] = mapped_column(Boolean)
    completed_at: Mapped[datetime] = mapped_column(TS, default=_now)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class TimerDraft(Base):
    __tablename__ = "timer_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_id", "child_id"], ["activities.id", "activities.child_id"], ondelete="CASCADE"
        ),
        UniqueConstraint("child_id", "activity_id", name="timer_drafts_child_activity_key"),
        CheckConstraint("state in ('idle','running','paused')", name="timer_drafts_state_check"),
        CheckConstraint("accumulated_ms >= 0", name="timer_drafts_accumulated_check"),
        CheckConstraint(
            "(state = 'running') = (running_since is not null)", name="timer_drafts_running_since_check"
        ),
        CheckConstraint(
            "state <> 'idle' or (accumulated_ms = 0 and session_started_at is null)",
            name="timer_drafts_idle_check",
        ),
        Index("timer_drafts_child_state_idx", "child_id", "state"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    activity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(8), default="idle")
    accumulated_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    running_since: Mapped[datetime | None] = mapped_column(TS)
    session_started_at: Mapped[datetime | None] = mapped_column(TS)
    started_on: Mapped[date | None] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(TS, default=_now, onupdate=_now)


class TimeEntry(Base):
    __tablename__ = "time_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_id", "child_id"], ["activities.id", "activities.child_id"], ondelete="CASCADE"
        ),
        CheckConstraint("duration_seconds between 1 and 86400", name="time_entries_duration_check"),
        CheckConstraint("source in ('timer','manual')", name="time_entries_source_check"),
        CheckConstraint(
            "quality_status in ('pending','confirmed','rejected','not_required')", name="time_entries_quality_check"
        ),
        CheckConstraint("workload in ('normal','increased','excluded')", name="time_entries_workload_check"),
        CheckConstraint("char_length(note) <= 500", name="time_entries_note_check"),
        Index("time_entries_child_date_idx", "child_id", "activity_date"),
        Index("time_entries_activity_date_idx", "activity_id", "activity_date"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    activity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    activity_date: Mapped[date] = mapped_column(Date)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(8))
    quality_status: Mapped[str] = mapped_column(String(16))
    workload: Mapped[str] = mapped_column(String(10), default="normal")
    note: Mapped[str] = mapped_column(Text, default="")
    deleted_at: Mapped[datetime | None] = mapped_column(TS)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[datetime] = mapped_column(TS, default=_now, onupdate=_now)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class DayStatus(Base):
    __tablename__ = "day_statuses"
    __table_args__ = (
        CheckConstraint("category in ('walk')", name="day_statuses_category_check"),
        CheckConstraint("status in ('no_walk','excluded')", name="day_statuses_status_check"),
    )
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    category: Mapped[str] = mapped_column(String(8), primary_key=True)
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(10))
    set_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(TS, default=_now, onupdate=_now)


class RewardPolicy(Base):
    __tablename__ = "reward_policies"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONType)
    effective_from: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class WalletAccount(Base):
    __tablename__ = "wallet_accounts"
    __table_args__ = (CheckConstraint("balance >= 0", name="wallet_accounts_balance_check"),)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(TS, default=_now, onupdate=_now)


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="wallet_transactions_amount_check"),
        CheckConstraint("balance_after >= 0", name="wallet_transactions_balance_after_check"),
        CheckConstraint(
            "reason_code in ('reward_lessons','reward_walk','reward_chores','world_purchase','adjustment')",
            name="wallet_transactions_reason_check",
        ),
        Index("wallet_transactions_child_created_idx", "child_id", "created_at"),
        UniqueConstraint("child_id", "seq", name="wallet_transactions_child_seq_key"),
        CheckConstraint("seq >= 1", name="wallet_transactions_seq_check"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wallet_accounts.child_id", ondelete="CASCADE"))
    # Per-child ledger order assigned under the wallet lock (commit order, unlike created_at).
    seq: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    reason_code: Mapped[str] = mapped_column(String(24))
    description: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str | None] = mapped_column(String(24))
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    period_end: Mapped[date | None] = mapped_column(Date)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class RewardEvaluation(Base):
    __tablename__ = "reward_evaluations"
    __table_args__ = (
        UniqueConstraint("child_id", "period_end", "category", name="reward_evaluations_period_key"),
        CheckConstraint("category in ('lessons','walk','chores')", name="reward_evaluations_category_check"),
        CheckConstraint("state in ('deferred','final')", name="reward_evaluations_state_check"),
        CheckConstraint("amount >= 0", name="reward_evaluations_amount_check"),
        CheckConstraint("mode in ('deterministic','ai_assisted')", name="reward_evaluations_mode_check"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    policy_version: Mapped[int] = mapped_column(ForeignKey("reward_policies.version"))
    category: Mapped[str] = mapped_column(String(8))
    period_end: Mapped[date] = mapped_column(Date)
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    baseline_start: Mapped[date] = mapped_column(Date)
    baseline_end: Mapped[date] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer, default=0)
    reason_code: Mapped[str] = mapped_column(String(40))
    explanation: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType)
    mode: Mapped[str] = mapped_column(String(16), default="deterministic")
    wallet_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("wallet_transactions.id"))
    evaluated_at: Mapped[datetime] = mapped_column(TS, default=_now)
    finalized_at: Mapped[datetime | None] = mapped_column(TS)


class WorldTheme(Base):
    __tablename__ = "world_themes"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)


class WorldCatalogItem(Base):
    __tablename__ = "world_catalog"
    __table_args__ = (
        UniqueConstraint("theme_code", "code", name="world_catalog_theme_code_key"),
        CheckConstraint("cost >= 0", name="world_catalog_cost_check"),
        ForeignKeyConstraint(
            ["theme_code", "requires_code"], ["world_catalog.theme_code", "world_catalog.code"],
            name="world_catalog_requires_fkey",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    theme_code: Mapped[str] = mapped_column(ForeignKey("world_themes.code"))
    code: Mapped[str] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer)
    cost: Mapped[int] = mapped_column(Integer)
    requires_code: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)


class ChildWorld(Base):
    __tablename__ = "child_worlds"
    __table_args__ = (
        UniqueConstraint("child_id", "theme_code", name="child_worlds_child_theme_key"),
        UniqueConstraint("id", "child_id", "theme_code", name="child_worlds_identity_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    theme_code: Mapped[str] = mapped_column(ForeignKey("world_themes.code"))
    position: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(TS, default=_now)


class WorldUnlock(Base):
    __tablename__ = "world_unlocks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["child_world_id", "child_id", "theme_code"],
            ["child_worlds.id", "child_worlds.child_id", "child_worlds.theme_code"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["theme_code", "upgrade_code"], ["world_catalog.theme_code", "world_catalog.code"]),
        UniqueConstraint("child_world_id", "upgrade_code", name="world_unlocks_world_upgrade_key"),
        CheckConstraint("cost >= 0", name="world_unlocks_cost_check"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    child_world_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    theme_code: Mapped[str] = mapped_column(String(32))
    upgrade_code: Mapped[str] = mapped_column(String(32))
    cost: Mapped[int] = mapped_column(Integer)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wallet_transactions.id"), unique=True)
    purchased_at: Mapped[datetime] = mapped_column(TS, default=_now)


class WorldEvent(Base):
    __tablename__ = "world_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["child_world_id", "child_id", "theme_code"],
            ["child_worlds.id", "child_worlds.child_id", "child_worlds.theme_code"],
            ondelete="CASCADE",
        ),
        Index("world_events_world_idx", "child_world_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    child_world_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    theme_code: Mapped[str] = mapped_column(String(32))
    upgrade_code: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(24), default="upgrade_unlocked")
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("audit_events_child_idx", "child_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    child_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(48))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)


class RevokedSession(Base):
    """Local logout revocations: `sid:<supabase session_id>`, `at:<sha256>`, `rt:<sha256>`."""

    __tablename__ = "revoked_sessions"
    __table_args__ = (
        CheckConstraint("kind in ('session','access_token','refresh_token')", name="revoked_sessions_kind_check"),
        Index("revoked_sessions_expires_idx", "expires_at"),
        Index("revoked_sessions_user_idx", "user_id"),
    )
    key: Mapped[str] = mapped_column(String(140), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    revoked_at: Mapped[datetime] = mapped_column(TS, default=_now)
    expires_at: Mapped[datetime] = mapped_column(TS)


class IdempotencyRequest(Base):
    __tablename__ = "idempotency_requests"
    __table_args__ = (Index("idempotency_requests_expires_idx", "expires_at"),)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)  # "<acting child id>:<Idempotency-Key>"
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)
    expires_at: Mapped[datetime] = mapped_column(TS)
