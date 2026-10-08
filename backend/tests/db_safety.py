"""Fail-closed guard for the destructive PostgreSQL test mode.

The Postgres test run executes `DROP SCHEMA public CASCADE`. It is allowed only when ALL hold,
checked purely from the URL/environment **before any connection is opened**:

  * TFE_ALLOW_DESTRUCTIVE_TEST_DB=1 (explicit opt-in, exact value "1")
  * scheme postgresql:// (or postgres://, postgresql+psycopg://)
  * host is loopback: localhost, 127.0.0.1 or ::1 (no remote hosts, no Supabase, no pooler)
  * database name is `tfe_test` or `tfe_test_<lowercase suffix>`
  * no `host=` / `hostaddr=` / `service=` query overrides that could redirect the connection
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import parse_qs, unquote, urlsplit

OPT_IN_ENV = "TFE_ALLOW_DESTRUCTIVE_TEST_DB"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
DB_NAME_RE = re.compile(r"^tfe_test(_[a-z0-9_]{1,40})?$")
FORBIDDEN_QUERY_KEYS = {"host", "hostaddr", "service", "dbname", "port"}


class UnsafeTestDatabase(Exception):
    pass


def validate_test_database_url(url: str, env: Mapping[str, str]) -> None:
    if env.get(OPT_IN_ENV) != "1":
        raise UnsafeTestDatabase(
            f"TEST_DATABASE_URL is set but {OPT_IN_ENV}=1 is missing. The Postgres test run DROPS schema "
            "public; opt in explicitly and only for a disposable local database.")
    parts = urlsplit(url)
    if parts.scheme not in ("postgresql", "postgres", "postgresql+psycopg"):
        raise UnsafeTestDatabase("TEST_DATABASE_URL must be a postgresql:// URL.")
    if "," in parts.netloc:
        raise UnsafeTestDatabase("Multi-host TEST_DATABASE_URL is not allowed.")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise UnsafeTestDatabase(f"TEST_DATABASE_URL host {host or '<empty>'!r} is not loopback "
                                 f"({', '.join(sorted(LOOPBACK_HOSTS))}).")
    if "supabase" in url.lower():
        raise UnsafeTestDatabase("TEST_DATABASE_URL must never point at Supabase.")
    query = {k.lower() for k in parse_qs(parts.query, keep_blank_values=True)}
    if query & FORBIDDEN_QUERY_KEYS:
        raise UnsafeTestDatabase(f"TEST_DATABASE_URL query must not override {sorted(query & FORBIDDEN_QUERY_KEYS)}.")
    dbname = unquote(parts.path.lstrip("/"))
    if not DB_NAME_RE.match(dbname):
        raise UnsafeTestDatabase(f"Test database name {dbname!r} must be 'tfe_test' or 'tfe_test_<suffix>'.")
