"""Uniform error envelope: {code, message, field_errors, request_id, details}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db.errors import is_unavailable_error, log_db_error

log = logging.getLogger("app.errors")


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        field_errors: list[dict[str, str]] | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field_errors = field_errors or []
        self.details = details
        self.headers = headers


def not_found(message: str = "Не найдено.") -> ApiError:
    return ApiError(404, "not_found", message)


def forbidden(message: str = "Недостаточно прав.") -> ApiError:
    return ApiError(403, "forbidden", message)


def validation(code: str, message: str, field: str | None = None) -> ApiError:
    fe = [{"field": field, "code": code, "message": message}] if field else []
    return ApiError(422, code, message, field_errors=fe)


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_body(
    request_id: str | None,
    code: str,
    message: str,
    field_errors: list[dict[str, str]] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "field_errors": field_errors or [],
        "request_id": request_id,
        "details": details,
    }


def error_response(request: Request, err: ApiError) -> JSONResponse:
    return JSONResponse(
        error_body(request_id_of(request), err.code, err.message, err.field_errors, err.details),
        status_code=err.status,
        headers=err.headers,
    )


_HTTP_CODES = {
    400: ("bad_request", "Некорректный запрос."),
    401: ("not_authenticated", "Нужно войти."),
    403: ("forbidden", "Недостаточно прав."),
    404: ("not_found", "Не найдено."),
    405: ("method_not_allowed", "Метод не поддерживается."),
    413: ("payload_too_large", "Слишком большой запрос."),
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for e in exc.errors():
            loc = [str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path", "header")]
            fields.append({"field": ".".join(loc) or "body", "code": e.get("type", "invalid"),
                           "message": e.get("msg", "invalid")})
        return JSONResponse(
            error_body(request_id_of(request), "validation_error", "Проверьте введённые данные.", fields),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_CODES.get(exc.status_code, ("error", "Ошибка запроса."))
        return JSONResponse(error_body(request_id_of(request), code, message), status_code=exc.status_code)

    @app.exception_handler(SQLAlchemyError)
    async def _database(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        route = getattr(request.scope.get("route"), "path", "?")
        if is_unavailable_error(exc):
            # Connectivity/timeout/pool exhaustion: transient, retryable. Value-free log line only.
            info = log_db_error(f"database unavailable method={request.method} route={route}", exc,
                                request_id=request_id_of(request))
            return JSONResponse(
                error_body(request_id_of(request), "database_unavailable",
                           "База данных временно недоступна. Попробуйте позже.",
                           details={"reason": info["category"]}),
                status_code=503, headers={"Retry-After": "5"},
            )
        return await _unhandled(request, exc)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Deliberately no traceback or exception message: DB errors can embed SQL parameters
        # (names, notes, emails). Correlate via request_id; the route template carries no user data.
        route = request.scope.get("route")
        log.error("unhandled error request_id=%s method=%s route=%s error=%s", request_id_of(request),
                  request.method, getattr(route, "path", "?"), type(exc).__name__)
        return JSONResponse(
            error_body(request_id_of(request), "internal_error", "Внутренняя ошибка. Попробуйте позже."),
            status_code=500,
        )
