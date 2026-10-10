"""Runtime configuration.

Values come from the process environment and, optionally, from the file named by CONFIG_FILE
(e.g. a 0600 read-only bind-mounted /data/config/app.env). No setting is required for the process to
start: unconfigured integrations are reported by /health/ready and produce 503 on data routes.

Fail closed on operator mistakes: if CONFIG_FILE is set but the file is missing, unreadable or yields
invalid values, get_settings() raises ConfigError instead of silently running without it. Its message
names only the path, the setting names and pydantic error types — never values, and never a chained
exception (`from None`), because both a ValidationError and a decode error can carry file content.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
APP_VERSION = "0.1.0"


class ConfigError(RuntimeError):
    """Unusable configuration. The message is safe to log: it never contains setting values."""


class Settings(BaseSettings):
    # hide_input_in_errors: a ValidationError must not echo the offending value (it may be a secret pasted
    # into the wrong key). Defence in depth: get_settings() also re-raises without the original error.
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "production"
    app_base_url: str | None = None

    database_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, ge=1, le=50)
    # None = same as db_pool_size (historical behaviour).
    db_max_overflow: int | None = Field(default=None, ge=0, le=50)
    db_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    db_pool_pre_ping: bool = True
    # Diagnostic only: open a fresh connection per checkout (no pooling). Pool settings are then ignored.
    db_null_pool: bool = False
    # libpq connect_timeout: bounds connection establishment per host attempt, NOT query duration.
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    # TCP keepalives detect a silently dead peer while the client waits for a reply.
    db_tcp_keepalives: bool = True
    db_tcp_keepalives_idle_seconds: int = Field(default=30, ge=1, le=7200)
    db_tcp_keepalives_interval_seconds: int = Field(default=10, ge=1, le=600)
    db_tcp_keepalives_count: int = Field(default=3, ge=1, le=30)
    # libpq tcp_user_timeout (Linux only; ignored elsewhere): max time sent data may stay unacknowledged.
    # 0 = operating-system default.
    db_tcp_user_timeout_ms: int = Field(default=30000, ge=0, le=600000)
    # Upper bound on how long GET /health/ready waits for its database check.
    db_ready_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120)

    supabase_url: str | None = None
    # Publishable (sb_publishable_…) or legacy anon key: sent as `apikey` to Supabase Auth REST.
    supabase_publishable_key: SecretStr | None = None
    # Optional legacy HS256 JWT secret. Projects on asymmetric signing keys use JWKS instead.
    supabase_jwt_secret: SecretStr | None = None
    supabase_jwt_audience: str = "authenticated"

    openai_api_key: SecretStr | None = None
    openai_model: str | None = None

    cookie_secure: bool = True
    frontend_dist: str = "../frontend/dist"

    login_rate_limit: int = Field(default=10, ge=1)
    login_rate_window_seconds: int = Field(default=300, ge=10)

    @field_validator("supabase_url", "app_base_url")
    @classmethod
    def _strip_slash(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return v.strip().rstrip("/")

    @field_validator("db_max_overflow", mode="before")
    @classmethod
    def _empty_int_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("database_url", "supabase_publishable_key", "supabase_jwt_secret", "openai_api_key")
    @classmethod
    def _empty_secret_is_none(cls, v: SecretStr | None) -> SecretStr | None:
        if v is None or not v.get_secret_value().strip():
            return None
        return v

    # ---- derived -------------------------------------------------------------------------
    @property
    def secure_cookies(self) -> bool:
        # Insecure cookies are only possible in explicit development mode.
        return self.cookie_secure or self.app_env != "development"

    @property
    def database_configured(self) -> bool:
        return self.database_url is not None

    @property
    def auth_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key)

    def missing_settings(self) -> list[str]:
        missing = []
        if not self.database_configured:
            missing.append("DATABASE_URL")
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        if not self.supabase_publishable_key:
            missing.append("SUPABASE_PUBLISHABLE_KEY")
        return missing

    @property
    def sqlalchemy_url(self) -> str | None:
        if self.database_url is None:
            return None
        url = self.database_url.get_secret_value()
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def frontend_dist_path(self) -> Path:
        p = Path(self.frontend_dist)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


def _check_config_file(path: Path) -> None:
    if not path.exists():
        raise ConfigError(f"CONFIG_FILE={path} does not exist. Create it from the template or unset CONFIG_FILE.")
    if not path.is_file():
        raise ConfigError(f"CONFIG_FILE={path} is not a regular file.")
    try:
        with path.open("rb"):
            pass
    except OSError as exc:
        raise ConfigError(f"CONFIG_FILE={path} is not readable by uid {getattr(os, 'getuid', lambda: '?')()} "
                          f"({type(exc).__name__}). Check owner/mode/ACL of the host file.") from None


def load_settings() -> Settings:
    """Build Settings from the environment and the optional CONFIG_FILE; raise ConfigError on misuse."""
    raw = os.environ.get("CONFIG_FILE", "").strip()
    source = "environment"
    kwargs: dict[str, object] = {}
    if raw:
        path = Path(raw)
        _check_config_file(path)
        kwargs["_env_file"] = path
        kwargs["_env_file_encoding"] = "utf-8"
        source = f"environment / CONFIG_FILE={path}"
    try:
        return Settings(**kwargs)  # type: ignore[arg-type]
    except ValidationError as exc:
        problems = sorted({f"{'.'.join(str(p) for p in e.get('loc', ())).upper() or '?'} ({e.get('type', 'invalid')})"
                           for e in exc.errors(include_input=False, include_url=False, include_context=False)})
        raise ConfigError(f"Invalid configuration in {source}: {', '.join(problems)}. "
                          "Values are not shown.") from None
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"Cannot read configuration from {source} ({type(exc).__name__}). "
                          "The file must be UTF-8 text in KEY=value format.") from None
    except Exception as exc:  # noqa: BLE001 - e.g. pydantic-settings SettingsError; its text may hold values
        raise ConfigError(f"Cannot load configuration from {source} ({type(exc).__name__}). "
                          "Values are not shown.") from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
