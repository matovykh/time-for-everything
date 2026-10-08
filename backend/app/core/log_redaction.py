"""Narrow log hygiene for the two uvicorn loggers the app does not control.

1. `uvicorn.access` logs `client - "METHOD /path?query HTTP/1.1" status`. A query string can carry tokens
   or codes (a mistyped link, an auth redirect, a probe), and access logs are typically shipped and kept
   longer than the request. The app never needs secrets in a URL, so the query is replaced wholesale.
   The PATH is not redacted (a client can put anything into it); production compose therefore runs
   uvicorn with --no-access-log, and this filter only protects other launch modes (dev, plain docker run).

2. `uvicorn.error` logs "Exception in ASGI application" with the full traceback when an exception escapes
   Starlette's ServerErrorMiddleware (rare: the app's own middleware already converts route errors into a
   500 that logs only the exception class). A traceback includes the exception message, which may embed
   SQL parameters or other request data. Outside APP_ENV=development the traceback is dropped and only
   the exception class name is kept.

This is deliberately not a general redaction system: other loggers (asyncio, third-party libraries) are
not filtered. See docs/SECRETS.md, "Ограничения".
"""

from __future__ import annotations

import logging

ACCESS_LOGGER = "uvicorn.access"
ERROR_LOGGER = "uvicorn.error"
REDACTED_QUERY = "?[query-redacted]"


def redact_query(path: str) -> str:
    head, sep, _query = path.partition("?")
    return head + REDACTED_QUERY if sep else path


class AccessLogQueryRedactor(logging.Filter):
    """Mutates record.args, so it works with uvicorn's AccessFormatter and the default message shape."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            record.args = (*args[:2], redact_query(args[2]), *args[3:])
        return True


class TracebackSuppressor(logging.Filter):
    """Replace exc_info/stack with the exception class name; the record itself is still emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info or record.exc_text or record.stack_info:
            exc_type = record.exc_info[0] if record.exc_info else None
            name = exc_type.__name__ if exc_type is not None else "unknown"
            try:
                text = record.getMessage().rstrip()
            except Exception:  # noqa: BLE001 - a malformed record must not break logging
                text = str(record.msg).rstrip()
            record.msg = f"{text} error={name} (traceback suppressed outside development)"
            record.args = None
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def _add_once(logger_name: str, flt: type[logging.Filter]) -> None:
    logger = logging.getLogger(logger_name)
    if not any(isinstance(f, flt) for f in logger.filters):
        logger.addFilter(flt())


def install_access_log_redaction() -> None:
    """Idempotent; called from create_app(), i.e. after uvicorn applied its logging config."""
    _add_once(ACCESS_LOGGER, AccessLogQueryRedactor)


def install_traceback_suppression() -> None:
    """Idempotent; create_app() calls it unless APP_ENV=development."""
    _add_once(ERROR_LOGGER, TracebackSuppressor)
