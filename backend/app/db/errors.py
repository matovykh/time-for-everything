"""Safe classification of database errors.

Driver messages can contain host names, user names, SQL text and bound parameters (personal data),
so nothing here ever returns or logs `str(exc)`. Messages are only *inspected* for a few well-known
substrings when the driver provides no SQLSTATE (e.g. libpq connection-level failures such as
"consuming input failed: SSL SYSCALL error: Operation timed out"). What leaves this module is limited
to exception class names, a validated 5-character SQLSTATE and a fixed category vocabulary.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import exc as sa_exc

log = logging.getLogger("app.db")

UNDEFINED_TABLE = "42P01"
_SQLSTATE_RE = re.compile(r"^[0-9A-Z]{5}$")

# Categories meaning "the database cannot be used right now" (as opposed to a bug or a schema problem).
UNAVAILABLE_CATEGORIES = frozenset({
    "timeout", "connection", "pool_timeout", "too_many_connections", "server_shutdown", "dns",
    "authentication", "query_canceled",
})

_TEXT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("authentication", ("password authentication failed", "authentication failed", "no password supplied")),
    ("too_many_connections", ("too many connections", "max client connections", "remaining connection slots")),
    ("dns", ("could not translate host name", "name or service not known", "nodename nor servname",
             "temporary failure in name resolution")),
    ("timeout", ("timed out", "timeout expired", "timeout")),
)


def _orig(exc: BaseException) -> BaseException | None:
    return exc.orig if isinstance(exc, sa_exc.DBAPIError) else None  # type: ignore[return-value]


def db_error_sqlstate(exc: BaseException) -> str | None:
    """SQLSTATE of the underlying driver error (psycopg `.sqlstate`, psycopg2 `.pgcode`), if valid."""
    orig = _orig(exc) or exc
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code if isinstance(code, str) and _SQLSTATE_RE.match(code) else None


def is_undefined_table(exc: BaseException) -> bool:
    """True only for "relation does not exist" (PostgreSQL 42P01) / SQLite "no such table"."""
    if not isinstance(exc, sa_exc.DBAPIError):
        return False
    if db_error_sqlstate(exc) == UNDEFINED_TABLE:
        return True
    orig = exc.orig
    # SQLite has no SQLSTATE; used by the test suite and local experiments.
    return type(orig).__module__ == "sqlite3" and str(orig).startswith("no such table")


def classify_db_error(exc: BaseException) -> str:
    if isinstance(exc, sa_exc.TimeoutError):  # QueuePool: no free connection within pool_timeout
        return "pool_timeout"
    if is_undefined_table(exc):
        return "undefined_table"
    state = db_error_sqlstate(exc)
    if state:
        if state.startswith("28"):
            return "authentication"
        if state == "53300":
            return "too_many_connections"
        if state == "57014":
            return "query_canceled"  # statement_timeout or explicit cancel
        if state.startswith("57P"):
            return "server_shutdown"
        if state.startswith("08"):
            return "connection"
        if state == "42501":
            return "permission_denied"
        if state.startswith("42"):
            return "schema_error"
        return "database_error"
    orig = _orig(exc)
    if orig is not None and type(orig).__module__ == "sqlite3":  # tests/local only: no network involved
        return "timeout" if "database is locked" in str(orig) else "database_error"
    if isinstance(exc, (sa_exc.OperationalError, sa_exc.InterfaceError)) or (
        isinstance(exc, sa_exc.DBAPIError) and exc.connection_invalidated
    ):
        text = str(_orig(exc) or "").lower()  # inspected only; never returned or logged
        for category, needles in _TEXT_RULES:
            if any(n in text for n in needles):
                return category
        return "connection"
    return "database_error"


def is_unavailable_error(exc: BaseException) -> bool:
    """The database could not be reached/used: worth a 503 'try later' rather than a 500."""
    if isinstance(exc, sa_exc.TimeoutError):
        return True
    if isinstance(exc, (sa_exc.OperationalError, sa_exc.InterfaceError)):
        return True
    if isinstance(exc, sa_exc.DBAPIError) and exc.connection_invalidated:
        return True
    return classify_db_error(exc) in UNAVAILABLE_CATEGORIES


def describe_db_error(exc: BaseException) -> dict[str, Any]:
    """Value-free description, safe for logs and API diagnostics."""
    orig = _orig(exc)
    return {
        "category": classify_db_error(exc),
        "error": type(exc).__name__,
        "driver_error": type(orig).__name__ if orig is not None else None,
        "sqlstate": db_error_sqlstate(exc),
    }


def log_db_error(event: str, exc: BaseException, *, request_id: str | None = None,
                 level: int = logging.WARNING) -> dict[str, Any]:
    info = describe_db_error(exc)
    log.log(level, "%s category=%s error=%s driver_error=%s sqlstate=%s request_id=%s", event, info["category"],
            info["error"], info["driver_error"], info["sqlstate"], request_id)
    return info
