#!/usr/bin/env python3
"""DANGEROUS: drop and recreate the application schema objects in `public`.

Dry run by default: prints the target and the exact SQL plan without connecting.
Execution requires ALL of:
  --reset
  --confirm-project-ref=<ref>   must equal the ref parsed from DATABASE_URL
  --allow-production            unless APP_ENV is 'development' or 'test'
  an interactive confirmation (type the ref), unless --yes is given

Never touches Supabase-managed schemas (auth, storage, …) and never deletes auth users.
All drops and migrations run in ONE transaction: on any error nothing changes.
Take a backup first, e.g.:  pg_dump "$DATABASE_URL" --schema=public -Fc -f backup.dump
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dbtool import (  # noqa: E402
    ADVISORY_LOCK_ID,
    connect,
    database_url,
    drop_statements,
    migrations,
    parse_target,
)


def build_plan() -> list[str]:
    plan = ["-- 1. drop application objects (public schema only)", *drop_statements(),
            "-- 2. re-apply migrations"]
    plan += [f"\\i supabase/migrations/{m.path.name}" for m in migrations()]
    return plan


def check_guards(args: argparse.Namespace, ref: str, app_env: str) -> str | None:
    """Return an error message when execution is not allowed."""
    if not args.reset:
        return None  # dry run
    if not args.confirm_project_ref:
        return "--confirm-project-ref is required with --reset."
    if args.confirm_project_ref != ref:
        return f"--confirm-project-ref={args.confirm_project_ref!r} does not match target ref {ref!r}."
    if app_env not in ("development", "test") and not args.allow_production:
        return f"APP_ENV={app_env or 'unset'} is treated as production: add --allow-production to proceed."
    return None


def main(argv: list[str] | None = None, input_fn=input) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database-url", help="defaults to $DATABASE_URL")
    p.add_argument("--reset", action="store_true", help="actually execute (otherwise dry run)")
    p.add_argument("--confirm-project-ref", help="must match the target project ref/host")
    p.add_argument("--allow-production", action="store_true")
    p.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    args = p.parse_args(argv)

    target = parse_target(database_url(args.database_url))
    app_env = os.environ.get("APP_ENV", "")
    print("Target:", target.describe())
    print("Recommended backup: pg_dump \"$DATABASE_URL\" --schema=public -Fc -f backup-before-reset.dump")
    print("\n".join(build_plan()))

    error = check_guards(args, target.project_ref, app_env)
    if error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    if not args.reset:
        print("\nDry run only. Nothing was executed. See --help for the required flags.")
        return 0
    if not args.yes:
        answer = input_fn(f"Type the project ref '{target.project_ref}' to DROP and recreate app data: ")
        if answer.strip() != target.project_ref:
            print("Aborted.", file=sys.stderr)
            return 3
    conn = connect(database_url(args.database_url))  # pragma: no cover - live DB
    try:  # pragma: no cover - live DB
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("set local lock_timeout = '10s'")
                cur.execute("select pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_ID,))
                for stmt in drop_statements():
                    cur.execute(stmt)
                for m in migrations():
                    cur.execute(m.sql())
                    cur.execute("insert into public.app_schema_migrations (version) values (%s) "
                                "on conflict (version) do nothing", (m.version,))
    finally:
        conn.close()
    print("Reset complete.")  # pragma: no cover
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
