"""ASGI entrypoint: `uvicorn app.main:app` (cwd = backend/).

Serves `/api/v1` and, if present, the built SPA from FRONTEND_DIST (default ../frontend/dist):
existing files are returned as-is; other non-API GET paths fall back to index.html.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from app.core.config import APP_VERSION, ConfigError, get_settings
from app.core.errors import ApiError, error_body, install_error_handlers
from app.core.log_redaction import install_access_log_redaction, install_traceback_suppression
from app.core.security import install_http_middleware
from app.modules.accounts.router import router as accounts_router
from app.modules.activities.router import router as activities_router
from app.modules.administration.router import router as admin_router
from app.modules.analytics.router import router as analytics_router
from app.modules.chores.router import router as chores_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.entries.router import router as entries_router
from app.modules.rewards.router import router as rewards_router
from app.modules.timers.router import router as timers_router
from app.modules.world.router import router as world_router

API_PREFIX = "/api/v1"


def _spa_routes(app: FastAPI) -> None:
    @app.api_route("/api/{rest:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
                   include_in_schema=False)
    def api_not_found(rest: str) -> Response:
        raise ApiError(404, "not_found", "Не найдено.")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(full_path: str, request: Request) -> Response:
        if full_path == "api" or full_path.startswith("api/"):
            raise ApiError(404, "not_found", "Не найдено.")
        dist = get_settings().frontend_dist_path
        index = dist / "index.html"
        if not index.is_file():
            return JSONResponse(
                error_body(getattr(request.state, "request_id", None), "frontend_not_built",
                           "Сборка интерфейса не найдена. Соберите frontend или задайте FRONTEND_DIST."),
                status_code=404,
            )
        if full_path:
            candidate = (dist / full_path).resolve()
            if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
                headers = {}
                if Path(full_path).parts[:1] == ("assets",):
                    headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    install_access_log_redaction()
    try:
        settings = get_settings()
    except ConfigError as exc:
        # Exit without a traceback: the message is value-free by construction (see core/config.py), and
        # SystemExit(str) is printed by the interpreter as one line instead of a stack dump.
        raise SystemExit(f"Configuration error: {exc}") from None
    if settings.app_env != "development":
        install_traceback_suppression()
    docs = settings.app_env != "production"
    app = FastAPI(
        title="Всё успею API",
        version=APP_VERSION,
        openapi_url=f"{API_PREFIX}/openapi.json" if docs else None,
        docs_url=f"{API_PREFIX}/docs" if docs else None,
        redoc_url=None,
    )
    install_error_handlers(app)
    install_http_middleware(app)
    api = APIRouter(prefix=API_PREFIX)
    for r in (admin_router, accounts_router, activities_router, timers_router, entries_router, chores_router,
              analytics_router, dashboard_router, rewards_router, world_router):
        api.include_router(r)
    app.include_router(api)
    _spa_routes(app)
    return app


app = create_app()
