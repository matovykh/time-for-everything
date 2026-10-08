"""Database-level guarantees of the real SQL migration (PostgreSQL only; skipped on SQLite).

Run with TEST_DATABASE_URL pointing at a disposable local PostgreSQL (see backend/README.md).
These tests use the local Supabase *stub* (roles anon/authenticated, auth.uid()), not Supabase.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import PG_URL

pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not PG_URL, reason="needs TEST_DATABASE_URL")]


def as_user(conn, role: str, uid: uuid.UUID | None) -> None:
    conn.execute(text(f"set local role {role}"))  # role is a fixed literal from the test
    conn.execute(text("select set_config('request.jwt.claim.sub', :s, true)"), {"s": str(uid) if uid else ""})


def test_rls_own_rows_only_and_no_client_writes(engine, make_api):
    a, b = make_api(), make_api()
    a.get("/api/v1/me")
    b.get("/api/v1/me")
    with engine.connect() as conn, conn.begin():
        as_user(conn, "authenticated", a.user_id)
        owners = set(conn.execute(text("select distinct child_id from public.activities")).scalars())
        assert owners == {a.user_id}
        assert conn.execute(text("select count(*) from public.world_catalog")).scalar_one() == 16
        profiles = set(conn.execute(text("select id from public.profiles")).scalars())
        assert profiles == {a.user_id}
    for stmt in (
        "insert into public.wallet_transactions (child_id, seq, amount, balance_after, reason_code, idempotency_key)"
        " values (:u, 99, 1000, 1000, 'adjustment', 'hack')",
        "update public.wallet_accounts set balance = 100000",
        "delete from public.time_entries",
        "select * from public.idempotency_requests",
        "select * from public.audit_events",
        "select * from public.revoked_sessions",
        "delete from public.revoked_sessions",
    ):
        with engine.connect() as conn, conn.begin(), pytest.raises(DBAPIError):
            as_user(conn, "authenticated", a.user_id)
            conn.execute(text(stmt), {"u": a.user_id})
    with engine.connect() as conn, conn.begin(), pytest.raises(DBAPIError):
        as_user(conn, "anon", None)
        conn.execute(text("select * from public.activities"))


def test_ledger_is_append_only(engine, api):
    from sqlalchemy.orm import Session

    from app.modules.wallet import service as wallet

    with Session(engine) as db:
        wallet.post(db, child_id=api.user_id, amount=50, reason_code="adjustment", description="t",
                    idempotency_key="t:1")
        db.commit()
    for stmt in ("update public.wallet_transactions set amount = 5000", "delete from public.wallet_transactions"):
        with engine.connect() as conn, conn.begin(), pytest.raises(DBAPIError, match="append-only"):
            conn.execute(text(stmt))
    with engine.connect() as conn, conn.begin(), pytest.raises(DBAPIError):
        conn.execute(text("update public.wallet_accounts set balance = -1"))
    # the explicit account-deletion procedure is still possible
    with engine.connect() as conn, conn.begin():
        conn.execute(text("set local tfe.allow_ledger_delete = 'on'"))
        conn.execute(text("delete from public.profiles where id = :u"), {"u": api.user_id})
        assert conn.execute(text("select count(*) from public.wallet_transactions")).scalar_one() == 0


def test_cross_owner_and_theme_mismatch_rejected_by_constraints(engine, make_api):
    a, b = make_api(), make_api()
    a.get("/api/v1/me")
    b.get("/api/v1/me")
    with engine.connect() as conn:
        act_a = conn.execute(text("select id from public.activities where child_id = :u and code = 'math'"),
                             {"u": a.user_id}).scalar_one()
        cw_a = conn.execute(text("select id from public.child_worlds where child_id = :u"),
                            {"u": a.user_id}).scalar_one()
    # B's entry pointing at A's activity violates the composite (activity_id, child_id) FK
    with engine.connect() as conn, conn.begin(), pytest.raises(DBAPIError, match="foreign key"):
        conn.execute(text("insert into public.time_entries (child_id, activity_id, activity_date, duration_seconds,"
                          " source, quality_status) values (:b, :act, current_date, 60, 'manual', 'pending')"),
                     {"b": b.user_id, "act": act_a})
    # unlocking a bricks upgrade on A's settlers world violates the theme-matching FK
    with engine.connect() as conn, conn.begin(), pytest.raises(DBAPIError, match="foreign key"):
        conn.execute(text("insert into public.wallet_transactions (child_id, seq, amount, balance_after, reason_code,"
                          " idempotency_key) values (:a, 1, 10, 10, 'adjustment', 'x')"), {"a": a.user_id})
        tx = conn.execute(text("select id from public.wallet_transactions where idempotency_key = 'x'")).scalar_one()
        conn.execute(text("insert into public.world_unlocks (child_id, child_world_id, theme_code, upgrade_code, cost,"
                          " transaction_id) values (:a, :cw, 'bricks', 'meadow', 60, :tx)"),
                     {"a": a.user_id, "cw": cw_a, "tx": tx})
