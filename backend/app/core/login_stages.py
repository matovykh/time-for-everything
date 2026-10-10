"""Value-free stage timing for POST /auth/login.

When login fails, the only signal is often the global DB handler's line, e.g. "database unavailable
method=POST route=/auth/login category=timeout". That line does not say WHICH part of the login was waiting.
Each stage logs `start` and then `ok` or `error`, with the request id and a monotonic elapsed time. A hang
therefore shows up as a `start` with no matching `ok`, and an error shows up with its stage.

Stages, in order: db_dependency (inside `get_db`, before engine creation and the cached schema check, so BEFORE
the handler body; only for endpoints marked with `time_db_dependency`), supabase_sign_in, jwt_verify,
ensure_profile, reward_evaluation (a failure is swallowed and logged as outcome=swallowed), response (me_dict +
cookies; me_dict can hit the DB after the reward rollback).

Logged values are limited to: the request id (validated by the HTTP middleware), a fixed stage name, the fixed
event/outcome vocabulary, elapsed milliseconds, exception CLASS names, ApiError status/code (fixed vocabulary,
validated again here), and the value-free DB description from app.db.errors (category, driver class, SQLSTATE).
Never logged: email, password, tokens, cookies, exception messages, SQL, DSN.

Lives in app.core (not app.modules.accounts) because app.db.session imports it.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from types import TracebackType

from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from app.core.errors import ApiError, request_id_of
from app.db.errors import describe_db_error

log = logging.getLogger("app.auth.login")

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DB_STAGE_ATTR = "_login_stage_db_dependency"


def describe_failure(exc: BaseException) -> str:
    """`key=value` pairs that describe an exception without its message."""
    fields: dict[str, object] = {"error": type(exc).__name__}
    if isinstance(exc, ApiError):
        fields["status"] = exc.status
        fields["code"] = exc.code if isinstance(exc.code, str) and _SAFE_CODE.match(exc.code) else "?"
    cause = exc.__cause__
    if cause is not None:
        fields["cause"] = type(cause).__name__
    db_exc = exc if isinstance(exc, SQLAlchemyError) else cause if isinstance(cause, SQLAlchemyError) else None
    if db_exc is not None:
        info = describe_db_error(db_exc)
        fields.update(category=info["category"], driver_error=info["driver_error"], sqlstate=info["sqlstate"])
    return " ".join(f"{k}={v}" for k, v in fields.items())


class LoginStage:
    """`with LoginStage(rid, "ensure_profile"):` logs start, then ok or error (outcome=raised).

    For a failure the caller handles and does not re-raise, call `swallowed(exc)` inside the block. The block then
    ends with event=error outcome=swallowed instead of event=ok."""

    def __init__(self, request_id: str | None, stage: str) -> None:
        self.request_id = request_id
        self.stage = stage
        self._started = 0.0
        self._swallowed: BaseException | None = None

    def __enter__(self) -> LoginStage:
        self._started = time.monotonic()
        log.info("login_stage request_id=%s stage=%s event=start", self.request_id, self.stage)
        return self

    def swallowed(self, exc: BaseException) -> None:
        self._swallowed = exc

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> bool:
        elapsed_ms = (time.monotonic() - self._started) * 1000
        failure, outcome = (exc, "raised") if exc is not None else (self._swallowed, "swallowed")
        if failure is None:
            log.info("login_stage request_id=%s stage=%s event=ok elapsed_ms=%.1f", self.request_id, self.stage,
                     elapsed_ms)
        else:
            log.warning("login_stage request_id=%s stage=%s event=error outcome=%s elapsed_ms=%.1f %s",
                        self.request_id, self.stage, outcome, elapsed_ms, describe_failure(failure))
        return False  # never suppresses: exception handling stays with the caller


def time_db_dependency[F: Callable[..., object]](endpoint: F) -> F:
    """Mark a route endpoint so `get_db` times its own acquisition as the db_dependency stage.

    Apply BELOW the router decorator so the marked function is the one FastAPI registers."""
    setattr(endpoint, _DB_STAGE_ATTR, True)
    return endpoint


def db_dependency_stage(request: Request) -> AbstractContextManager[object]:
    """LoginStage for marked endpoints (Starlette puts the matched endpoint in scope), else a no-op."""
    if getattr(request.scope.get("endpoint"), _DB_STAGE_ATTR, False):
        return LoginStage(request_id_of(request), "db_dependency")
    return nullcontext()
