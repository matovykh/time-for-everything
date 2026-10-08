"""Shared helpers for scripts/db_migrate.py and scripts/db_reset.py.

Only touches application-owned objects in schema `public`. Never references Supabase-managed
schemas (auth, storage, realtime, …) in any DDL it generates.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"
MIGRATION_RE = re.compile(r"^(\d{14})_[a-z0-9_]+\.sql$")
ADVISORY_LOCK_ID = 7_310_062_026  # arbitrary constant for "vse-uspeyu migrations"

# Reverse dependency order. No CASCADE: unexpected dependants make the reset fail loudly.
APP_TABLES = (
    "world_events", "world_unlocks", "child_worlds", "reward_evaluations", "wallet_transactions",
    "wallet_accounts", "day_statuses", "time_entries", "timer_drafts", "chore_completions", "schedules",
    "activities", "guardian_children", "profiles", "world_catalog", "world_themes", "reward_policies",
    "audit_events", "idempotency_requests", "revoked_sessions", "app_schema_migrations",
)
APP_FUNCTIONS = (
    "tfe_can_read_child(uuid)", "tfe_forbid_ledger_change()", "tfe_protect_final_evaluation()",
)
MANAGED_SCHEMAS = ("auth", "storage", "realtime", "supabase_functions", "extensions", "graphql", "vault")


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path

    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


def migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    out = []
    for p in sorted(directory.glob("*.sql")):
        m = MIGRATION_RE.match(p.name)
        if not m:
            raise SystemExit(f"Unexpected migration file name: {p.name}")
        out.append(Migration(m.group(1), p))
    return out


@dataclass(frozen=True)
class Target:
    host: str
    port: int
    database: str
    user: str
    project_ref: str
    is_supabase: bool

    def describe(self) -> str:
        kind = "Supabase project" if self.is_supabase else "PostgreSQL host"
        return f"{kind} ref={self.project_ref} host={self.host}:{self.port} db={self.database} user={self.user}"


def parse_target(url: str) -> Target:
    parts = urlsplit(url)
    if parts.scheme not in ("postgresql", "postgres", "postgresql+psycopg"):
        raise SystemExit("DATABASE_URL must be a postgresql:// URL")
    host = parts.hostname or ""
    user = unquote(parts.username or "")
    ref = None
    m = re.match(r"^db\.([a-z0-9]{20})\.supabase\.(co|com)$", host)
    if m:
        ref = m.group(1)
    elif host.endswith(".pooler.supabase.com"):
        m2 = re.match(r"^[^.]+\.([a-z0-9]{20})$", user)
        ref = m2.group(1) if m2 else None
    is_supabase = ref is not None
    return Target(host=host, port=parts.port or 5432, database=(parts.path or "/postgres").lstrip("/") or "postgres",
                  user=user, project_ref=ref or host, is_supabase=is_supabase)


def database_url(cli_value: str | None) -> str:
    url = cli_value or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL or pass --database-url.")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def drop_statements() -> list[str]:
    stmts = [f"drop table if exists public.{t};" for t in APP_TABLES]
    stmts += [f"drop function if exists public.{f};" for f in APP_FUNCTIONS]
    assert_only_public(stmts)
    return stmts


def assert_only_public(stmts: list[str]) -> None:
    for s in stmts:
        lowered = s.lower()
        if " public." not in lowered or any(f" {schema}." in lowered for schema in MANAGED_SCHEMAS):
            raise SystemExit(f"Refusing to run statement outside the application schema: {s}")


def connect(url: str):  # pragma: no cover - requires a live database
    try:
        import psycopg
    except ImportError:
        sys.exit("psycopg is required: pip install -r backend/requirements.txt")
    # autocommit=True: every `with conn.transaction():` block is a real, self-contained transaction.
    return psycopg.connect(url, autocommit=True, connect_timeout=10, prepare_threshold=None)
