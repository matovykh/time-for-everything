# DevOps handoff — «Всё успею» MVP (final delivery)

> **Historical (2026-10-07, before the repository split).** `infra/`, `compose*.yaml`, `.dockerignore`,
> the container CI job and `tests/security/container_secret_smoke.sh` have since moved to the separate
> `time-for-everything_deploy` repository (see its `docs/HANDOFF-ENGINEER.md`). Paths, the `vse-uspeyu:mvp`
> tag and the `container` CI job below describe the old layout; test results remain valid as a record.

Audience: the technical writer who will produce the user/operator documentation, and whoever runs
the first real installation. Everything below was executed locally on 2026-10-07 by DevOps
(macOS, Docker Desktop 29.2.0 / Compose v5.0.2, Apple Silicon → `linux/arm64` image). Base the final
instructions on the commands in §3 and §5; they are the ones that were actually run.

**Scope of this pass.** DevOps owns only `infra/`, `compose.yaml`, `.dockerignore`, `.github/workflows/`
and this file. App code, `README.md`, `docs/DEPLOYMENT.md`, tests and secrets were **not** changed.
No live Supabase project was contacted; no real credentials were used anywhere.

> **Not verified (state this in user-facing docs):** real Supabase Auth (login / refresh / logout),
> Supabase JWKS, and RLS/Data API behaviour against a *live* Supabase project. Local PostgreSQL runs use
> `backend/tests/sql/supabase_stub.sql`, a test-only stand-in for `auth.users`, `auth.uid()` and the
> `anon`/`authenticated` roles. GitHub Actions has never run remotely (no published repository); the
> workflow was validated locally by executing its `run:` blocks (see §3.4).

---

## 1. Final artifact

| Item | Value |
|---|---|
| Image tag | `vse-uspeyu:mvp` |
| Image ID (local, containerd store) | `sha256:d4677dae7cbf3a59388eba7adb3d160fc97ee1820498ec6fe9f8347e31995c1d` |
| Platform / size | `linux/arm64`, 381 MB on disk (≈82 MB content). CI builds `linux/amd64`. |
| Build | `docker build -f infra/Dockerfile -t vse-uspeyu:mvp .` → exit 0, every layer `CACHED` (no source change since the 07:20 build) |
| Frontend bundle | `assets/index-C8-0lkfK.js` (650 kB, 206 kB gzip), `assets/index-_2TvpXyQ.css`, 5 Nunito Sans woff2. Identical hashes from a clean `npm ci && npm run build`. No `.map` files, no `sourceMappingURL`. |
| Running instance | `tfe-mvp-smoke` → `127.0.0.1:8001`, hardened flags, unconfigured, runs exactly the ID above (verified `docker inspect .Image` == tag ID). |

Note for operators: with Docker's containerd image store the image ID is the *index* digest. It changes
on every re-export (the build attestation is regenerated) even when all layers are cached, so a rebuild
of identical sources can show a different ID. Verify "container runs the current image" by comparing
`docker inspect <ctr> --format '{{.Image}}'` with `docker image inspect vse-uspeyu:mvp --format '{{.Id}}'`.

## 2. Architecture (as shipped)

- **One container**: Uvicorn (single process) + FastAPI serves `/api/v1/*` and the built React SPA from
  `/app/frontend/dist`. Node exists only in the build stage. `prototype/`, tests, `.env*`, caches,
  DB files and `node_modules` are excluded by `.dockerignore` and absent from the image (verified).
- **External services**: Supabase PostgreSQL (`DATABASE_URL`) and Supabase Auth (`SUPABASE_URL` +
  publishable/anon key). Nothing else. OpenAI keys are only reported as configured; AI is not implemented.
- **Image** (`infra/Dockerfile`): stage 1 `node:24-bookworm-slim` → `npm ci && npm run build`;
  stage 2 `python:3.13-slim-bookworm`, `pip install -r backend/requirements.txt`, user `app` uid/gid
  **10001**, app files root-owned (not writable by the app user), `/data/config` owned by `app`,
  `EXPOSE 8000`, `HEALTHCHECK` = GET `/api/v1/health/live`,
  `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers`.
- **Runtime hardening** (compose and the CI smoke run): `read_only` root FS, `tmpfs /tmp` 32 MB,
  `cap_drop: ALL`, `no-new-privileges`, `init`, 512 MB / 1 CPU / 128 pids, `restart: unless-stopped`,
  json-file logs 10 MB × 3. Port published on **127.0.0.1 only**; TLS/public exposure via a reverse proxy.
- **Configuration**: a server-side env file bind-mounted **read-only** at `/data/config/app.env`
  (`CONFIG_FILE`). Process environment variables take precedence. Changes need a container restart.
- **Schema**: never created/migrated at start-up. Migrations are an explicit operator step (§5.3).
- **Health**: `GET /api/v1/health/live` = process up. `GET /api/v1/health/ready` = 200 only when DB is
  reachable, schema is current **and** Auth is configured; otherwise 503 with `checks` + Russian `setup`
  hints. Readiness does **not** prove that a real login works.

## 3. Verification performed (exact commands, outcomes)

All exit codes were captured directly (`set -o pipefail` or `rc=$?` right after the command; no piping
into `tail` before taking the code). CI-equivalent runs used a **clean copy** of the repo in
`/tmp/tfe-ci/repo` (rsync excluding `.venv`, `node_modules`, `dist`, caches, `.claude`, `.env`/`.env.local`)
with a fresh `uv venv --python 3.13` + `requirements-dev.txt`, so the working tree and its `frontend/dist`
were not touched. Logs: `/tmp/tfe-ci/logs/*.log` (ephemeral).

### 3.1 Image and hardened container (unconfigured)

```sh
docker build --progress=plain -f infra/Dockerfile -t vse-uspeyu:mvp .        # exit 0
docker rm -f tfe-mvp-smoke                                                    # old container ran a superseded image
docker run -d --name tfe-mvp-smoke -p 127.0.0.1:8001:8000 --init --read-only \
  --tmpfs /tmp:size=32m,mode=1777 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 512m --cpus 1.0 --pids-limit 128 vse-uspeyu:mvp                   # exit 0, healthy
```

| Check (against `http://127.0.0.1:8001`) | Result |
|---|---|
| `GET /api/v1/health/live` | **200** `{"status":"ok"}` |
| `GET /api/v1/health/ready` | **503** `database: not_configured, schema: unknown, auth: not_configured` + 2 Russian setup steps |
| `GET /` | 200 `text/html` (SPA) |
| `GET /some/route` (SPA fallback) | 200 `index.html` |
| `/assets/index-*.js`, `/assets/index-*.css` | 200, `cache-control: public, max-age=31536000, immutable` |
| `/logos/logo.png` | 200 `image/png` |
| `GET /api/v1/nope` | 404 JSON `{"code":"not_found",…}` |
| `GET /api/v1/me`, `/activities`, `/settings` | **503** `service_not_configured` |
| `/api/v1/docs`, `/api/v1/openapi.json` | 404 (disabled when `APP_ENV=production`, the default) |
| Path traversal (`/../../etc/passwd`, `/assets/..%2f..%2f…`) | only `index.html` returned, no file content |
| Process identity | uid/gid **10001**, `CapEff=0`, `CapBnd=0`, `NoNewPrivs=1`, PID 1 = `docker-init` |
| Writes | `/app/backend`, `/app/frontend/dist`, `/data/config` → *Read-only file system*; `/tmp` writable (tmpfs) |
| Image contents | no `*.map`, `.env*`, `*.db`, `*.sqlite*`; no `tests/`, no `prototype/`; no secret-like env vars (`GPG_KEY` is the Python base image's public signing key) |
| Response headers | `x-content-type-options: nosniff`, `x-frame-options: DENY`, `referrer-policy: same-origin`, `cross-origin-opener-policy: same-origin`, `cache-control: no-cache` (HTML) / `no-store` (API). No CSP / HSTS (see §7). |

DB-only readiness (container with a read-only mounted `CONFIG_FILE` containing only `DATABASE_URL` to a
disposable local PG17 with stub + migrations, reached via `host.docker.internal`; container removed after):
`ready` → **503** `database: ok, schema: ok, auth: not_configured`; `/me` and `/settings` → **401**
`not_authenticated` (with a DB configured the app answers 401, without one 503). The test DB password did
not appear in any response or container log.

### 3.2 Compose

```sh
docker compose -f compose.yaml config -q                                   # exit 0 (real tree, no .env)
# in the clean copy, image already built (no rebuild, so the mvp tag is unchanged):
TFE_HTTP_PORT=8003 docker compose -p tfe-devops-compose -f compose.yaml up -d --no-build   # without .env → exit 1
#   "bind source path does not exist: …/.env"  (fails closed — intended)
cp .env.example .env && chmod 600 .env
TFE_HTTP_PORT=8003 docker compose -p tfe-devops-compose -f compose.yaml up -d --no-build   # exit 0, healthy in 7 s
docker compose -p tfe-devops-compose -f compose.yaml down                                 # exit 0, container+network removed
```

Verified on the compose container: same image ID as `vse-uspeyu:mvp`; `ReadonlyRootfs=true`,
`CapDrop=[ALL]`, `no-new-privileges`, `Init=true`, 512 MiB, 1 CPU, 128 pids, `unless-stopped`,
json-file 10m×3; `/data/config/app.env` mounted `rw=false` and readable by uid 10001; live 200, ready 503, `/` 200.

### 3.3 Tests (clean copy, fresh venv / fresh `npm ci`)

| Suite | Command (cwd) | Result |
|---|---|---|
| Backend, SQLite | `python -m pytest` (`backend/`) | exit 0 — **113 passed, 3 skipped** (PG-only) |
| Independent QA, SQLite | `python -m pytest tests/backend -q` (repo root) | exit 0 — **1714 passed** |
| Lint | `ruff check --config pyproject.toml app tests ../scripts` (`backend/`) | exit 0 — all checks passed |
| Reward policy oracle | `python -I -m unittest discover -s tests/reference -v` | exit 0 — 28 tests OK |
| Scanner self-tests | `python -I -m unittest discover -s tests/security -v` | exit 0 — 8 tests OK |
| Secret scan, repo | `python -I tests/security/scan_secrets.py` | exit 0 — 0 findings (clean copy; see §7 for the working copy) |
| Backend, PostgreSQL 17 | `TFE_ALLOW_DESTRUCTIVE_TEST_DB=1 TEST_DATABASE_URL=postgresql://postgres:<pw>@127.0.0.1:55441/tfe_test python -m pytest` | exit 0 — **116 passed, 0 skipped** |
| Independent QA, PostgreSQL 17 | `QA_ALLOW_DESTRUCTIVE_TEST_DB=1 QA_TEST_DATABASE_URL=postgresql://postgres:<pw>@127.0.0.1:55441/tfe_qa python -m pytest tests/backend -q` | exit 0 — **1714 passed** |
| Frontend | `npm ci`, `npm run typecheck`, `npm test`, `npm run test:qa`, `npm run build` (`frontend/`) | all exit 0 — **34/34** unit, **28/28** QA, build OK, 0 `.map` |
| Secret scan, bundle | `python3 -I ../tests/security/scan_secrets.py "$PWD/dist"` (`frontend/`) | exit 0 — 0 findings in `frontend/dist`; a planted `sb_secret_…` canary was detected (exit 1) |

PostgreSQL runs used a **new** disposable container `tfe-devops-pg` (`127.0.0.1:55441`, removed
afterwards). The team's existing test DBs were not used, so there was no concurrent use. The only
warning is Starlette's `httpx` TestClient deprecation (test-only).

### 3.4 CI workflow validated locally

`.github/workflows/ci.yml` parses (PyYAML). `actionlint` is not installed. Each job's `run:` blocks were
executed with `bash --noprofile --norc -eo pipefail` (GitHub's shell), with the job/step `env` and
`working-directory`, via a throwaway runner (`/tmp/tfe-ci/tools/run_ci_steps.py`). Only the host port,
DB password and container name were substituted for local use.

| Job | Result |
|---|---|
| `backend` | all steps exit 0 (see §3.3) |
| `postgres` | backend PG17 116 passed; create `tfe_qa`/`tfe_migr` + stub OK; QA PG17 1714 passed; migration CLI dry run → apply → re-apply "Schema is up to date." |
| `frontend` | all steps exit 0; new bundle step scans `frontend/dist` |
| `container` | compose validate, build, image-content assertions and hardened smoke test exit 0; a negative control without `--read-only` correctly **fails** ("root filesystem is writable") |

## 4. Changes made in this pass (DevOps-owned files only)

**`.github/workflows/ci.yml`**
1. **Fixed a vacuous check**: `scan_secrets.py dist` run from `frontend/` resolved to `<repo>/dist`
   (the scanner resolves relative paths against the repo root), so the bundle was never scanned. Now
   `"$PWD/dist"`, plus `dist/index.html` must exist, no `*.map`, no `sourceMappingURL`.
2. `postgres` job now also runs the **independent QA suite on PostgreSQL** (DB `tfe_qa`) and exercises
   **`scripts/db_migrate.py`** (offline, dry run, apply, idempotent re-apply) on a stubbed DB `tfe_migr`.
   Extra DSNs are built at run time from `CI_PG_PASSWORD`, so no new literal credential lines enter the
   repo and the QA scanner allowlist stays unchanged. Added pip cache.
3. `container` job: `docker compose config -q`; asserts `USER app:app`, uid 10001, no maps/env/DB
   files/tests/prototype in the image; the smoke run uses the same hardening as compose and additionally
   checks `/me` 503, unknown API 404, SPA fallback 200, uid 10001 and that the root FS is read-only
   (probe on app-owned `/data/config`, because `/app` is root-owned and would pass even without `--read-only`).

**`compose.yaml`**
1. `image: vse-uspeyu:mvp`, so `docker compose build` produces the same tag that docs and smoke tests use.
2. Host port configurable: `"127.0.0.1:${TFE_HTTP_PORT:-8000}:8000"` (still loopback-only; default unchanged).
3. Log rotation: json-file `max-size 10m`, `max-file 3`.

`infra/Dockerfile` and `.dockerignore`: reviewed, verified, **unchanged** (no defects found).

## 5. How to run (tested commands)

### 5.1 Production-like (Docker Compose)

```sh
cp .env.example .env            # fill on the server; never commit; Linux: chown 10001 .env && chmod 600 .env
docker compose build            # tags vse-uspeyu:mvp
docker compose up -d            # host port 8000 on 127.0.0.1; or: TFE_HTTP_PORT=8002 docker compose up -d
docker compose ps
curl -f http://127.0.0.1:8000/api/v1/health/live      # 200
curl -s http://127.0.0.1:8000/api/v1/health/ready     # 503 + setup steps until DB, schema and Auth are ready
docker compose down
```

- `.env` must exist, or `up` fails (`create_host_path: false`). Docker Desktop maps bind-mount ownership.
  On Linux the file must be readable by uid 10001 (owner 10001, mode 0600 or a narrow ACL).
- Use **GET** for probes. `HEAD /api/v1/health/live` returns 404.
- Compose also reads the project `.env` for its own `${…}` interpolation (only `TFE_HTTP_PORT` is used).
  Values containing `$` may produce Compose warnings. Prefer setting `TFE_HTTP_PORT` in the shell.
- Behind a reverse proxy: replace the command with
  `--proxy-headers --forwarded-allow-ips=<proxy IP>` (never `*`). The rate limiter is in-process, so
  run a single container and a single worker.

### 5.2 Plain `docker run` (equivalent hardening)

```sh
docker run -d --name tfe-app -p 127.0.0.1:8000:8000 --init --read-only \
  --tmpfs /tmp:size=32m,mode=1777 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 512m --cpus 1.0 --pids-limit 128 \
  -e CONFIG_FILE=/data/config/app.env \
  --mount type=bind,source="$PWD/.env",target=/data/config/app.env,readonly \
  vse-uspeyu:mvp
```

### 5.3 Database migrations (operator step; app never migrates)

```sh
cd backend && source .venv/bin/activate     # psycopg from backend/requirements.txt
export DATABASE_URL='postgresql://…?sslmode=require'   # server-side only
python -I ../scripts/db_migrate.py --offline        # list repo migrations, no connection
python -I ../scripts/db_migrate.py                  # dry run: pending list (read-only connection)
python -I ../scripts/db_migrate.py --apply          # apply; re-running prints "Schema is up to date."
```

Migrations: `20261006000001_init.sql`, `20261006000002_session_revocations.sql` (required schema
version `20261006000002`). Seed: 4 world themes, 16 upgrades, reward policy v1, no users. RLS is
enabled on every `public` table (verified on PG17 with the stub). `scripts/db_reset.py` is
dry-run by default. Execution requires `--reset --confirm-project-ref=<ref>`, plus `--allow-production`
outside development/test, plus interactive confirmation. Take `pg_dump "$DATABASE_URL" --schema=public -Fc` first.

Accounts: create users in the Supabase dashboard. Guardian linking is operator SQL only:
`update public.profiles set role='guardian' where id='<adult>'; insert into public.guardian_children (guardian_id, child_id) values ('<adult>','<child>');`

### 5.4 Configuration keys (`.env.example`; full descriptions in `backend/.env.example`)

| Key | Needed for readiness | Notes |
|---|---|---|
| `APP_ENV` | – | `production` (default). `development` only for local HTTP. |
| `APP_BASE_URL` | – (needed for real use) | Exact public HTTPS origin; foreign `Origin` on unsafe methods is rejected. |
| `COOKIE_SECURE` | – | `false` takes effect only with `APP_ENV=development`. |
| `DATABASE_URL` | **yes** | Supabase PG DSN with `sslmode=require`; server-side secret. |
| `DB_POOL_SIZE` | – | 1–50, default 5. |
| `SUPABASE_URL` | **yes** | `https://<ref>.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | **yes** | Publishable/anon key. **Never** the secret/service-role key. |
| `SUPABASE_JWT_SECRET` | – | Legacy HS256 projects only; empty with JWKS signing keys. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | – | Reported as configured only; AI not implemented. |
| `LOGIN_RATE_LIMIT`, `LOGIN_RATE_WINDOW_SECONDS` | – | Defaults 10 / 300 s, in-process. |
| `CONFIG_FILE`, `FRONTEND_DIST` | – | Set by compose/image (`/data/config/app.env`, `/app/frontend/dist`). |
| `TFE_HTTP_PORT` | – | Compose only: host port, default 8000. Not read by the app. |

### 5.5 Local development (from `backend/README.md` / `frontend/IMPLEMENTATION.md`)

Backend: `uvicorn app.main:app --host 127.0.0.1 --port 8000` from `backend/` with
`APP_ENV=development COOKIE_SECURE=false` for HTTP. Frontend: `npm run dev` (5173, proxies `/api` to
`VITE_BACKEND_ORIGIN`, default `http://127.0.0.1:8000`).

## 6. Not implemented in this MVP (from `docs/API.md` §9–10, `GET /settings → deferred`, backend README)

`deferred` list returned by the API: `admin_connections_write`, `ai_assisted_rewards`, `signup`,
`password_recovery`, `guardian_management`, `wallet_adjustments`, `chore_exceptions`. In detail:

- AI-assisted rewards / keeper letter; no OpenAI calls (rewards are deterministic policy v1).
- Admin UI writes of connections / `.env` (`PATCH /settings`, `/admin/connections` do not exist; `GET /settings` is read-only).
- Sign-up, password recovery, child login without email. Users are created in Supabase by an adult/operator.
- Guardian ↔ child linking and role management API (operator SQL only, §5.3).
- Wallet adjustments API.
- Chore schedule exceptions (vacation/illness). Walks use the `excluded` day status instead.
- Reading / custom-goal rewards and voluntary instant rewards.
- Data export / deletion endpoints (deletion is a documented manual SQL + Supabase procedure in `supabase/README.md`).
- Audit-log read API.
- Distributed rate limiting (in-process only, single container); background scheduler (reward evaluation runs at login and on `POST /rewards/evaluate`).
- Dev seed / demo data.
- Child timezone change is adult-only **by design** (security), not a missing feature.

## 7. Limitations and warnings

1. **Live Supabase not verified** (Auth, JWKS, RLS via Data API, TLS DSN, pooler). Do the checklist in
   `docs/DEPLOYMENT.md` («Проверка перед реальной эксплуатацией») on a real project before use.
2. **CI never ran on GitHub**: it was validated locally only (§3.4). The first remote run should be watched.
   It builds `linux/amd64`, while local verification was `linux/arm64`.
3. **No CSP / HSTS / Permissions-Policy headers** from the app. Set HSTS (and optionally CSP) at the HTTPS
   reverse proxy. Changing app headers is outside DevOps scope.
4. Missing static files under `/assets/` (e.g. `*.js.map`) return the SPA `index.html` with **200**
   instead of 404 (SPA fallback). Harmless (no maps exist), but monitoring should not treat 200 as proof an asset exists.
5. `HEAD` on health endpoints returns 404. Use GET (the image HEALTHCHECK and CI already do).
6. `/api/v1/me` answers **503** when no DB is configured and **401** when a DB is configured but there is
   no session (the frontend handles both via `/health/ready`).
7. Bundle ≈650 kB (206 kB gzip), no code splitting. Source maps are disabled (`build.sourcemap: false`).
8. Single worker, in-process login limiter; scale vertically only. `--no-proxy-headers` by default.
9. Working copy secret scan: `python3 -I tests/security/scan_secrets.py` on *this* working tree exits 1
   with 3 HIGH findings in **`.claude/settings.local.json`** (local tool-permission entries that contain the
   password of the disposable loopback QA DB `127.0.0.1:55439/tfe_qa`). The file is in `.gitignore` and
   `.dockerignore` (never committed, never in the image). A clean checkout scans with 0 findings. Owner may
   delete those permission lines. DevOps did not edit them (out of scope).
10. Image ID changes on re-export even for identical sources (§1).
11. No license chosen yet. Required before public publication (owner decision).
12. Test-only: Starlette deprecation warning for the `httpx` TestClient.

## 8. Environment state at handoff

| Port / resource | What | Owner | State |
|---|---|---|---|
| `127.0.0.1:8001` | `tfe-mvp-smoke`, image `vse-uspeyu:mvp` (`d4677dae…`), hardened, unconfigured | DevOps | **left running** for review; remove with `docker rm -f tfe-mvp-smoke` |
| `127.0.0.1:8000` | local uvicorn PID 62394 from `backend/.venv` (started 2026-10-06 20:05, unconfigured, serves working-tree `frontend/dist`, same bundle hashes) | engineers | **preserved, not touched**. Occupies compose's default port: use `TFE_HTTP_PORT` or stop it first. |
| `127.0.0.1:8080` | `python3 -m http.server` for `prototype/` (PID 66538) | prototype | **preserved** |
| `127.0.0.1:55432` | `tfe-pg-test` postgres:17-alpine (DBs `tfe_test`, `tfe_scripts`), idle | engineers | **left** (disposable). Remove: `docker rm -f tfe-pg-test` |
| `127.0.0.1:55439` | `tfe-qa-pg` postgres:17-alpine (DBs `tfe_qa`, `tfe_test_qa`), idle | QA | **left** (disposable). Remove: `docker rm -f tfe-qa-pg` |
| `buildx_buildkit_pdf-book-splitter-builder0` and `pdf-book-splitter` images | unrelated project | other | **not touched** |

Cleaned up by DevOps: the old `tfe-mvp-smoke` (superseded image `184dbf9c…`, no longer on disk);
`tfe-devops-pg` (55441); `tfe-devops-ready` (8002); compose project `tfe-devops-compose` (8003, container +
network); `tfe-devops-ci` (removed by the CI trap); image `vse-uspeyu:ci`; scratch repo copy and venv in
`/tmp/tfe-ci` (only `logs/` and `tools/` remain, safe to delete).

## 9. Notes for the technical writer

- `docs/DEPLOYMENT.md` is still accurate. Worth adding: `TFE_HTTP_PORT`, the image tag `vse-uspeyu:mvp`,
  "use GET for probes", HSTS/CSP at the proxy, and that `.env` must exist before `docker compose up`.
- Keep the "not verified against live Supabase" statement prominent wherever setup is described.
- The canonical feature gap list is `GET /settings → deferred` plus `docs/API.md` §10 (mirrored in §6).
- Test counts to quote: backend 113 passed + 3 skipped (SQLite) / 116 passed (PG17); independent QA 1714
  passed (SQLite and PG17); frontend 34 unit + 28 QA; reference 28; scanner 8.
