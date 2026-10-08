"""Secret-leak regression tests for configuration loading, API responses and logs.

Every value here is a SYNTHETIC canary generated per run (no real credentials). Strings are concatenated
so the repository secret scanner does not mistake the test source itself for a leak. These tests pin the
specific leak paths we know about; they are not a proof that no other path exists.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import ConfigError, Settings, get_settings, load_settings
from app.core.log_redaction import (
    REDACTED_QUERY,
    AccessLogQueryRedactor,
    TracebackSuppressor,
    install_access_log_redaction,
    install_traceback_suppression,
)
from app.db import session as db_session
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]
RUN = uuid.uuid4().hex
CANARY_DB_PW = "tfecanarydbpw" + RUN
CANARY_KEY = "tfecanarykey" + RUN
CANARY_JWT = "tfecanaryjwt" + RUN
CANARY_AI = "tfecanaryai" + RUN
CANARY_QUERY = "tfecanaryquery" + RUN
CANARIES = (CANARY_DB_PW, CANARY_KEY, CANARY_JWT, CANARY_AI)
# Loopback port 1: a connection attempt is refused immediately, no external network is touched.
CANARY_DSN = "postgresql://canary_user:" + CANARY_DB_PW + "@127.0.0.1:1/canary_db?sslmode=disable"
SECRET_KEYS = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_JWT_SECRET", "OPENAI_API_KEY",
               "CONFIG_FILE", "APP_ENV", "DB_POOL_SIZE", "APP_BASE_URL")


def _env_file(tmp_path: Path, lines: list[str], name: str = "app.env") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    p.chmod(0o600)
    return p


def _valid_lines() -> list[str]:
    return [
        "APP_ENV=test",
        "DATABASE_" + "URL=" + CANARY_DSN,
        "SUPABASE_URL=https://canaryprojectref.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY=" + CANARY_KEY,
        "SUPABASE_JWT_" + "SECRET=" + CANARY_JWT,
        "OPENAI_API_" + "KEY=" + CANARY_AI,
    ]


def _assert_clean(text: str, *extra: str) -> None:
    for canary in (*CANARIES, *extra):
        assert canary not in text
        assert canary[-12:] not in text  # partial echo, e.g. a truncated value


def _assert_safe_config_error(exc: ConfigError, *extra: str) -> None:
    _assert_clean(str(exc), *extra)
    assert exc.__cause__ is None and exc.__suppress_context__  # no chained ValidationError/decode error


@pytest.fixture
def clean_env(monkeypatch):
    for k in SECRET_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()
    db_session.configure_engine(None)


# ---- config validation never echoes values ----------------------------------------------------
def test_validation_error_hides_input(clean_env):
    with pytest.raises(ValidationError) as info:
        Settings(app_env=CANARY_KEY, db_pool_size=CANARY_JWT)
    _assert_clean(str(info.value) + repr(info.value))


def test_invalid_environment_values_raise_value_free_config_error(clean_env):
    clean_env.setenv("APP_ENV", CANARY_KEY)
    clean_env.setenv("DB_POOL_SIZE", CANARY_JWT)
    with pytest.raises(ConfigError) as info:
        load_settings()
    _assert_safe_config_error(info.value)
    assert "APP_ENV" in str(info.value) and "DB_POOL_SIZE" in str(info.value)


def test_missing_explicit_config_file_fails_closed(clean_env, tmp_path):
    clean_env.setenv("CONFIG_FILE", str(tmp_path / "absent.env"))
    with pytest.raises(ConfigError, match="does not exist"):
        get_settings()


def test_config_file_that_is_a_directory_fails_closed(clean_env, tmp_path):
    clean_env.setenv("CONFIG_FILE", str(tmp_path))
    with pytest.raises(ConfigError, match="not a regular file"):
        get_settings()


@pytest.mark.skipif(not hasattr(os, "getuid") or os.getuid() == 0, reason="root bypasses file modes")
def test_unreadable_config_file_fails_closed_without_content(clean_env, tmp_path):
    p = _env_file(tmp_path, _valid_lines())
    p.chmod(0o000)
    try:
        clean_env.setenv("CONFIG_FILE", str(p))
        with pytest.raises(ConfigError, match="not readable") as info:
            get_settings()
        _assert_safe_config_error(info.value)
    finally:
        p.chmod(0o600)


def test_invalid_values_in_config_file_are_not_echoed(clean_env, tmp_path):
    p = _env_file(tmp_path, [*_valid_lines(), "APP_ENV=" + CANARY_KEY, "LOGIN_RATE_LIMIT=" + CANARY_AI])
    clean_env.delenv("APP_ENV")  # process environment would win over the file
    clean_env.setenv("CONFIG_FILE", str(p))
    with pytest.raises(ConfigError) as info:
        get_settings()
    _assert_safe_config_error(info.value)
    assert "APP_ENV" in str(info.value) and "LOGIN_RATE_LIMIT" in str(info.value) and str(p) in str(info.value)


def test_non_utf8_config_file_is_not_echoed(clean_env, tmp_path):
    p = tmp_path / "app.env"
    p.write_bytes(b"OPENAI_API_" + b"KEY=" + CANARY_AI.encode() + b"\xff\xfe\n")
    clean_env.setenv("CONFIG_FILE", str(p))
    with pytest.raises(ConfigError) as info:
        get_settings()
    _assert_safe_config_error(info.value)


def test_empty_config_file_variable_means_environment_only(clean_env):
    clean_env.setenv("CONFIG_FILE", "  ")
    assert get_settings().database_configured is False


def test_loaded_settings_never_render_secrets(clean_env, tmp_path):
    clean_env.setenv("CONFIG_FILE", str(_env_file(tmp_path, _valid_lines())))
    s = get_settings()
    assert s.database_configured and s.auth_configured and s.openai_api_key is not None
    assert s.supabase_jwt_secret is not None and s.supabase_jwt_secret.get_secret_value() == CANARY_JWT
    _assert_clean(repr(s) + str(s) + s.model_dump_json() + repr(s.model_dump()))


def test_environment_overrides_config_file(clean_env, tmp_path):
    clean_env.setenv("CONFIG_FILE", str(_env_file(tmp_path, _valid_lines())))
    clean_env.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_from_env")
    assert get_settings().supabase_publishable_key.get_secret_value() == "sb_publishable_from_env"


# ---- API responses and application logs -------------------------------------------------------
def test_configured_secrets_absent_from_api_responses_and_logs(clean_env, tmp_path, caplog, make_api):
    clean_env.setenv("CONFIG_FILE", str(_env_file(tmp_path, _valid_lines())))
    caplog.set_level(logging.DEBUG)
    bodies: list[str] = []
    a = make_api()  # installs the fixture engine; exercises the authenticated settings route
    for path in ("/api/v1/me", "/api/v1/settings", "/api/v1/health/ready", "/api/v1/health/live",
                 "/api/v1/does-not-exist", "/"):
        r = a.get(path)
        bodies.append(r.text + repr(dict(r.headers)))
    settings = a.get("/api/v1/settings").json()["integrations"]
    assert settings == {"database": {"configured": True}, "supabase_auth": {"configured": True},
                        "openai": {"configured": True}}
    # Readiness against the canary DSN itself (refused on loopback): reported, never echoed.
    db_session.configure_engine(None)
    r = TestClient(app, base_url="https://testserver").get("/api/v1/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["database"] == "unreachable"
    bodies.append(r.text)
    logged = "\n".join(rec.getMessage() + str(rec.exc_text or "") for rec in caplog.records)
    _assert_clean("\n".join(bodies) + logged)


def test_query_string_canary_absent_from_error_logs(clean_env, caplog):
    caplog.set_level(logging.DEBUG)
    c = TestClient(app, base_url="https://testserver")
    for path in ("/api/v1/health/live", "/api/v1/does-not-exist", "/api/v1/me"):
        c.get(path, params={"access_token": CANARY_QUERY})
    # Server-side records only: the test's own httpx client logs the URL it requested.
    server = [rec.getMessage() for rec in caplog.records if "https://testserver/" not in rec.getMessage()]
    _assert_clean("\n".join(server), CANARY_QUERY)


# ---- access log query redaction ---------------------------------------------------------------
def test_access_log_filter_redacts_query_with_uvicorn_formatter():
    from uvicorn.logging import AccessFormatter

    install_access_log_redaction()
    install_access_log_redaction()  # idempotent
    logger = logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, AccessLogQueryRedactor) for f in logger.filters) == 1
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    handler = Capture()
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        args = ("127.0.0.1:5000", "GET", "/api/v1/health/live?access_token=" + CANARY_QUERY, "1.1", 200)
        logger.info('%s - "%s %s HTTP/%s" %d', *args)
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/assets/app.js", "1.1", 200)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    assert lines[0] == f'127.0.0.1:5000 - "GET /api/v1/health/live{REDACTED_QUERY} HTTP/1.1" 200 OK'
    assert lines[1] == '127.0.0.1:5000 - "GET /assets/app.js HTTP/1.1" 200 OK'


def test_uvicorn_error_traceback_is_reduced_to_exception_class():
    install_traceback_suppression()
    install_traceback_suppression()  # idempotent
    logger = logging.getLogger("uvicorn.error")
    assert sum(isinstance(f, TracebackSuppressor) for f in logger.filters) == 1
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    handler = Capture()
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        try:
            raise RuntimeError("params: password=" + CANARY_DB_PW)
        except RuntimeError as exc:
            # Exactly how uvicorn reports an exception that escaped the ASGI app.
            logger.error("Exception in ASGI application\n", exc_info=exc)
        logger.info("Started server process [%d]", 42)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    assert lines[0] == ("ERROR Exception in ASGI application error=RuntimeError "
                        "(traceback suppressed outside development)")
    assert lines[1] == "INFO Started server process [42]"
    _assert_clean("\n".join(lines))
    assert "Traceback" not in "\n".join(lines)


# ---- real uvicorn process: access log and startup failures ------------------------------------
def _child_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SECRET_KEYS and not k.startswith("TEST_")}
    env.update({"APP_ENV": "production", "PYTHONDONTWRITEBYTECODE": "1", "FRONTEND_DIST": str(BACKEND / "absent")})
    env.update(extra)
    return env


def _uvicorn(port: int, env: dict[str, str]) -> subprocess.Popen[str]:
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
           "--no-proxy-headers"]
    return subprocess.Popen(cmd, cwd=BACKEND, env=env, stdout=subprocess.PIPE,  # noqa: S603
                            stderr=subprocess.STDOUT, text=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_uvicorn_access_log_has_no_query_string():
    port = _free_port()
    proc = _uvicorn(port, _child_env())
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{base}/api/v1/health/live", timeout=1).read()  # noqa: S310
                break
            except OSError:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
        url = f"{base}/api/v1/health/live?access_token={CANARY_QUERY}&code={CANARY_KEY}"
        assert urllib.request.urlopen(url, timeout=3).status == 200  # noqa: S310
    finally:
        proc.terminate()
        out, _ = proc.communicate(timeout=10)
    assert f'"GET /api/v1/health/live{REDACTED_QUERY} HTTP/1.1" 200' in out
    _assert_clean(out, CANARY_QUERY)


@pytest.mark.parametrize("case", ["missing", "invalid"])
def test_uvicorn_refuses_to_start_on_bad_config_without_leaking(tmp_path, case):
    if case == "missing":
        cfg = tmp_path / "absent.env"
    else:
        cfg = _env_file(tmp_path, [*_valid_lines(), "APP_ENV=" + CANARY_KEY, "DB_POOL_SIZE=" + CANARY_DB_PW])
    proc = _uvicorn(_free_port(), _child_env(CONFIG_FILE=str(cfg)))
    out, _ = proc.communicate(timeout=30)
    assert proc.returncode != 0
    assert "Configuration error: CONFIG_FILE=" in out or "Configuration error: Invalid configuration" in out
    assert "Traceback" not in out
    _assert_clean(out)
