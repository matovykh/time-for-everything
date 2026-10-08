# «Всё успею» — backend (MVP)

FastAPI + SQLAlchemy 2 (sync) + psycopg 3 for an external **Supabase PostgreSQL / Supabase Auth**.
HTTP contract: [`docs/API.md`](../docs/API.md). Schema: [`supabase/`](../supabase/README.md).
Project docs (Russian): [architecture](../docs/ARCHITECTURE.md), [development and tests](../docs/DEVELOPMENT.md).
Deployment (image, compose, releases) lives in the separate `time-for-everything_deploy` repository.

Status: working end-to-end core, tested on SQLite and on a local PostgreSQL 17 with the real SQL
migration. **Not yet exercised against a live Supabase project** (no credentials were provided):
login/refresh/logout are tested through the real HTTP client code with a mocked Supabase transport.

## Run

```sh
cd backend
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
# or: python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env.local     # fill in; never commit. Load it via CONFIG_FILE=… or your shell.
CONFIG_FILE="$PWD/.env.local" .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- ASGI app `app.main:app`, cwd `backend/`. API under `/api/v1`; OpenAPI at `/api/v1/docs` when
  `APP_ENV` ≠ `production`.
- SPA: files from `FRONTEND_DIST` (default `../frontend/dist`, relative to `backend/`; Docker:
  `/app/frontend/dist`). Existing files are served directly (`/assets/*` with immutable caching), other
  non-`/api` GET paths fall back to `index.html`. Unknown `/api/*` → JSON 404. Without a build `/`
  returns `404 frontend_not_built`.
- Starts without any configuration: `GET /api/v1/health/live` → 200; `GET /api/v1/health/ready` → 503
  with `checks` and Russian `setup` steps; data routes → `503 service_not_configured`.
- Schema is **never** created at start-up: `python ../scripts/db_migrate.py --apply` (see `supabase/`).
- Behind a reverse proxy run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy ip>` so the
  login rate limiter sees client IPs. The limiter is in-process (single container per spec).
- Dev without HTTPS: `APP_ENV=development COOKIE_SECURE=false`, Vite proxy `/api` → `127.0.0.1:8000`.

## Configuration

See [`.env.example`](.env.example). Required for readiness: `DATABASE_URL`, `SUPABASE_URL`,
`SUPABASE_PUBLISHABLE_KEY` (publishable/anon key — **never** the secret/service-role key).
`SUPABASE_JWT_SECRET` only for legacy HS256 projects. `CONFIG_FILE` points to an env file read
explicitly (environment variables take precedence). If `CONFIG_FILE` is set but the file is missing, unreadable
or holds invalid values, start-up fails with one value-free `Configuration error: …` line (no traceback).
`OPENAI_*` are only reported as configured. Production secret handling: `docs/SECRETS.md` in `time-for-everything_deploy`.

## Architecture

```
app/
  main.py                 app factory, routers, SPA fallback
  core/                   config, clock, errors, security (CSRF, cookies, body limit, headers,
                          rate limit), deps (session → principal → provisioning → acting child),
                          idempotency, audit, shared request schemas
  db/                     ORM models (mirror of the SQL migration), engine/session, schema check
  integrations/           supabase_auth: GoTrue REST client + JWT verifier (JWKS / HS256)
  modules/<name>/         router (HTTP) → service (domain logic, owner-filtered queries)
    accounts activities timers entries chores analytics dashboard rewards wallet world administration
```

Small modules keep queries inside services instead of separate repository classes; every query is
filtered by `ctx.child_id`. Analytics/dashboard are read-only; only `wallet.service.post` writes the
ledger; the world module can only debit.

Key mechanisms:

- **Auth**: `POST /auth/login` calls Supabase `token?grant_type=password` server-side; tokens live only in
  HttpOnly cookies. Every request verifies the JWT (signature via `/auth/v1/.well-known/jwks.json`
  ES256/RS256, or HS256 secret; `exp`, `aud=authenticated`, `iss`, `role=authenticated`). Double-submit
  CSRF on every unsafe method incl. login, plus Origin check against `APP_BASE_URL`.
- **Logout revocation**: logout first writes `revoked_sessions` rows (`sid:<session_id>`,
  `at:<sha256 access token>`, `rt:<sha256 refresh token>`), then pauses timers, then calls Supabase
  `/logout` best-effort. Every authenticated request and every refresh checks these keys, so copied
  cookies stop working immediately even if the upstream call fails. Expired rows are pruned on logout.
- **Logging**: unhandled errors and failed background steps log only request id, method, route template
  and exception class — no tracebacks or messages (SQL parameters could contain personal data); the
  engine uses `hide_parameters=True`.
- **Provisioning**: first authenticated request creates profile (`role=child`), 7 timed activities,
  4 chores (3 scheduled, 1 voluntary), timer drafts, wallet (0) and the `settlers` world. Idempotent and race-safe;
  `user_metadata` is used only for the display name.
- **Timers**: one draft row per activity, `SELECT … FOR UPDATE` + expected `revision` + Idempotency-Key
  stored in the same transaction. Save = freeze elapsed + create entry + reset in one transaction.
- **Rewards**: policy v1 as pure functions with exact fractions (`rewards/policy.py`). Due periods are
  evaluated at login and via `POST /rewards/evaluate`; unique `(child, period_end, category)` + unique
  wallet idempotency key + wallet row lock prevent double payment.
- **Reward-input integrity**: a child cannot set `workload`, change timezone, or change time/date of /
  delete a reviewed (confirmed/rejected) lesson entry — note only; adult correction required.
  Idempotency keys are scoped per (actor, acting child, key); body integers are strict.
- **Wallet/world**: conditional `UPDATE … SET balance = balance + :x WHERE balance + :x >= 0`, per-child
  ledger `seq`, CHECK constraints, append-only trigger; purchase in one transaction.

## Tests

```sh
cd backend
.venv/bin/python -m pytest                       # SQLite (FKs on); Postgres-only tests are skipped
.venv/bin/ruff check --config pyproject.toml app tests ../scripts

# Same suite on a disposable local PostgreSQL with the real SQL migration:
docker run -d --name tfe-pg-test -e POSTGRES_PASSWORD=<local-only> -e POSTGRES_DB=tfe_test \
  -p 127.0.0.1:55432:5432 postgres:17-alpine
TFE_ALLOW_DESTRUCTIVE_TEST_DB=1 \
TEST_DATABASE_URL=postgresql://postgres:<local-only>@127.0.0.1:55432/tfe_test .venv/bin/python -m pytest
docker rm -f tfe-pg-test
```

The Postgres mode drops and recreates schema `public`. It is **fail-closed** (`tests/db_safety.py`,
validated before any connection; otherwise pytest exits with a usage error): requires
`TFE_ALLOW_DESTRUCTIVE_TEST_DB=1` (exact value), a loopback host (`localhost`, `127.0.0.1`, `::1`), database
name `tfe_test` or `tfe_test_<suffix>`, no Supabase in the URL and no `host`/`hostaddr`/`service`/`dbname`/
`port` query overrides. CI example: `TEST_DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/tfe_test`.
Authentication in API tests uses an explicit `app.dependency_overrides[get_principal]` (header
`X-Test-User`) installed by `tests/conftest.py`; production code has no auth bypass switch. The
cookie/JWT/CSRF path is tested without that override in `tests/test_auth_security.py`.

Covered: independent timers (spec scenario math/russian), reload, two-device conflicts, idempotent
replays, long/forgotten sessions, midnight and DST, DB failure keeps the draft; all-time history and
daily totals; future dates; schedules by weekday and timezone; checkbox toggling; analytics buckets;
reward examples from the spec, deferral, no double pay under concurrency; purchases incl. concurrent
overspend; cross-user isolation over HTTP and at service level; guardian context; RLS/grants/
triggers/composite FKs on PostgreSQL; health/setup, SPA traversal, body limit, rate limit, secrets
never in responses; reset script guards.

## Not in this MVP (explicit)

AI-assisted rewards and OpenAI calls; admin connection/.env writes (`GET /settings` is read-only);
sign-up, password recovery, child login without email; guardian linking/role API (operator SQL);
wallet adjustments API; chore exceptions (vacation/illness) — walks use `excluded` day status;
reading/custom-goal and voluntary instant rewards; export/deletion endpoints; audit read API;
distributed rate limiting; a background scheduler (evaluation runs at login / on request);
dev seed with demo data. Validation against a live Supabase project is still pending.
