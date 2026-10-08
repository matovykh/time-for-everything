"""Health/setup behaviour, SPA serving, DB scripts and SQL ⇄ code consistency."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db import session as db_session
from app.main import app
from app.modules.rewards.policy import PARAMETERS
from app.modules.world.catalog import THEMES, UPGRADES

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = sorted((REPO / "supabase" / "migrations").glob("*.sql"))
MIGRATION = MIGRATIONS[-1]  # latest
INIT = MIGRATIONS[0]  # reference seed lives here
ALL_SQL = "\n".join(m.read_text() for m in MIGRATIONS)


def load_script(name: str):
    sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- health & unconfigured start ---------------------------------------------------------------
def test_unconfigured_process_starts_with_setup_guidance():
    db_session.configure_engine(None)
    c = TestClient(app, base_url="https://testserver")
    assert c.get("/api/v1/health/live").json() == {"status": "ok"}
    r = c.get("/api/v1/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["database"] == "not_configured"
    assert any("DATABASE_URL" in s for s in r.json()["setup"])
    c.headers["X-Test-User"] = "00000000-0000-0000-0000-000000000001"
    from app.core.deps import get_principal
    from tests.conftest import _test_principal

    app.dependency_overrides[get_principal] = _test_principal
    r = c.get("/api/v1/activities")
    assert r.status_code == 503 and r.json()["code"] == "service_not_configured"


def test_ready_reports_missing_schema(tmp_path):
    from sqlalchemy import create_engine

    db_session.configure_engine(create_engine(f"sqlite:///{tmp_path / 'empty.db'}"))
    try:
        r = TestClient(app).get("/api/v1/health/ready").json()
        assert r["checks"]["database"] == "ok" and r["checks"]["schema"] == "missing"
    finally:
        db_session.configure_engine(None)


def test_ready_when_everything_configured(engine, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://abcdefghijklmnopqrst.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_x")
    get_settings.cache_clear()
    r = TestClient(app).get("/api/v1/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def test_required_schema_version_matches_latest_migration():
    assert MIGRATION.name.startswith(db_session.REQUIRED_SCHEMA_VERSION)
    assert f"values ('{db_session.REQUIRED_SCHEMA_VERSION}')" in MIGRATION.read_text()


# ---- SPA ------------------------------------------------------------------------------------
def test_spa_serving(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    monkeypatch.setenv("FRONTEND_DIST", str(dist))
    get_settings.cache_clear()
    c = TestClient(app)
    assert c.get("/").text == "<html>spa</html>"
    assert c.get("/world/settlers").text == "<html>spa</html>"  # client-side route fallback
    r = c.get("/assets/app.js")
    assert r.text == "console.log(1)" and "immutable" in r.headers["cache-control"]
    assert "nope" not in c.get("/assets/../../secret.txt").text
    assert "nope" not in c.get("/%2e%2e/secret.txt").text
    api = c.get("/api/v1/does-not-exist")
    assert api.status_code == 404 and api.json()["code"] == "not_found"
    assert c.get("/api").json()["code"] == "not_found"
    assert c.get("/api/v1/health/live").headers["x-content-type-options"] == "nosniff"


def test_relative_frontend_dist_resolves_from_backend_dir(monkeypatch):
    monkeypatch.setenv("FRONTEND_DIST", "../frontend/dist")
    get_settings.cache_clear()
    assert get_settings().frontend_dist_path == (REPO / "frontend" / "dist").resolve()


# ---- SQL seed ⇄ code ------------------------------------------------------------------------
def test_sql_seed_matches_world_registry_and_policy():
    sql = INIT.read_text()
    themes = re.findall(r"\('(\w+)',\s+'([^']+)',\s+(\d)\)", sql)
    assert [(c, n) for c, n, _ in themes] == [(t.code, t.name) for t in THEMES]
    upgrades = re.findall(r"\('(\w+)',\s+(\d),\s+(\d+),\s+(null|'\w+')\)", sql)
    assert [(c, int(p), int(cost), None if r == "null" else r.strip("'")) for c, p, cost, r in upgrades] == [
        (u.code, i, u.cost, u.requires) for i, u in enumerate(UPGRADES)]
    params = json.loads(re.search(r"values \(1, '(\{.*?\})'::jsonb", sql, re.S).group(1))
    assert params == PARAMETERS


def test_prototype_world_registry_matches():
    proto = (REPO / "prototype" / "worlds.js").read_text()
    for t in THEMES:
        assert f'id: "{t.code}"' in proto and f'name: "{t.name}"' in proto
        for title in t.titles:
            assert f'"{title}"' in proto
    for u in UPGRADES:
        assert re.search(rf'id: "{u.code}",\s+cost: {u.cost},', proto)


def test_orm_tables_exist_in_migration():
    from app.db.models import Base

    sql = ALL_SQL
    for table in Base.metadata.tables.values():
        assert f"create table public.{table.name} " in sql or f"public.{table.name} (" in sql, table.name
        for col in table.columns:
            assert re.search(rf"\n\s+{col.name}\s", sql), f"{table.name}.{col.name}"


def test_migration_never_alters_managed_schemas():
    sql = ALL_SQL.lower()
    code = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    assert not re.search(r"(create|alter|drop|insert into|update|delete from|truncate)\s+(table\s+)?(auth|storage)\.",
                         code)
    assert "references auth.users" in code  # only a reference


# ---- scripts --------------------------------------------------------------------------------
def test_reset_dry_run_and_guards(monkeypatch, capsys):
    reset = load_script("db_reset")
    url = "postgresql://postgres:pw@db.abcdefghijklmnopqrst.supabase.co:5432/postgres"
    monkeypatch.setattr(reset, "connect", lambda *_a: pytest.fail("must not connect"))
    monkeypatch.delenv("APP_ENV", raising=False)
    assert reset.main(["--database-url", url]) == 0  # dry run
    out = capsys.readouterr().out
    assert "ref=abcdefghijklmnopqrst" in out and "drop table if exists public.wallet_transactions;" in out
    assert reset.main(["--database-url", url, "--reset"]) == 2
    assert reset.main(["--database-url", url, "--reset", "--confirm-project-ref=wrongwrongwrongwrong"]) == 2
    assert reset.main(["--database-url", url, "--reset", "--confirm-project-ref=abcdefghijklmnopqrst"]) == 2
    assert "--allow-production" in capsys.readouterr().err
    answers = iter(["no"])
    assert reset.main(["--database-url", url, "--reset", "--confirm-project-ref=abcdefghijklmnopqrst",
                       "--allow-production"], input_fn=lambda _p: next(answers)) == 3


def test_reset_statements_only_touch_public_app_objects():
    tool = load_script("_dbtool")
    stmts = tool.drop_statements()
    assert all(s.startswith(("drop table if exists public.", "drop function if exists public.")) for s in stmts)
    assert not any("cascade" in s for s in stmts)
    with pytest.raises(SystemExit):
        tool.assert_only_public(["drop table if exists auth.users;"])
    with pytest.raises(SystemExit):
        tool.assert_only_public(["drop schema storage;"])
    from app.db.models import Base

    assert set(tool.APP_TABLES) == set(Base.metadata.tables)  # nothing forgotten, nothing foreign


def test_pooler_url_project_ref():
    tool = load_script("_dbtool")
    t = tool.parse_target("postgresql://postgres.abcdefghijklmnopqrst:pw@aws-0-eu-central-1.pooler.supabase.com:6543/postgres")
    assert t.is_supabase and t.project_ref == "abcdefghijklmnopqrst" and t.port == 6543
    local = tool.parse_target("postgresql://u:p@localhost:5433/app")
    assert not local.is_supabase and local.project_ref == "localhost"


def test_migrate_offline_lists_files(capsys):
    migrate = load_script("db_migrate")
    assert migrate.main(["--offline"]) == 0
    assert MIGRATION.name in capsys.readouterr().out
