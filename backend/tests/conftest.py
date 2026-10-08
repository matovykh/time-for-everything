"""Test harness.

* Default: SQLite file DB built from the ORM metadata (foreign keys ON, BEGIN IMMEDIATE so
  concurrent writers serialise like row locks would).
* TEST_DATABASE_URL=postgresql://… : a DISPOSABLE PostgreSQL. The real SQL migration is applied
  on top of a local Supabase stub (tests/sql/supabase_stub.sql). Requires TFE_ALLOW_DESTRUCTIVE_TEST_DB=1,
  a loopback host and database `tfe_test[_suffix]` — validated before connecting (tests/db_safety.py).

Authentication: the only bypass is an explicit FastAPI dependency override of `get_principal`
installed here (header X-Test-User). Production code has no such switch. JWT verification itself
is tested separately in test_auth.py.
"""

from __future__ import annotations

import os
import uuid
import warnings
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)

for _k in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_JWT_SECRET", "OPENAI_API_KEY",
           "CONFIG_FILE", "APP_BASE_URL"):
    os.environ.pop(_k, None)
os.environ["APP_ENV"] = "test"

from fastapi import Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine, event, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.clock import clock  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.deps import get_principal  # noqa: E402
from app.core.errors import ApiError  # noqa: E402
from app.core.security import login_limiter  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.db.models import Base, RewardPolicy, SchemaMigration, WorldCatalogItem, WorldTheme  # noqa: E402
from app.integrations.supabase_auth import Principal  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.rewards.policy import PARAMETERS, POLICY_VERSION  # noqa: E402
from app.modules.world.catalog import THEMES, UPGRADES  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PG_URL = os.environ.get("TEST_DATABASE_URL") or None
if PG_URL:
    from tests.db_safety import UnsafeTestDatabase, validate_test_database_url

    try:  # fail closed BEFORE any connection: this mode drops schema public
        validate_test_database_url(PG_URL, os.environ)
    except UnsafeTestDatabase as exc:
        raise pytest.UsageError(f"Refusing destructive Postgres test run: {exc}") from None
FIXED_NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)  # 12:00 in Europe/Moscow, Tuesday

APP_TABLES = ["world_events", "world_unlocks", "child_worlds", "reward_evaluations", "wallet_transactions",
              "wallet_accounts", "day_statuses", "time_entries", "timer_drafts", "chore_completions", "schedules",
              "activities", "guardian_children", "profiles", "audit_events", "idempotency_requests",
              "revoked_sessions"]


def seed_reference(db: Session) -> None:
    for i, t in enumerate(THEMES):
        db.add(WorldTheme(code=t.code, name=t.name, sort_order=i + 1))
    db.flush()
    for t in THEMES:
        for i, u in enumerate(UPGRADES):
            db.add(WorldCatalogItem(theme_code=t.code, code=u.code, position=i, cost=u.cost, requires_code=u.requires))
    db.add(RewardPolicy(version=POLICY_VERSION, parameters=PARAMETERS, effective_from=FIXED_NOW.date()))
    db.add(SchemaMigration(version=db_session.REQUIRED_SCHEMA_VERSION))
    db.commit()


def _sqlite_engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        dbapi_conn.isolation_level = None
        dbapi_conn.execute("pragma foreign_keys = on")
        dbapi_conn.create_function("char_length", 1, lambda s: None if s is None else len(s), deterministic=True)

    @event.listens_for(engine, "begin")
    def _on_begin(conn):  # noqa: ANN001
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_reference(db)
    return engine


_pg_engine: Engine | None = None


def _postgres_engine() -> Engine:
    global _pg_engine
    if _pg_engine is None:
        from tests.db_safety import validate_test_database_url

        validate_test_database_url(PG_URL, os.environ)  # re-checked right before the DROP
        url = PG_URL.replace("postgresql://", "postgresql+psycopg://", 1)
        engine = create_engine(url, connect_args={"prepare_threshold": None})
        raw = engine.raw_connection()  # no parameters → psycopg leaves %I in format() alone
        try:
            cur = raw.cursor()
            cur.execute("drop schema if exists public cascade; create schema public;")
            cur.execute((Path(__file__).parent / "sql" / "supabase_stub.sql").read_text())
            for f in sorted((REPO / "supabase" / "migrations").glob("*.sql")):
                cur.execute(f.read_text())
            raw.commit()
        finally:
            raw.close()
        _pg_engine = engine
    with _pg_engine.begin() as conn:
        conn.exec_driver_sql("truncate " + ", ".join(f"public.{t}" for t in APP_TABLES) + ", auth.users cascade")
    return _pg_engine


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = _postgres_engine() if PG_URL else _sqlite_engine(tmp_path / "test.db")
    db_session.configure_engine(eng)
    yield eng
    db_session.configure_engine(None)
    if not PG_URL:
        eng.dispose()


@pytest.fixture(autouse=True)
def _frozen_clock() -> Iterator[None]:
    clock.set(FIXED_NOW)
    login_limiter.reset()
    get_settings.cache_clear()
    yield
    clock.set(None)
    get_settings.cache_clear()
    app.dependency_overrides.clear()


def _test_principal(request: Request) -> Principal:
    uid = request.headers.get("x-test-user")
    if not uid:
        raise ApiError(401, "not_authenticated", "Нужно войти.")
    return Principal(user_id=uuid.UUID(uid), email=f"{uid[:8]}@example.test", user_metadata={})


def ensure_auth_user(engine: Engine, user_id: uuid.UUID) -> None:
    """Postgres runs only: emulate the Supabase-managed auth.users row the FK expects."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("insert into auth.users (id, email) values (:id, :e) on conflict do nothing"),
                         {"id": user_id, "e": f"{str(user_id)[:8]}@example.test"})


class Api:
    """A browser-like client for one user: own cookie jar, CSRF bootstrap, test identity."""

    def __init__(self, user_id: uuid.UUID, engine: Engine) -> None:
        self.user_id = user_id
        self.client = TestClient(app, base_url="https://testserver")
        token = self.client.get("/api/v1/auth/csrf").json()["csrf_token"]
        self.client.headers.update({"X-Test-User": str(user_id), "X-CSRF-Token": token})
        ensure_auth_user(engine, user_id)

    def __getattr__(self, name: str):  # get/post/put/patch/delete
        return getattr(self.client, name)

    def activity(self, code: str) -> dict:
        items = self.client.get("/api/v1/activities", params={"include_archived": True}).json()["items"]
        return next(a for a in items if a["code"] == code)

    def timer(self, activity_id: str, cmd: str, revision: int, key: str | None = None, **body) -> object:
        return self.client.post(f"/api/v1/activities/{activity_id}/timer/{cmd}", json={"revision": revision, **body},
                                headers={"Idempotency-Key": key or uuid.uuid4().hex})


@pytest.fixture
def make_api(engine: Engine):
    app.dependency_overrides[get_principal] = _test_principal

    def _make(user_id: uuid.UUID | None = None) -> Api:
        return Api(user_id or uuid.uuid4(), engine)

    return _make


@pytest.fixture
def api(make_api) -> Api:
    a = make_api()
    assert a.get("/api/v1/me").status_code == 200  # provisions the profile
    return a


def set_now(value: datetime) -> None:
    clock.set(value)
