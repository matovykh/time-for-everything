"""QA black-box security sweeps driven by the live route table (new routes are covered automatically).

IDs refer to docs/MVP-QA.md §2. Real cookie/JWT path, no principal override.
"""

from __future__ import annotations

import logging
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from conftest import CANARY_JWT_SECRET, CANARY_OPENAI, CANARY_PUBLISHABLE, mint

PUBLIC = {("GET", "/api/v1/health/live"), ("GET", "/api/v1/health/ready"), ("GET", "/api/v1/auth/csrf"),
          ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/logout"), ("POST", "/api/v1/auth/refresh")}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def api_routes():
    """From the generated OpenAPI document (FastAPI ≥0.14x nests included routers lazily)."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/api/v1"):
            out.extend((m.upper(), path) for m in ops if m.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"})
    return sorted(out)


def fill(path: str, value: str = None) -> str:
    def sub(m):
        name = m.group(1)
        if "date" in name:
            return "2026-10-06"
        if name == "cmd":
            return "start"
        if name == "theme_code":
            return "settlers"
        if name == "category":
            return "walk"
        return value or str(uuid.uuid4())
    return re.sub(r"\{(\w+)\}", sub, path)


def test_route_table_is_nonempty():
    assert len(api_routes()) >= 30


@pytest.mark.parametrize("method,path", [r for r in api_routes() if r not in PUBLIC])
def test_sec01_every_private_route_requires_session(engine, method, path):
    c = TestClient(app, base_url="https://testserver")
    token = c.get("/api/v1/auth/csrf").json()["csrf_token"]
    r = c.request(method, fill(path), headers={"X-CSRF-Token": token, "Idempotency-Key": uuid.uuid4().hex},
                  json={} if method in UNSAFE else None)
    assert r.status_code == 401, (method, path, r.status_code, r.text[:200])


@pytest.mark.parametrize("method,path", [r for r in api_routes() if r[0] in UNSAFE])
def test_sec02_every_unsafe_route_requires_csrf(child, method, path):
    child.client.headers.pop("X-CSRF-Token")
    r = child.request(method, fill(path), json={}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 403 and r.json()["code"] == "csrf_failed", (method, path, r.status_code)
    # wrong token and foreign origin
    r = child.request(method, fill(path), json={}, headers={"X-CSRF-Token": "x" * 43})
    assert r.status_code == 403
    r = child.request(method, fill(path), json={},
                      headers={"X-CSRF-Token": child.csrf, "Origin": "https://evil.example"})
    assert r.status_code == 403, (method, path, "foreign Origin accepted")


def test_sec03_copied_access_cookie_dead_after_logout_but_other_session_alive(make_api, fake_supabase):
    a = make_api()
    act = a.activity("math")["id"]
    copied = a.access
    # second device of the same user = different Supabase session
    other = TestClient(app, base_url="https://testserver")
    other.cookies.set("tfe_at", mint(a.user_id, session_id=str(uuid.uuid4())))
    assert other.get("/api/v1/me").status_code == 200
    assert a.post("/api/v1/auth/logout").status_code == 204
    attacker = TestClient(app, base_url="https://testserver")
    csrf = attacker.get("/api/v1/auth/csrf").json()["csrf_token"]
    attacker.cookies.set("tfe_at", copied)
    for method, path in [("GET", "/api/v1/me"), ("GET", "/api/v1/wallet"), ("GET", f"/api/v1/activities/{act}/entries"),
                         ("POST", f"/api/v1/activities/{act}/timer/start")]:
        r = attacker.request(method, path, headers={"X-CSRF-Token": csrf, "Idempotency-Key": uuid.uuid4().hex},
                             json={"revision": 0} if method == "POST" else None)
        assert r.status_code == 401, (method, path, r.status_code)
    assert other.get("/api/v1/me").status_code == 200  # scope=local: other device unaffected


def test_sec03_logout_cookies_cleared_and_flags(make_api, fake_supabase):
    a = make_api()
    r = a.post("/api/v1/auth/logout")
    sc = r.headers.get_list("set-cookie")
    for name in ("tfe_at", "tfe_rt", "tfe_csrf"):
        line = next(s for s in sc if s.startswith(name + "="))
        assert "Max-Age=0" in line or "expires=Thu, 01 Jan 1970" in line.lower() or 'Max-Age="0"' in line, line
        assert "Secure" in line


def test_sec04_sec05_canaries_never_in_any_get_response_or_log(make_api, caplog):
    a = make_api()
    act = a.activity("math")["id"]
    caplog.set_level(logging.DEBUG)
    bodies = []
    for method, path in api_routes():
        if method != "GET":
            continue
        r = a.get(fill(path, act))
        bodies.append(r.text + "".join(f"{k}:{v}" for k, v in r.headers.items()))
    blob = "\n".join(bodies) + "\n".join(rec.getMessage() for rec in caplog.records)
    for canary in (CANARY_JWT_SECRET, CANARY_OPENAI, CANARY_PUBLISHABLE, CANARY_OPENAI[-8:], CANARY_JWT_SECRET[-8:]):
        assert canary not in blob


def test_sec05_settings_only_configured_flags(child):
    s = child.get("/api/v1/settings").json()
    assert s["integrations"]["openai"] == {"configured": True}
    assert "sk-" not in str(s) and "supabase.co" not in str(s)


def test_sec06_unhandled_error_has_no_details(child, monkeypatch, caplog):
    from app.modules.entries import service

    marker = "QA-PII-Иванов-secret-note"

    def boom(*a, **k):
        raise RuntimeError(f"insert failed params=({marker})")

    monkeypatch.setattr(service, "daily_totals", boom)
    act = child.activity("math")["id"]
    caplog.set_level(logging.DEBUG)
    r = child.get(f"/api/v1/activities/{act}/daily-totals")
    assert r.status_code == 500 and r.json()["code"] == "internal_error"
    assert marker not in r.text
    assert all(marker not in (rec.getMessage() + str(rec.exc_text or "")) for rec in caplog.records)
    assert all(rec.exc_info is None for rec in caplog.records if rec.levelno >= logging.ERROR)


def test_iso03_owner_fields_in_body_rejected(child, make_api):
    other = make_api()
    act = child.activity("math")["id"]
    for extra in ("child_id", "owner_id", "user_id", "owner"):
        r = child.post(f"/api/v1/activities/{act}/entries",
                       json={"activity_date": "2026-10-05", "duration_seconds": 600, extra: str(other.user_id)})
        assert r.status_code == 422, extra


def test_iso_child_cannot_use_x_child_id(child, make_api):
    other = make_api()
    child.client.headers["X-Child-Id"] = str(other.user_id)
    assert child.get("/api/v1/activities").status_code == 404
