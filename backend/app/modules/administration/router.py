"""Health probes and read-only settings status (never returns secret values)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.config import APP_VERSION, get_settings
from app.core.deps import Ctx, get_ctx
from app.db.session import REQUIRED_SCHEMA_VERSION, check_database, get_engine
from app.modules.rewards.policy import POLICY_VERSION

router = APIRouter(tags=["administration"])

DEFERRED = ["admin_connections_write", "ai_assisted_rewards", "signup", "password_recovery",
            "guardian_management", "wallet_adjustments", "chore_exceptions"]


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> JSONResponse:
    settings = get_settings()
    checks: dict[str, str] = {}
    setup: list[str] = []
    diagnostics: dict[str, dict] = {}
    engine = None
    try:
        engine = get_engine()
    except Exception:  # noqa: BLE001 - malformed URL must not crash the probe
        checks["database"] = "invalid_configuration"
        setup.append("DATABASE_URL задан некорректно. Ожидается postgresql://… строка подключения Supabase.")
    if engine is None and "database" not in checks:
        checks["database"] = "not_configured"
        setup.append("Задайте DATABASE_URL (строка подключения Supabase PostgreSQL, sslmode=require).")
    if engine is not None:
        result = check_database(engine, settings.db_ready_timeout_seconds)
        checks["database"], checks["schema"] = result.database, result.schema
        if result.diagnostics:
            diagnostics["database"] = result.diagnostics  # class names / SQLSTATE / category only
        if result.database == "ok" and result.schema != "ok":
            setup.append(f"Примените миграции: python scripts/db_migrate.py --apply "
                         f"(нужна версия {REQUIRED_SCHEMA_VERSION}).")
        elif result.database == "timeout":
            setup.append("База данных не ответила вовремя: проверьте сеть/TLS до Supabase и нагрузку пула.")
        elif result.database == "unreachable":
            setup.append("База данных недоступна: проверьте сеть, TLS и учётные данные в DATABASE_URL.")
        elif result.database == "error":
            setup.append("Ошибка при проверке БД (см. diagnostics и журнал сервера): проверьте права и схему.")
    checks.setdefault("schema", "unknown")
    checks["auth"] = "configured" if settings.auth_configured else "not_configured"
    if not settings.auth_configured:
        setup.append("Задайте SUPABASE_URL и SUPABASE_PUBLISHABLE_KEY (publishable/anon ключ, не secret).")
    ok = checks["database"] == "ok" and checks["schema"] == "ok" and checks["auth"] == "configured"
    body: dict = {"status": "ready" if ok else "not_ready", "checks": checks, "setup": setup}
    if diagnostics:
        body["diagnostics"] = diagnostics
    return JSONResponse(body, status_code=200 if ok else 503)


@router.get("/settings")
def settings_status(ctx: Ctx = Depends(get_ctx)) -> dict:
    s = get_settings()
    return {
        "app": {"env": s.app_env, "version": APP_VERSION},
        "integrations": {
            "database": {"configured": s.database_configured},
            "supabase_auth": {"configured": s.auth_configured},
            "openai": {"configured": s.openai_api_key is not None},
        },
        "rewards": {"policy_version": POLICY_VERSION, "mode": "deterministic", "ai_available": False},
        "deferred": DEFERRED,
    }
