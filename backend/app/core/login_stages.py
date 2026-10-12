"""Value-free stage timing for POST /auth/login.

When login fails, the only signal is often the global DB handler's line, e.g. "database unavailable
method=POST route=/auth/login category=timeout". That line does not say WHICH part of the login was waiting.
Each stage logs `start` and then `ok` or `error`, with the request id and a monotonic elapsed time. A hang
therefore shows up as a `start` with no matching `ok`, and an error shows up with its stage.

Stages, in order: db_dependency (inside `get_db`, before engine creation and the cached schema check, so BEFORE
the handler body; only for endpoints marked with `time_db_dependency`), supabase_sign_in, jwt_verify,
ensure_profile, reward_evaluation (a failure is swallowed and logged as outcome=swallowed), response (me_dict +
cookies; me_dict can hit the DB after the reward rollback).

Inside ensure_profile, and ONLY when the login route passes `login_request_id` (every other caller of ensure_profile,
e.g. get_ctx for /me or /auth/logout, passes nothing and logs nothing), finer `ensure_profile.*` sub-stages are
logged around each DB operation (see ENSURE_PROFILE_STAGES and app.modules.accounts.provisioning). Per-activity
sub-stages carry `index=N`: the position in the fixed DEFAULT_ACTIVITIES table, never a code or name.

Logged values are limited to: the request id (validated by the HTTP middleware), a fixed stage name, the fixed
event/outcome vocabulary, elapsed milliseconds, exception CLASS names, ApiError status/code (fixed vocabulary,
validated again here), and the value-free DB description from app.db.errors (category, driver class, SQLSTATE).
Stage names come from the fixed STAGES table (anything else is logged as `unknown`); an index is a small
non-negative int (anything else is logged as `?`).
Never logged: email, password, tokens, cookies, user ids, display names, exception messages, SQL, DSN.

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
_MAX_INDEX = 999

# Sub-stages of ensure_profile, in the order a first login (new profile) logs them; the activity_* triple repeats
# once per DEFAULT_ACTIVITIES entry with index=0..N-1. Meaning of each: app.modules.accounts.provisioning.
ENSURE_PROFILE_STAGES: tuple[str, ...] = (
    "ensure_profile.profile_get",
    "ensure_profile.email_commit",  # existing profile whose email changed
    "ensure_profile.profile_add",
    "ensure_profile.profile_flush",
    "ensure_profile.activity_add",
    "ensure_profile.activity_flush",
    "ensure_profile.activity_children_add",
    "ensure_profile.wallet_world_add",
    "ensure_profile.final_flush",
    "ensure_profile.active_world_flush",
    "ensure_profile.commit",
    "ensure_profile.integrity_rollback",  # IntegrityError cleanup (concurrent first login)
    "ensure_profile.integrity_reread",
)
STAGES: frozenset[str] = frozenset({
    "db_dependency", "supabase_sign_in", "jwt_verify", "ensure_profile", "reward_evaluation", "response",
    *ENSURE_PROFILE_STAGES,
})


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
    ends with event=error outcome=swallowed instead of event=ok.

    `index` (optional) is a position in a fixed table (e.g. DEFAULT_ACTIVITIES) and is logged as `index=N`."""

    def __init__(self, request_id: str | None, stage: str, index: int | None = None) -> None:
        self.request_id = request_id
        self.stage = stage if stage in STAGES else "unknown"
        self.index = index
        where = f"stage={self.stage}"
        if index is not None:
            ok = type(index) is int and 0 <= index <= _MAX_INDEX
            where += f" index={index if ok else '?'}"
        self._where = where
        self._started = 0.0
        self._swallowed: BaseException | None = None

    def __enter__(self) -> LoginStage:
        self._started = time.monotonic()
        log.info("login_stage request_id=%s %s event=start", self.request_id, self._where)
        return self

    def swallowed(self, exc: BaseException) -> None:
        self._swallowed = exc

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> bool:
        elapsed_ms = (time.monotonic() - self._started) * 1000
        failure, outcome = (exc, "raised") if exc is not None else (self._swallowed, "swallowed")
        if failure is None:
            log.info("login_stage request_id=%s %s event=ok elapsed_ms=%.1f", self.request_id, self._where,
                     elapsed_ms)
        else:
            log.warning("login_stage request_id=%s %s event=error outcome=%s elapsed_ms=%.1f %s",
                        self.request_id, self._where, outcome, elapsed_ms, describe_failure(failure))
        return False  # never suppresses: exception handling stays with the caller


def optional_stage(request_id: str | None, stage: str, index: int | None = None) -> AbstractContextManager[object]:
    """LoginStage when a login request id is given, else a no-op (no log line, no timing, no behaviour change).

    Used inside shared code (ensure_profile) so only the login route, which passes its request id, is traced."""
    if not request_id:
        return nullcontext()
    return LoginStage(request_id, stage, index)


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
