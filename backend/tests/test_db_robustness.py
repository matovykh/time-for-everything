"""Database robustness: connection options, precise schema classification, bounded readiness,
value-free DB diagnostics and DB-independent 401s. No network access is needed."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from types import SimpleNamespace

import jwt
import psycopg
import psycopg.errors as pg_errors
import pytest
from fastapi.testclient import TestClient
from psycopg import pq
from psycopg.conninfo import make_conninfo
from sqlalchemy import URL, create_engine, text
from sqlalchemy import exc as sa_exc
from sqlalchemy.pool import NullPool, QueuePool

from app.core import deps
from app.core.config import Settings, get_settings, load_settings
from app.db import session as db_session
from app.db.errors import classify_db_error, describe_db_error, is_unavailable_error, is_undefined_table
from app.main import app

SECRET_HOST = "db.secretprojectref.supabase.co"
SECRET_PW = "canary-" + "db-credential-in-driver-message"  # only ever inside a fake driver error text
# No credentials: create_engine() never connects in these tests.
PG_URL = URL.create("postgresql+psycopg", username="postgres", host="127.0.0.1", port=1,
                    database="postgres").render_as_string()


def _wrap(orig: Exception, cls: type[sa_exc.DBAPIError] = sa_exc.OperationalError) -> sa_exc.DBAPIError:
    return cls("select version from app_schema_migrations", None, orig)


def _ssl_timeout() -> sa_exc.DBAPIError:
    return _wrap(psycopg.OperationalError(
        f"consuming input failed: SSL SYSCALL error: Operation timed out (host={SECRET_HOST} pw={SECRET_PW})"))


# ---- connection / pool options ------------------------------------------------------------------
def test_default_connect_args_are_bounded_and_valid_libpq_keywords():
    args = db_session.pg_connect_args(Settings())
    assert args == {"connect_timeout": 5, "prepare_threshold": None, "application_name": "vse-uspeyu",
                    "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3,
                    "tcp_user_timeout": 30000}
    libpq = {k: v for k, v in args.items() if k != "prepare_threshold"}  # psycopg-only option
    parsed = {o.keyword.decode(): o.val for o in pq.Conninfo.parse(make_conninfo("", **libpq).encode())}
    for k, v in libpq.items():
        assert parsed[k] == str(v).encode(), k  # an unknown keyword would have raised


def test_connect_args_follow_settings():
    args = db_session.pg_connect_args(Settings(db_tcp_keepalives=False, db_tcp_user_timeout_ms=0,
                                               db_connect_timeout_seconds=12))
    assert args["keepalives"] == 0 and "keepalives_idle" not in args and "tcp_user_timeout" not in args
    assert args["connect_timeout"] == 12


def test_default_pool_preserves_previous_behaviour():
    eng = db_session.build_engine(PG_URL, Settings())  # create_engine never connects
    try:
        pool = eng.pool
        assert isinstance(pool, QueuePool)
        assert pool.size() == 5 and pool._max_overflow == 5 and pool._timeout == 30
        assert pool._recycle == 1800 and pool._pre_ping is True
        assert eng.hide_parameters is True
    finally:
        eng.dispose()


def test_pool_settings_and_diagnostic_null_pool():
    eng = db_session.build_engine(PG_URL, Settings(db_pool_size=3, db_max_overflow=0, db_pool_timeout_seconds=7,
                                                   db_pool_recycle_seconds=600, db_pool_pre_ping=False))
    assert eng.pool.size() == 3 and eng.pool._max_overflow == 0 and eng.pool._timeout == 7
    assert eng.pool._recycle == 600 and eng.pool._pre_ping is False
    eng.dispose()
    eng = db_session.build_engine(PG_URL, Settings(db_null_pool=True))
    assert isinstance(eng.pool, NullPool)
    eng.dispose()


def test_db_settings_parse_from_environment(monkeypatch):
    monkeypatch.setenv("DB_MAX_OVERFLOW", "")
    monkeypatch.setenv("DB_NULL_POOL", "true")
    monkeypatch.setenv("DB_TCP_USER_TIMEOUT_MS", "0")
    monkeypatch.setenv("DB_READY_TIMEOUT_SECONDS", "2.5")
    s = load_settings()
    assert s.db_max_overflow is None and s.db_null_pool and s.db_tcp_user_timeout_ms == 0
    assert s.db_ready_timeout_seconds == 2.5


@pytest.mark.parametrize("key,value", [("DB_CONNECT_TIMEOUT_SECONDS", "0"), ("DB_TCP_KEEPALIVES_COUNT", "0"),
                                       ("DB_POOL_TIMEOUT_SECONDS", "100000"), ("DB_READY_TIMEOUT_SECONDS", "0")])
def test_db_settings_are_bounded(monkeypatch, key, value):
    from app.core.config import ConfigError

    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigError, match=key):
        load_settings()


# ---- error classification -----------------------------------------------------------------------
def test_only_undefined_table_counts_as_missing_schema():
    assert is_undefined_table(_wrap(pg_errors.UndefinedTable("relation does not exist"), sa_exc.ProgrammingError))
    for orig in (pg_errors.InsufficientPrivilege("permission denied"), pg_errors.UndefinedColumn("no column"),
                 pg_errors.QueryCanceled("canceling statement"), psycopg.OperationalError("SSL SYSCALL error")):
        assert not is_undefined_table(_wrap(orig)), type(orig).__name__


@pytest.mark.parametrize("exc,category,unavailable", [
    (_ssl_timeout(), "timeout", True),
    (_wrap(psycopg.OperationalError("server closed the connection unexpectedly")), "connection", True),
    (_wrap(psycopg.OperationalError("password authentication failed for user")), "authentication", True),
    (_wrap(pg_errors.AdminShutdown("terminating")), "server_shutdown", True),
    (_wrap(pg_errors.QueryCanceled("canceling statement due to statement timeout")), "query_canceled", True),
    (_wrap(pg_errors.TooManyConnections("too many")), "too_many_connections", True),
    (sa_exc.TimeoutError("QueuePool limit reached"), "pool_timeout", True),
    (_wrap(pg_errors.InsufficientPrivilege("denied"), sa_exc.ProgrammingError), "permission_denied", False),
    (_wrap(pg_errors.UndefinedTable("nope"), sa_exc.ProgrammingError), "undefined_table", False),
    (_wrap(pg_errors.UniqueViolation("dup"), sa_exc.IntegrityError), "database_error", False),
])
def test_classification(exc, category, unavailable):
    assert classify_db_error(exc) == category
    assert is_unavailable_error(exc) is unavailable


def test_description_is_value_free():
    info = describe_db_error(_ssl_timeout())
    assert info == {"category": "timeout", "error": "OperationalError", "driver_error": "OperationalError",
                    "sqlstate": None}
    info = describe_db_error(_wrap(pg_errors.UndefinedTable("x"), sa_exc.ProgrammingError))
    assert info["sqlstate"] == "42P01" and info["driver_error"] == "UndefinedTable"


# ---- schema_status --------------------------------------------------------------------------------
class _FailingEngine:
    """engine.connect() works; every statement fails with the given error (e.g. an SSL read timeout)."""

    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.driver_sql: list[str] = []

    def exec_driver_sql(self, sql: str):
        self.driver_sql.append(sql)

    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *_a, **_k):
        raise self.exc

    def rollback(self):
        raise AssertionError("must not swallow a non-undefined-table error")


def test_schema_status_reraises_timeouts_instead_of_reporting_missing():
    with pytest.raises(sa_exc.OperationalError):
        db_session.schema_status(_FailingEngine(_ssl_timeout()))
    with pytest.raises(sa_exc.ProgrammingError):
        db_session.schema_status(_FailingEngine(_wrap(pg_errors.InsufficientPrivilege("x"), sa_exc.ProgrammingError)))


def test_schema_status_sqlite(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 's.db'}")
    try:
        assert db_session.schema_status(eng) == "missing"  # no table
        with eng.begin() as c:
            c.execute(text("create table app_schema_migrations (applied_at text)"))  # wrong shape
        with pytest.raises(sa_exc.OperationalError):
            db_session.schema_status(eng)
        with eng.begin() as c:
            c.execute(text("drop table app_schema_migrations"))
            c.execute(text("create table app_schema_migrations (version text primary key, applied_at text)"))
        assert db_session.schema_status(eng) == "missing"  # empty
        with eng.begin() as c:
            c.execute(text("insert into app_schema_migrations (version) values ('1')"))
        assert db_session.schema_status(eng) == "outdated"
    finally:
        eng.dispose()


# ---- /health/ready -------------------------------------------------------------------------------
class _HealthyPgConn(_FailingEngine):
    """Fake PostgreSQL connection that answers the probe."""

    def __init__(self) -> None:
        super().__init__(AssertionError())
        self.rolled_back = False

    def execute(self, *_a, **_k):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [db_session.REQUIRED_SCHEMA_VERSION]))

    def rollback(self):
        self.rolled_back = True


def test_probe_sets_transaction_scoped_statement_timeout_on_postgres():
    conn = _HealthyPgConn()
    assert db_session._check_database(conn, 2500) == db_session.DbCheck("ok", "ok")
    assert conn.driver_sql == ["SET LOCAL statement_timeout = 2500"] and conn.rolled_back


def test_probe_failure_on_postgres_is_unreachable_with_category():
    conn = _FailingEngine(_ssl_timeout())
    result = db_session._check_database(conn, 1000)
    assert conn.driver_sql == ["SET LOCAL statement_timeout = 1000"]
    assert (result.database, result.schema, result.diagnostics["category"]) == ("unreachable", "unknown", "timeout")
    canceled = db_session._check_database(_FailingEngine(_wrap(pg_errors.QueryCanceled("statement timeout"))), 1)
    assert canceled.database == "unreachable" and canceled.diagnostics["category"] == "query_canceled"


def test_probe_on_sqlite_issues_no_set_local(engine):
    assert db_session.check_database(engine, 5) == db_session.DbCheck("ok", "ok")


@pytest.mark.postgres
@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")
def test_probe_statement_timeout_does_not_leak_into_pool(engine):
    with engine.connect() as c:
        default = c.exec_driver_sql("show statement_timeout").scalar()
    assert db_session.check_database(engine, 5) == db_session.DbCheck("ok", "ok")
    for _ in range(3):
        with engine.connect() as c:
            assert c.exec_driver_sql("show statement_timeout").scalar() == default


def test_ready_reports_timeout_as_unreachable_not_missing(engine, monkeypatch, caplog):
    def read_schema_status(_conn):
        raise _ssl_timeout()

    monkeypatch.setattr(db_session, "_read_schema_status", read_schema_status)
    caplog.set_level(logging.DEBUG)
    r = TestClient(app).get("/api/v1/health/ready")
    body = r.json()
    assert r.status_code == 503
    assert body["checks"]["database"] == "unreachable" and body["checks"]["schema"] == "unknown"
    assert body["diagnostics"]["database"]["category"] == "timeout"
    logged = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "category=timeout" in logged
    for secret in (SECRET_HOST, SECRET_PW, "SSL SYSCALL"):
        assert secret not in r.text and secret not in logged


def test_ready_answers_within_bound_and_is_single_flight(engine, monkeypatch):
    monkeypatch.setenv("DB_READY_TIMEOUT_SECONDS", "0.2")
    get_settings.cache_clear()
    release = threading.Event()
    calls: list[int] = []

    def hanging_check(_engine, _ms):
        calls.append(1)
        release.wait(10)
        return db_session.DbCheck("ok", "ok")

    monkeypatch.setattr(db_session, "_check_database", hanging_check)
    c = TestClient(app)
    try:
        for _ in range(3):
            t0 = time.monotonic()
            body = c.get("/api/v1/health/ready").json()
            assert time.monotonic() - t0 < 3
            assert body["checks"]["database"] == "timeout" and body["status"] == "not_ready"
            assert body["diagnostics"]["database"]["category"] == "probe_timeout"
        assert len(calls) == 1  # later probes joined the pending check
    finally:
        release.set()


def test_stale_probe_is_replaced_but_abandoned_threads_are_capped(engine, monkeypatch):
    release = threading.Event()
    calls: list[int] = []

    def hanging_check(_engine, _ms):
        calls.append(1)
        release.wait(10)
        return db_session.DbCheck("ok", "ok")

    monkeypatch.setattr(db_session, "_check_database", hanging_check)
    monkeypatch.setattr(db_session, "_probe_is_stale", lambda _started, _timeout: True)
    try:
        for _ in range(db_session.MAX_ABANDONED_PROBES + 3):
            assert db_session.check_database(engine, 0.05).database == "timeout"
        assert len(calls) == 1 + db_session.MAX_ABANDONED_PROBES
    finally:
        release.set()
    time.sleep(0.05)
    monkeypatch.setattr(db_session, "_check_database", lambda _e, _ms: db_session.DbCheck("ok", "ok"))
    assert db_session.check_database(engine, 2).database == "ok"  # recovers once threads finish


# ---- data routes ---------------------------------------------------------------------------------
def test_schema_check_timeout_on_data_route_is_503_database_unavailable(make_api, monkeypatch, caplog):
    a = make_api()
    db_session.configure_engine(db_session._engine)  # reset the cached "schema ok"

    def schema_status(_engine):
        raise _ssl_timeout()

    monkeypatch.setattr(db_session, "schema_status", schema_status)
    caplog.set_level(logging.DEBUG)
    r = a.get("/api/v1/activities")
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    assert r.json()["details"] == {"database": "unreachable", "reason": "timeout"}
    logged = "\n".join(rec.getMessage() for rec in caplog.records)
    assert SECRET_HOST not in r.text + logged and SECRET_PW not in r.text + logged


def test_mid_request_connection_loss_is_503_and_other_db_errors_stay_500(api, monkeypatch, caplog):
    import app.modules.activities.service as activities

    errors = iter([_ssl_timeout(), _wrap(pg_errors.UniqueViolation(f"dup {SECRET_PW}"), sa_exc.IntegrityError)])

    def boom(*_a, **_k):
        raise next(errors)

    monkeypatch.setattr(activities, "list_activities", boom)
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    client.headers.update(api.client.headers)
    caplog.set_level(logging.DEBUG)
    r = client.get("/api/v1/activities")
    assert r.status_code == 503 and r.json()["code"] == "database_unavailable"
    assert r.headers["retry-after"] == "5" and r.json()["details"] == {"reason": "timeout"}
    r2 = client.get("/api/v1/activities")
    assert r2.status_code == 500 and r2.json()["code"] == "internal_error"
    logged = "\n".join(rec.getMessage() + str(rec.exc_text or "") for rec in caplog.records)
    assert r.json()["request_id"] in logged and "Traceback" not in logged
    for secret in (SECRET_HOST, SECRET_PW):
        assert secret not in r.text + r2.text + logged


# ---- 401 without database readiness --------------------------------------------------------------
JWT_SECRET = "test-only-hs256-secret-with-enough-length-0123456789"
SUPABASE = "https://abcdefghijklmnopqrst.supabase.co"


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_only")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    get_settings.cache_clear()
    deps.get_verifier.cache_clear()
    yield
    deps.get_verifier.cache_clear()


def _token() -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(uuid.uuid4()), "aud": "authenticated", "iss": f"{SUPABASE}/auth/v1",
                       "role": "authenticated", "exp": now + 3600, "iat": now}, JWT_SECRET, algorithm="HS256")


@pytest.mark.parametrize("db_state", ["not_configured", "timing_out"])
def test_unauthenticated_me_is_401_without_database(auth_env, monkeypatch, tmp_path, db_state):
    if db_state == "not_configured":
        db_session.configure_engine(None)
    else:
        db_session.configure_engine(create_engine(f"sqlite:///{tmp_path / 'x.db'}"))

        def schema_status(_engine):
            raise _ssl_timeout()

        monkeypatch.setattr(db_session, "schema_status", schema_status)
    try:
        c = TestClient(app, base_url="https://testserver")
        assert c.get("/api/v1/me").status_code == 401
        c.cookies.set("tfe_at", "not-a-jwt")
        assert c.get("/api/v1/me").status_code == 401
        # A genuine token cannot be checked against the revocation list: fail closed with 503.
        c.cookies.set("tfe_at", _token())
        r = c.get("/api/v1/me")
        expected = "service_not_configured" if db_state == "not_configured" else "database_unavailable"
        assert r.status_code == 503 and r.json()["code"] == expected
    finally:
        db_session.configure_engine(None)
