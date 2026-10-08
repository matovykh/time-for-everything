# supabase/

Application schema for an **external Supabase project** (PostgreSQL 15+).

- `migrations/<timestamp>_<name>.sql` — ordered, forward-only migrations. They create only
  application objects in `public` (tables, constraints, indexes, RLS policies, grants, triggers) and
  the required reference data: 4 world themes, 16 world upgrades, reward policy v1. No demo data,
  no users, no passwords.
- The files contain no `begin/commit`; `scripts/db_migrate.py` runs each file in one transaction and
  records it in `public.app_schema_migrations`. With psql use `--single-transaction -v ON_ERROR_STOP=1`.
- The backend **never** creates or migrates the schema at start-up; `/api/v1/health/ready` reports
  `schema: missing|outdated` until migrations are applied.

```sh
cd backend && source .venv/bin/activate          # psycopg comes from backend/requirements.txt
export DATABASE_URL='postgresql://…?sslmode=require'
python ../scripts/db_migrate.py --offline         # lists repository migrations, connects nowhere
python ../scripts/db_migrate.py                   # dry run: lists pending migrations
python ../scripts/db_migrate.py --apply
python ../scripts/db_reset.py                     # dry run: prints target + exact SQL, connects nowhere
```

`db_reset.py` (dangerous) executes only with `--reset --confirm-project-ref=<ref>`, plus
`--allow-production` unless `APP_ENV` is `development`/`test`, plus an interactive confirmation
(or `--yes`). It drops only the listed `public` application tables/functions (no `CASCADE`) and
re-applies migrations in one transaction. It never touches `auth`, `storage` or other managed
schemas and never deletes auth users. Back up first: `pg_dump "$DATABASE_URL" --schema=public -Fc -f backup.dump`.

Step-by-step operator guide (in Russian), including backups and account setup: `docs/DEPLOYMENT.md`
(sections on migrations and accounts) in the separate `time-for-everything_deploy` repository. Its address
will be added after publication. Migrations stay an explicit operator step, run from an application checkout
at the released commit (`application.commit` in the release manifest). They are never run by the image or on
the server, and `db_reset.py` is never used for upgrades.

Security model:

- RLS is enabled on every table. Data API roles: `anon` — nothing; `authenticated` — `SELECT` of own /
  linked-child rows and reference tables; no inserts/updates/deletes. Internal tables (audit,
  idempotency, migrations) are invisible to them.
- The backend connects with `DATABASE_URL` (typically the table owner, which bypasses RLS) and
  enforces ownership by `child_id` in every query; this is covered by isolation tests.
- `wallet_transactions` is append-only and final `reward_evaluations` are immutable (triggers).
  Deleting a child's data is an explicit procedure (see the migration header): delete
  `public.profiles` with `set local tfe.allow_ledger_delete = 'on'`, then delete the auth user through
  the Supabase dashboard/Admin API.
- Users are created by an adult/operator in Supabase Auth (dashboard invite or Admin API). Promoting a
  profile to `guardian`/`admin` and linking children is an operator SQL action in this MVP:
  `update public.profiles set role = 'guardian' where id = '<adult>';`
  `insert into public.guardian_children (guardian_id, child_id) values ('<adult>', '<child>');`

Verified locally against PostgreSQL 17 with `backend/tests/sql/supabase_stub.sql` (a test-only stand-in
for `auth.users`, `auth.uid()` and the `anon`/`authenticated` roles). It has **not** been applied to a
live Supabase project from this repository (no credentials were provided).
