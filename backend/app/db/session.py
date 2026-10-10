"""Engine/session management. The engine is created lazily; nothing is created in the DB.

Timeouts, honestly stated (see DB_* settings in backend/.env.example):
* `connect_timeout` bounds connection establishment only (per host attempt).
* TCP keepalives detect a peer that silently vanished while we wait for a reply; `tcp_user_timeout`
  (Linux) bounds how long sent data may stay unacknowledged. Together they turn an indefinite
  "consuming input failed: SSL SYSCALL error" hang into a bounded error *when the network path dies*.
* None of these is a total query deadline: a live but slow server keeps the socket healthy.
  GET /health/ready therefore additionally bounds its own wait (DB_READY_TIMEOUT_SECONDS).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.login_stages import db_dependency_stage
from app.db.errors import (
    UNAVAILABLE_CATEGORIES,
    classify_db_error,
    describe_db_error,
    is_undefined_table,
    log_db_error,
)
from app.db.models import SchemaMigration

# Latest migration file in supabase/migrations (checked by a test).
REQUIRED_SCHEMA_VERSION = "20261006000002"
APPLICATION_NAME = "vse-uspeyu"

log = logging.getLogger("app.db")

_lock = threading.Lock()
_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None
_schema_ok = False


def pg_connect_args(settings: Settings) -> dict[str, Any]:
    """libpq/psycopg connection parameters. They override same-named parameters in DATABASE_URL."""
    args: dict[str, Any] = {
        "connect_timeout": settings.db_connect_timeout_seconds,
        # prepare_threshold=None keeps psycopg compatible with Supabase's transaction pooler.
        "prepare_threshold": None,
        "application_name": APPLICATION_NAME,
    }
    if settings.db_tcp_keepalives:
        args.update(keepalives=1, keepalives_idle=settings.db_tcp_keepalives_idle_seconds,
                    keepalives_interval=settings.db_tcp_keepalives_interval_seconds,
                    keepalives_count=settings.db_tcp_keepalives_count)
    else:
        args["keepalives"] = 0
    if settings.db_tcp_user_timeout_ms > 0:
        args["tcp_user_timeout"] = settings.db_tcp_user_timeout_ms
    return args


def build_engine(url: str, settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    if not url.startswith("postgresql"):
        return create_engine(url, hide_parameters=True)
    common: dict[str, Any] = {
        "hide_parameters": True,  # bound values (PII) never appear in exception text or logs
        "connect_args": pg_connect_args(settings),
    }
    if settings.db_null_pool:
        # Diagnostic mode: every checkout opens (and every checkin closes) a real connection, so a
        # stale pooled socket can be ruled out. Slower; pool settings do not apply.
        return create_engine(url, poolclass=NullPool, **common)
    overflow = settings.db_pool_size if settings.db_max_overflow is None else settings.db_max_overflow
    return create_engine(
        url,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_size=settings.db_pool_size,
        max_overflow=overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
        **common,
    )


def configure_engine(engine: Engine | None) -> None:
    """Install an explicit engine (used by tests and by get_engine on first use)."""
    global _engine, _factory, _schema_ok
    with _lock:
        _engine = engine
        _factory = sessionmaker(bind=engine, expire_on_commit=False) if engine is not None else None
        _schema_ok = False


def get_engine() -> Engine | None:
    if _engine is None:
        settings = get_settings()
        if settings.sqlalchemy_url:
            configure_engine(build_engine(settings.sqlalchemy_url, settings))
    return _engine


def schema_status(engine: Engine) -> str:
    """'ok' | 'missing' | 'outdated'.

    'missing' only when the migrations table does not exist (undefined table) or is empty. Any other
    error — timeouts, dropped connections, permission problems — is re-raised as SQLAlchemyError so the
    caller reports the database as unavailable instead of claiming the schema is absent."""
    with engine.connect() as conn:
        return _read_schema_status(conn)


def _read_schema_status(conn: Connection) -> str:
    try:
        rows = conn.execute(select(SchemaMigration.version)).scalars().all()
    except SQLAlchemyError as exc:
        if not is_undefined_table(exc):
            raise
        conn.rollback()
        return "missing"
    if not rows:
        return "missing"
    return "ok" if REQUIRED_SCHEMA_VERSION in rows else "outdated"


def ping(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("select 1"))


# ---- readiness probe ------------------------------------------------------------------------------
@dataclass(frozen=True)
class DbCheck:
    database: str  # ok | unreachable | error | timeout
    schema: str  # ok | missing | outdated | unknown
    diagnostics: dict[str, Any] | None = None  # value-free (see app.db.errors)


def _failed_check(exc: SQLAlchemyError) -> DbCheck:
    info = log_db_error("database readiness check failed", exc)
    state = "unreachable" if info["category"] in UNAVAILABLE_CATEGORIES else "error"
    return DbCheck(state, "unknown", info)


def _check_database(engine: Engine, statement_timeout_ms: int) -> DbCheck:
    """ping + schema check on ONE pooled connection inside one transaction that is rolled back.

    PostgreSQL only: `SET LOCAL statement_timeout` makes a live-but-slow server cancel the probe's
    statements (57014) server-side. SET LOCAL is transaction-scoped, so it is safe with Supabase's
    transaction pooler and never leaks onto pooled connections. It does NOT help when the network path
    hangs (the cancellation never arrives) — that case is bounded only by the TCP settings."""
    try:
        with engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                # int-formatted literal: SET does not accept bind parameters under server-side binding.
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
            conn.execute(text("select 1"))
            status = _read_schema_status(conn)
            conn.rollback()
        return DbCheck("ok", status)
    except SQLAlchemyError as exc:
        return _failed_check(exc)


def _run_probe(engine: Engine, fut: Future[DbCheck], statement_timeout_ms: int) -> None:
    try:
        fut.set_result(_check_database(engine, statement_timeout_ms))
    except Exception as exc:  # noqa: BLE001 - never let the probe thread die silently
        log.error("database readiness check crashed error=%s", type(exc).__name__)
        fut.set_result(DbCheck("error", "unknown", {"category": "unexpected", "error": type(exc).__name__,
                                                     "driver_error": None, "sqlstate": None}))


_probe_lock = threading.Lock()
_probe: tuple[Engine, Future[DbCheck], float] | None = None  # engine, result, start (monotonic)
_abandoned: list[Future[DbCheck]] = []  # stale probes whose threads may still be blocked on a socket
MAX_ABANDONED_PROBES = 3


def _probe_is_stale(started: float, timeout: float) -> bool:
    return time.monotonic() - started > max(3 * timeout, 30.0)


def check_database(engine: Engine, timeout: float) -> DbCheck:
    """ping + schema_status, answered within `timeout` seconds.

    The check runs in a background thread. If it overruns, the caller gets database='timeout' while the
    thread keeps waiting on the socket (bounded by the TCP settings, not by this function). Single-flight:
    concurrent/subsequent probes join a still-running check instead of starting more threads. A check
    pending for longer than max(3*timeout, 30s) is abandoned and replaced, so one wedged socket cannot
    pin readiness at 'timeout' forever. Threads are bounded: at most 1 + MAX_ABANDONED_PROBES exist.

    Residual (by design, to avoid unbounded threads): if all of them stay wedged — a network hang the
    TCP keepalive/tcp_user_timeout settings do not end, e.g. those settings disabled or non-Linux —
    readiness keeps answering 'timeout' (promptly) until a thread finishes or the process restarts."""
    global _probe
    with _probe_lock:
        _abandoned[:] = [f for f in _abandoned if not f.done()]
        pending = _probe is not None and _probe[0] is engine and not _probe[1].done()
        if pending and (not _probe_is_stale(_probe[2], timeout) or len(_abandoned) >= MAX_ABANDONED_PROBES):
            fut = _probe[1]
        else:
            if pending:
                _abandoned.append(_probe[1])
                log.warning("database readiness check stale; starting a new one (abandoned=%d)", len(_abandoned))
            fut = Future()
            _probe = (engine, fut, time.monotonic())
            threading.Thread(target=_run_probe, args=(engine, fut, max(100, int(timeout * 1000))),
                             name="db-ready-probe", daemon=True).start()
    try:
        return fut.result(timeout=timeout)
    except FutureTimeout:
        log.warning("database readiness check exceeded %.1fs (still pending in background)", timeout)
        return DbCheck("timeout", "unknown", {"category": "probe_timeout", "error": None, "driver_error": None,
                                              "sqlstate": None})


# ---- request dependencies -------------------------------------------------------------------------
def _ensure_schema(engine: Engine) -> None:
    global _schema_ok
    if _schema_ok:
        return
    try:
        status = schema_status(engine)
    except SQLAlchemyError as exc:
        info = log_db_error("database schema check failed", exc)
        raise ApiError(503, "database_unavailable", "База данных временно недоступна. Попробуйте позже.",
                       details={"database": "unreachable", "reason": info["category"]}) from exc
    if status != "ok":
        raise ApiError(503, "schema_missing",
                       "Схема БД не применена. Выполните scripts/db_migrate.py (см. backend/README.md).",
                       details={"schema": status, "required_version": REQUIRED_SCHEMA_VERSION})
    _schema_ok = True


def get_optional_db() -> Iterator[Session | None]:
    """Like get_db, but yields None when the DB is not configured/ready (used by logout)."""
    engine = get_engine()
    try:
        if engine is None or _factory is None:
            raise ApiError(503, "service_not_configured", "")
        _ensure_schema(engine)
    except ApiError:
        yield None
        return
    session = _factory()
    try:
        yield session
    finally:
        session.close()


def get_db(request: Request) -> Iterator[Session]:
    # Endpoints marked with time_db_dependency (login) get a db_dependency stage around acquisition; else no-op.
    with db_dependency_stage(request):
        engine = get_engine()
        if engine is None or _factory is None:
            raise ApiError(503, "service_not_configured", "Сервер ещё не настроен: не задано подключение к БД.",
                           details={"missing": get_settings().missing_settings()})
        _ensure_schema(engine)
        session = _factory()
    try:
        yield session
    finally:
        session.close()


__all__ = ["REQUIRED_SCHEMA_VERSION", "DbCheck", "build_engine", "check_database", "classify_db_error",
           "configure_engine", "describe_db_error", "get_db", "get_engine", "get_optional_db", "ping",
           "pg_connect_args", "schema_status"]
