#!/usr/bin/env python3
"""Apply pending SQL migrations from supabase/migrations to DATABASE_URL.

Default is a dry run (lists pending migrations). `--apply` executes each pending file in its own
transaction under an advisory lock and records it in public.app_schema_migrations.
The application server never runs migrations by itself.

    python scripts/db_migrate.py                 # dry run (connects read-only to read versions)
    python scripts/db_migrate.py --offline       # dry run without connecting
    python scripts/db_migrate.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dbtool import ADVISORY_LOCK_ID, connect, database_url, migrations, parse_target  # noqa: E402


def applied_versions(conn) -> set[str]:  # pragma: no cover - live DB
    with conn.cursor() as cur:
        cur.execute("select to_regclass('public.app_schema_migrations') is not null")
        if not cur.fetchone()[0]:
            return set()
        cur.execute("select version from public.app_schema_migrations")
        return {r[0] for r in cur.fetchall()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database-url", help="defaults to $DATABASE_URL")
    p.add_argument("--apply", action="store_true", help="execute pending migrations")
    p.add_argument("--offline", action="store_true", help="dry run without connecting")
    args = p.parse_args(argv)

    files = migrations()
    if args.offline:
        print("Migrations in repository (offline, nothing executed):")
        for m in files:
            print(f"  {m.version}  {m.path.name}")
        return 0

    url = database_url(args.database_url)
    print("Target:", parse_target(url).describe())
    conn = connect(url)
    try:
        done = applied_versions(conn)
        pending = [m for m in files if m.version not in done]
        if not pending:
            print("Schema is up to date.")
            return 0
        print("Pending migrations:")
        for m in pending:
            print(f"  {m.version}  {m.path.name}")
        if not args.apply:
            print("Dry run only. Re-run with --apply to execute.")
            return 0
        for m in pending:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("select pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_ID,))
                    if m.version in applied_versions(conn):
                        continue
                    cur.execute(m.sql())
                    cur.execute("insert into public.app_schema_migrations (version) values (%s) "
                                "on conflict (version) do nothing", (m.version,))
            print(f"Applied {m.path.name}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
