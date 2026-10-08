"""Engine/session management. The engine is created lazily; nothing is created in the DB."""

from __future__ import annotations

import threading
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import ApiError
from app.db.models import SchemaMigration

# Latest migration file in supabase/migrations (checked by a test).
REQUIRED_SCHEMA_VERSION = "20261006000002"

_lock = threading.Lock()
_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None
_schema_ok = False


def build_engine(url: str, pool_size: int = 5) -> Engine:
    if url.startswith("postgresql"):
        return create_engine(
            url,
            hide_parameters=True,  # bound values (PII) never appear in exception text or logs
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=pool_size,
            pool_recycle=1800,
            # prepare_threshold=None keeps psycopg compatible with Supabase's transaction pooler.
            connect_args={"connect_timeout": 5, "prepare_threshold": None, "application_name": "vse-uspeyu"},
        )
    return create_engine(url, hide_parameters=True)


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
            configure_engine(build_engine(settings.sqlalchemy_url, settings.db_pool_size))
    return _engine


def schema_status(engine: Engine) -> str:
    """'ok' | 'missing' | 'outdated'. Raises SQLAlchemyError when unreachable."""
    with engine.connect() as conn:
        try:
            rows = conn.execute(select(SchemaMigration.version)).scalars().all()
        except SQLAlchemyError:
            conn.rollback()
            return "missing"
    if not rows:
        return "missing"
    return "ok" if REQUIRED_SCHEMA_VERSION in rows else "outdated"


def ping(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("select 1"))


def _ensure_schema(engine: Engine) -> None:
    global _schema_ok
    if _schema_ok:
        return
    try:
        status = schema_status(engine)
    except SQLAlchemyError as exc:
        raise ApiError(503, "service_not_configured", "База данных недоступна.",
                       details={"database": "unreachable"}) from exc
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


def get_db() -> Iterator[Session]:
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
