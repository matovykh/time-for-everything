# Contributing

Read `docs/SPECIFICATION.md` and `docs/API.md` before changing behavior. Preserve the approved visual prototype while developing the separate `frontend/` and `backend/` application.

## Pull requests

- Keep changes focused and describe the user-visible behavior and tests performed.
- Add regression tests for timers, ownership checks, schedules, rewards and purchases when changing those domains.
- Never trust a balance, reward, role, price or resource owner supplied by the browser.
- Database changes require an explicit migration, indexes/constraints and a safe upgrade path. Do not add destructive startup behavior.
- Do not commit real credentials, generated local databases, recordings of real children, or production dumps.
- Run backend tests and the frontend typecheck/build. Browser tests must use synthetic isolated data.
- Verify light/dark/system themes, keyboard interaction, reduced motion and responsive layouts when changing UI.

## Releases and the DevOps repository

This repository contains source, migrations and Source CI only. The Dockerfile, production compose, server config template and the image release workflow live in the separate `time-for-everything_deploy` repository (its address will be added once the repositories are published). Do not add Docker, compose or deployment files here; `backend/tests/test_repo_hygiene.py` enforces this.

The release workflow in that repository verifies the following, so keep them true:

- The Source CI workflow file stays `.github/workflows/ci.yml`. A release needs a successful `push` (or `workflow_dispatch`) run of it for the exact commit.
- The released commit is on the default branch, and the tag `vX.Y.Z` points to it.
- `APP_VERSION` in `backend/app/core/config.py` equals the tag version without `v`. A mismatch fails the release.
- `REQUIRED_SCHEMA_VERSION` in `backend/app/db/session.py` equals the prefix of the newest file in `supabase/migrations/`.
- Only `frontend/`, `backend/app/` and `backend/requirements.txt` go into the image. New runtime settings must be added to `Settings` and to the production template in the DevOps repository.

## Architecture

Use a Python modular monolith with a same-origin web frontend; do not add microservices without a demonstrated need. Supabase provides external PostgreSQL and authentication. The game spends an immutable server-controlled wallet; it never awards itself currency. Missing dates are not zero-duration activity records.

The root Node package belongs to the historical prototype; the application has its own package and lockfile in `frontend/`.

No project license has been selected yet. Ask the owner before redistributing the code or supplied logo/avatar assets.
