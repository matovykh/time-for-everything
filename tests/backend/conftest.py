"""Independent QA harness for the backend (owned by QA; does not import backend/tests).

* Auth goes through the REAL production path: `tfe_at` cookie → JWT verification (HS256 test secret)
  → revocation check → provisioning. There is NO `get_principal` override. Only Supabase's HTTP API is
  replaced by an httpx.MockTransport injected through the `get_auth_client` dependency seam.
* DB: SQLite (ORM metadata) by default. Set QA_TEST_DATABASE_URL=postgresql://…@127.0.0.1:PORT/tfe_qa
  to run on a DISPOSABLE local PostgreSQL with the real SQL migrations (schema public is dropped!).
  The URL must use a loopback host and a database named tfe_qa*; anything else is refused.
* Canary secrets are injected into the environment so leak tests can search responses and logs.

Run from repo root:  backend/.venv/bin/python -m pytest tests/backend -p no:cacheprovider
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlsplit

import pytest

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

CANARY_JWT_SECRET = "qa-canary-jwt-secret-" + "Z" * 40
CANARY_OPENAI = "sk-qa-canary-" + "K" * 40
CANARY_PUBLISHABLE = "sb_publishable_qa_canary_" + "P" * 20
SUPABASE = "https://qacanaryprojectref.supabase.co"

for _k in ("DATABASE_URL", "CONFIG_FILE", "APP_BASE_URL"):
    os.environ.pop(_k, None)
os.environ.update({
    "APP_ENV": "test",
    "SUPABASE_URL": SUPABASE,
    "SUPABASE_PUBLISHABLE_KEY": CANARY_PUBLISHABLE,
    "SUPABASE_JWT_SECRET": CANARY_JWT_SECRET,
    "OPENAI_API_KEY": CANARY_OPENAI,
})

import httpx  # noqa: E402
import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine, event, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core import deps  # noqa: E402
from app.core.clock import clock  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import login_limiter  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.db.models import (  # noqa: E402
    Base,
    GuardianChild,
    Profile,
    RewardPolicy,
    SchemaMigration,
    WorldCatalogItem,
    WorldTheme,
)
from app.integrations.supabase_auth import SupabaseAuthClient  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.rewards.policy import PARAMETERS, POLICY_VERSION  # noqa: E402
from app.modules.wallet import service as wallet  # noqa: E402
from app.modules.world.catalog import THEMES, UPGRADES  # noqa: E402

FIXED_NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)  # Tuesday, 12:00 Europe/Moscow
PG_URL = os.environ.get("QA_TEST_DATABASE_URL") or None


_DB_NAME_RE = re.compile(r"^tfe_qa(?:_[a-z0-9_]{1,40})?$")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
# libpq/psycopg query parameters that can silently redirect the connection or re-target the database.
_FORBIDDEN_QUERY = {"host", "hostaddr", "port", "dbname", "service", "servicefile", "options", "user",
                    "passfile", "target_session_attrs", "load_balance_hosts"}
_FORBIDDEN_ENV = ("PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")


def _check_pg_url(url: str) -> None:
    """Fail closed BEFORE any connection: this mode DROPs schema public."""
    if os.environ.get("QA_ALLOW_DESTRUCTIVE_TEST_DB") != "1":
        raise pytest.UsageError("QA_TEST_DATABASE_URL drops schema public: set QA_ALLOW_DESTRUCTIVE_TEST_DB=1 exactly")
    parts = urlsplit(url)
    if parts.scheme not in ("postgresql", "postgres"):
        raise pytest.UsageError("QA_TEST_DATABASE_URL must be postgresql://")
    if "," in parts.netloc or parts.hostname not in _LOOPBACK:
        raise pytest.UsageError("QA_TEST_DATABASE_URL must point to exactly one loopback host")
    if not _DB_NAME_RE.match(unquote(parts.path.lstrip("/"))):
        raise pytest.UsageError("QA_TEST_DATABASE_URL database name must be tfe_qa or tfe_qa_<suffix>")
    bad = {k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)} & _FORBIDDEN_QUERY
    if bad:
        raise pytest.UsageError(f"QA_TEST_DATABASE_URL must not override connection target via query: {sorted(bad)}")
    env = [k for k in _FORBIDDEN_ENV if os.environ.get(k)]
    if env:
        raise pytest.UsageError(f"unset libpq target overrides before a destructive run: {env}")


def _seed(db: Session) -> None:
    for i, t in enumerate(THEMES):
        db.add(WorldTheme(code=t.code, name=t.name, sort_order=i + 1))
    db.flush()
    for t in THEMES:
        for i, u in enumerate(UPGRADES):
            db.add(WorldCatalogItem(theme_code=t.code, code=u.code, position=i, cost=u.cost, requires_code=u.requires))
    db.add(RewardPolicy(version=POLICY_VERSION, parameters=PARAMETERS, effective_from=FIXED_NOW.date()))
    db.add(SchemaMigration(version=db_session.REQUIRED_SCHEMA_VERSION))
    db.commit()


def _sqlite(path: Path) -> Engine:
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(eng, "connect")
    def _c(conn, _r):  # noqa: ANN001
        conn.isolation_level = None
        conn.execute("pragma foreign_keys = on")
        conn.create_function("char_length", 1, lambda s: None if s is None else len(s), deterministic=True)

    @event.listens_for(eng, "begin")
    def _b(conn):  # noqa: ANN001
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    Base.metadata.create_all(eng)
    with Session(eng) as db:
        _seed(db)
    return eng


_pg: Engine | None = None


def _postgres() -> Engine:
    global _pg
    _check_pg_url(PG_URL)  # re-checked on every use, before connect and before DROP
    if _pg is None:
        eng = create_engine(PG_URL.replace("postgresql://", "postgresql+psycopg://", 1),
                            connect_args={"prepare_threshold": None})
        raw = eng.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute("select current_database()")  # server addr is the container IP behind a port-forward
            (dbname,) = cur.fetchone()
            if not _DB_NAME_RE.match(dbname):
                raise pytest.UsageError(f"connected database {dbname!r} is not a disposable tfe_qa DB")
            cur.execute("drop schema if exists public cascade; create schema public;")
            cur.execute((BACKEND / "tests" / "sql" / "supabase_stub.sql").read_text())
            for f in sorted((REPO / "supabase" / "migrations").glob("*.sql")):
                cur.execute(f.read_text())
            raw.commit()
        finally:
            raw.close()
        _pg = eng
    with _pg.begin() as conn:
        tables = [r[0] for r in conn.execute(text(
            "select tablename from pg_tables where schemaname='public' and tablename not in "
            "('world_themes','world_catalog','reward_policies','app_schema_migrations')"))]
        conn.exec_driver_sql("truncate " + ", ".join(f"public.{t}" for t in tables) + ", auth.users cascade")
    return _pg


@pytest.fixture
def engine(tmp_path: Path):
    eng = _postgres() if PG_URL else _sqlite(tmp_path / "qa.db")
    db_session.configure_engine(eng)
    yield eng
    db_session.configure_engine(None)
    if not PG_URL:
        eng.dispose()


@pytest.fixture(autouse=True)
def _env():
    clock.set(FIXED_NOW)
    login_limiter.reset()
    get_settings.cache_clear()
    deps.get_verifier.cache_clear()
    yield
    clock.set(None)
    get_settings.cache_clear()
    deps.get_verifier.cache_clear()
    app.dependency_overrides.clear()


def set_now(value: datetime) -> None:
    clock.set(value)


def at(day: date, hour_utc: int = 9) -> None:
    set_now(datetime(day.year, day.month, day.day, hour_utc, tzinfo=UTC))


def mint(sub: uuid.UUID, session_id: str | None = None, exp_delta: int = 3600) -> str:
    now = int(time.time())  # JWT exp is checked against the real wall clock by PyJWT
    claims = {"sub": str(sub), "aud": "authenticated", "iss": f"{SUPABASE}/auth/v1", "role": "authenticated",
              "exp": now + exp_delta, "iat": now, "email": f"{str(sub)[:8]}@qa.test", "user_metadata": {}}
    if session_id:
        claims["session_id"] = session_id
    return jwt.encode(claims, CANARY_JWT_SECRET, algorithm="HS256")


class FakeSupabase:
    """Lenient upstream: accepts any refresh token and any logout, so only backend-side controls count."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.url.path == "/auth/v1/logout":
            return httpx.Response(204)
        if request.url.path == "/auth/v1/token":
            body = json.loads(request.content or b"{}")
            sub = uuid.UUID(body.get("refresh_token", "rt:" + str(uuid.uuid4())).split(":", 1)[1]) \
                if body.get("refresh_token", "").startswith("rt:") else uuid.uuid4()
            return httpx.Response(200, json={"access_token": mint(sub, session_id=str(uuid.uuid4())),
                                             "refresh_token": f"rt:{sub}", "expires_in": 3600, "user": {}})
        return httpx.Response(404)


@pytest.fixture
def fake_supabase():
    fake = FakeSupabase()
    app.dependency_overrides[deps.get_auth_client] = lambda: SupabaseAuthClient(
        get_settings(), transport=httpx.MockTransport(fake.handler))
    return fake


class Api:
    """Browser-like client for one user with real session cookies and CSRF bootstrap."""

    def __init__(self, engine: Engine, user_id: uuid.UUID | None = None) -> None:
        self.user_id = user_id or uuid.uuid4()
        self.session_id = str(uuid.uuid4())
        self.engine = engine
        if engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                conn.execute(text("insert into auth.users (id, email) values (:i, :e) on conflict do nothing"),
                             {"i": self.user_id, "e": f"{str(self.user_id)[:8]}@qa.test"})
        self.client = TestClient(app, base_url="https://testserver")
        self.csrf = self.client.get("/api/v1/auth/csrf").json()["csrf_token"]
        self.client.headers["X-CSRF-Token"] = self.csrf
        self.access = mint(self.user_id, self.session_id)
        self.client.cookies.set("tfe_at", self.access)
        self.client.cookies.set("tfe_rt", f"rt:{self.user_id}")
        r = self.client.get("/api/v1/me")
        assert r.status_code == 200, r.text

    def __getattr__(self, name):
        return getattr(self.client, name)

    def activity(self, code: str) -> dict:
        items = self.client.get("/api/v1/activities", params={"include_archived": True}).json()["items"]
        return next(a for a in items if a["code"] == code)

    def timer(self, activity_id: str, cmd: str, revision: int, key: str | None = None, **body):
        return self.client.post(f"/api/v1/activities/{activity_id}/timer/{cmd}", json={"revision": revision, **body},
                                headers={"Idempotency-Key": key or uuid.uuid4().hex})


@pytest.fixture
def make_api(engine):
    return lambda user_id=None: Api(engine, user_id)


@pytest.fixture
def child(make_api) -> Api:
    return make_api()


def make_guardian(make_api, engine, kid: Api) -> Api:
    g = make_api()
    with Session(engine) as db:  # operator action (DB-only in MVP per API.md §1.4)
        db.get(Profile, g.user_id).role = "guardian"
        db.add(GuardianChild(guardian_id=g.user_id, child_id=kid.user_id))
        db.commit()
    g.client.headers["X-Child-Id"] = str(kid.user_id)
    return g


def grant(engine, child_id, amount: int) -> None:
    with Session(engine) as db:
        wallet.post(db, child_id=child_id, amount=amount, reason_code="adjustment", description="qa grant",
                    idempotency_key=f"qa:{uuid.uuid4()}")
        db.commit()
