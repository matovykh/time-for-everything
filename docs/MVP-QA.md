# MVP QA — independent acceptance report

Owner: independent QA (Claude). QA writes only `tests/` and this file. Sources: `docs/SPECIFICATION.md` v0.3, `docs/API.md` (MVP contract).

**No live Supabase or OpenAI credentials were available. Nothing here validates Supabase Auth, its JWKS signing or a real Supabase project.** PostgreSQL results come from a disposable local `postgres:17-alpine` container (`tfe-qa-pg`, 127.0.0.1:55439) with the repository's real SQL migrations on top of `backend/tests/sql/supabase_stub.sql`. The engineers' `tfe-pg-test` container was not touched.

Status: **partial report, 2026-10-07.** Engineers are still changing code: logout returning 503 when the DB fails is in progress, and the frontend is finishing mobile rewards. The final full re-run was interrupted at the user's request. The results below come from the latest completed runs (§5).

> **Указатель на итоговое состояние** (добавлен при подготовке документации; сам отчёт исторический,
> QA его не перезапускал и результаты ниже не обновлялись). Что изменилось после отчёта:
> - **QA-07 закрыт**: source maps в production-сборке отключены (`frontend/vite.config.ts`, `sourcemap: false`);
>   CI и DevOps проверяют отсутствие `*.map` и `sourceMappingURL` в `frontend/dist` и в образе.
> - **QA-04 решён продуктово**: часовой пояс ребёнка меняет только взрослый — **намеренно**, как мера
>   безопасности (`permissions.can_edit_timezone`, `PATCH /me` → `403` для ребёнка; [API.md §4](API.md#4-auth-and-profile)).
> - **Logout 503 реализован**: `POST /auth/logout` отвечает `503 logout_incomplete`, если отзыв сессии не удалось
>   записать на сервере; cookies очищаются всегда ([API.md §4](API.md#4-auth-and-profile)).
> - Итоговые полные прогоны (backend 113 + 3 skipped на SQLite / 116 на PG17; независимый QA 1714 на SQLite и PG17;
>   frontend 34 unit + 28 QA; эталон 28; сканер 8) — [DEVOPS-HANDOFF.md §3](DEVOPS-HANDOFF.md).
> - По-прежнему **не выполнено**: проверка с живым Supabase и независимый QA-прогон Playwright на финальном
>   frontend (визуальную проверку на синтетических ответах API проводил frontend-инженер —
>   [frontend/IMPLEMENTATION.md](../frontend/IMPLEMENTATION.md)).

## 1. Findings for engineers

**Re-check 2026-10-07 ~02:00 (backend files modified 01:52–01:53):** QA-01…QA-06 are **fixed**. The QA tests that reproduced them now pass. `tests/backend/test_qa_reward_integrity.py` + `test_qa_timers_history_world.py`: 28/28 on SQLite, 28/28 on PG17. Fixes seen: `entries/service.py:121,162,186` (a child's workload change and measured edits/deletes of reviewed entries are guarded), `accounts/router.py` (`can_edit_timezone` only for a guardian), `core/idempotency.py:48-50` (`scoped_key(child_id, key)`), `core/schemas.py:19,24` (strict ints). The full suite was not re-run after these fixes (the run was interrupted on request). QA-07 (source maps) and the QA-04 product decision are still open. The descriptions below are kept as regression documentation.

Severity is about reward/currency integrity, child-data isolation and spec conformance. Every finding has a test that fails today and passes once the defect is fixed. Run it from the repo root with:
`backend/.venv/bin/python -m pytest tests/backend/<file>::<test> -p no:cacheprovider`. Add `QA_TEST_DATABASE_URL=… QA_ALLOW_DESTRUCTIVE_TEST_DB=1` to run it on PostgreSQL. Results are identical on SQLite and PG17.

### QA-01 HIGH — a child can edit a guardian-confirmed lesson entry and keep the confirmation → unearned stars
- Code: `backend/app/modules/entries/service.py:145-163` `update_entry`. `setattr` at `:155` applies `duration_seconds`/`activity_date`/`workload` but never resets `quality_status`. Router: `backend/app/modules/entries/router.py:27-33,62-66` (any actor may PATCH).
- Repro: `tests/backend/test_qa_reward_integrity.py::test_finding_child_edit_of_confirmed_entry_must_not_stay_confirmed`
  1. Math is 35 min on 10-06/07/08 and on 10-13/14/15, all guardian-confirmed (control case pays 0).
  2. On 10-16 the child PATCHes 10-13..15 to 25 min. Responses keep `quality_status: "confirmed"`.
  3. On 10-20, `POST /rewards/evaluate` → lessons **final, 30 stars**, where 0 was expected.
- Spec: §5.2 (confirmed comparable work only), §2 (a child can't change reward inputs), §14 ("Нет улучшения уроков → 0").
- Suggested fix: any non-guardian change to the duration, date or workload of a lesson entry resets it to `pending` (or forbid it), with audit.

### QA-02 HIGH — a child sets `workload` (`excluded`/`increased`) and so cherry-picks the fastest days
- Code: `Workload` is accepted from any actor in `entries/router.py:24` (create), `:32` (patch) and `timers/router.py:30` (save). The policy drops `excluded` days and days that aren't `normal`: `backend/app/modules/rewards/policy.py` `_lesson_days`.
- Repro: `test_qa_reward_integrity.py::test_finding_child_cannot_mark_workload_to_drop_slow_days`. The window has 40,40,40,30,30,30 (median 35 = baseline, so 0 expected). The child PATCHes the three 40-minute entries to `workload: excluded` (200 ×3) → **20 stars**.
- Spec §5.2.2–3: the parent marks workload; you can't pick only the fastest results.
- Suggested fix: only a guardian may set or change `workload` (a child's value is ignored or forced to `normal`), or changing it resets quality to `pending`.

### QA-03 MEDIUM — a child can delete slow confirmed lesson days → stars
- Code: `entries/service.py:165-172` `delete_entry` (any actor; an audit row is written but there's no reward guard).
- Repro: `test_qa_reward_integrity.py::test_finding_child_deleting_slow_confirmed_days_does_not_pay` → DELETE ×3 (204) → **20 stars**.
- Spec §5.2.3. Suggested fix: deleting a confirmed lesson entry, or any lesson entry inside an open reward window, needs a guardian. Otherwise a deleted confirmed day should block or defer that subject.

### QA-04 MEDIUM — changing the profile timezone lets a child back-fill yesterday's missed chores
- Code: `backend/app/modules/accounts/router.py:225-240` `patch_me` lets a child change `timezone` at any time. `chores/service.py:70-71` takes "today" from `ctx.today` (`core/deps.py:92-93`, `local_date(child.timezone)`).
- Repro: `test_qa_reward_integrity.py::test_finding_timezone_switch_cannot_backfill_missed_chore`.
  1. At Wed 09:00 Moscow, PUT completion for Tuesday → 422.
  2. PATCH `/me` `{"timezone":"Pacific/Pago_Pago"}` → 200.
  3. PUT the Tuesday completion again → **200**, so the missed instance now counts toward C/N.
- Spec §4.1 says the reporting date uses a fixed timezone. It is ambiguous whether the child may edit the profile timezone (§3.8 lists it under profile fields). **Product decision needed.** Options: guardian-only timezone change; apply it from the next local day; or keep completions on the server day of `completed_at`.

### QA-05 LOW — a guardian's Idempotency-Key is scoped per actor, not per acting child
- Code: `backend/app/core/idempotency.py:39-41,49,70`. The key is `(actor_id, key)` and the request hash covers method + path + body, but not `X-Child-Id`.
- Repro: `tests/backend/test_qa_timers_history_world.py::test_guardian_idempotency_key_scoped_per_child`. The guardian buys `settlers/meadow` for kid1, then sends the same key and body with `X-Child-Id: kid2` → `201` with `Idempotent-Replay: true` and kid1's purchase payload. Kid2 is **not** charged and gets nothing.
- Impact: the client gets a wrong success and the wrong child's data is shown (to an authorised guardian). Fix: put the acting child id in the scope or the hash.

### QA-06 LOW — durations accept JSON strings
- `EntryCreate.duration_seconds = "600"` → 201. `Strict` (`backend/app/core/schemas.py:11-12`) forbids extra fields but stays in lax type mode. API.md says integers.
- Repro: `test_qa_timers_history_world.py::test_finding_low_numeric_string_coerced`. Fix: `ConfigDict(extra="forbid", strict=True)` or `StrictInt` on numeric fields.

### QA-07 INFO — the production frontend build ships source maps
- `frontend/vite.config.ts:21` `sourcemap: true` → `dist/assets/*.js.map` (2.5 MB, the full source). No secrets were found in it (scan below), but it's served by FastAPI. Use `"hidden"` or `false` for release, or decide explicitly.

### Parent-reported items, verified status
- **Copied access cookie after logout** (accounts/router logout): now **rejected**. `core/deps.py` `get_principal` checks `revocation.is_revoked` by `sid:` and access-token hash. Covered by `tests/backend/test_qa_security_sweeps.py::test_sec03_copied_access_cookie_dead_after_logout_but_other_session_alive`, which tries GET `/me`, `/wallet`, entries and POST timer/start with the copied cookie → 401. The same user's other session stays valid (scope=local). Passing on SQLite and PG17. Re-run once the 503-on-DB-failure change lands.
- **log.exception leaking SQL parameters / PII**: the current code logs only the request id, route template and exception class (`core/errors.py`, `core/security.py`, `accounts/router.py`), and the engine uses `hide_parameters=True`. Covered by `test_sec06_unhandled_error_has_no_details`: an injected exception message carrying a PII marker appears in neither the response nor any log record, and no `exc_info` is attached. Passing.

## 2. Verified OK (independent QA tests, passing)

- **Auth sweep** (route table from OpenAPI): every private `/api/v1` route returns 401 with no session. CSRF: every unsafe route → 403 when the token is missing or wrong, or when there's a foreign `Origin`. Logout clears all three cookies with `Secure`.
- **Isolation**: child B → each id-bearing route with A's activity, chore or entry id → 404/422 with no A data in the body. A's entries, timer revision, wallet, worlds and chores are unchanged afterwards. B's lists contain none of A's ids. Owner fields in bodies → 422. A child sending `X-Child-Id` → 404.
- **Secrets**: canary JWT secret, OpenAI key and publishable key never appear in any GET response, header or log. `/settings` returns `configured` flags only.
- **Timers**: spec scenario math 10 / russian 15 / math +5 → 900 s + 900 s. Six concurrent saves → exactly one 201 and one entry. Same key replayed concurrently → one entry. Key reused with a different body → 422 `idempotency_key_reuse`. A client can't post elapsed time. Over 4 h → `long_session_confirmation_required` (draft kept); over 24 h → `session_too_long` until `duration_seconds` is given. Midnight default is `started_on` **per API.md §5** (23:50→00:20 saved to the start date). Manual entries don't touch the draft. A manual entry can't forge `source=timer`.
- **History**: entries from 2023–2026 with cursor pagination are complete with no duplicates. Daily totals are chronological, skip gaps and sum same-day entries. A future date in the child's timezone → 422, while the child's today is accepted when UTC is still yesterday. Week buckets run Monday–Sunday and the current week is flagged.
- **Chores**: the weekday chore and Friday chore are evaluated in the child's timezone. A Saturday completion for a weekday chore → 422 `not_scheduled`. A voluntary chore toggled ×6 → one completion, no stars, not counted in N.
- **Rewards vs oracle**: the backend `policy.py` matches `tests/reference/reward_policy_v1.py` on 400 chores, 600 walk and 600 lessons random cases, the exact 5/10/15 % boundaries (incl. 2100→1785 s) and the window/period semantics of API.md §8 (`D_k=A+14+7k`, period_end = D−1). Repeated evaluate/preview calls don't pay.
- **Purchases**: client-supplied `cost`/`price`/`amount` → 422. Prerequisites are enforced. Six concurrent buys of one item → one debit. Four concurrent buys across worlds with balance for two → exactly two, never negative, ledger sum = balance. World progress is independent and adding a world is free and idempotent.
- **Frontend**: all 13 routes (including an unknown id, `#garbage`, `%3Cscript%3E`) render without uncaught errors when every endpoint returns 500, and show `role=alert`; they also cope with empty collections. HTML in activity or display names renders as text (no injected `img`/`b`, no script run). Web Storage holds only the theme choice and the guardian's acting-child id, never tokens. Home and chores use the server's `scheduled_*` counts (prototype issue PRO-1 is fixed in React).

## 3. Spec/API interpretations used (confirm)
1. Midnight follows API.md: default `started_on`, allowed `started_on ≤ date ≤ today`. Tested as documented.
2. A failed chores regularity check pays 0 (API.md §8 agrees).
3. Walk improvement needs a baseline with E≥5 and no missing day (API.md §8). The oracle adapter applies this.
4. The child timezone edit (QA-04) needs a product decision.

## 4. QA assets
| Path | Purpose |
|---|---|
| `tests/reference/` | Spec oracle + 28 self-tests |
| `tests/security/scan_secrets.py`, `test_scan_secrets.py` | Leak scanner. Narrow, path-bound allowlist: only the loopback CI DSN in `.github/workflows/ci.yml` (exact line), plus 8 regression tests covering true positives and the former false positives |
| `tests/backend/conftest.py` | Real cookie→JWT→revocation auth (no principal override). Mock Supabase transport via `get_auth_client`. SQLite, or a disposable PG gated by `QA_ALLOW_DESTRUCTIVE_TEST_DB=1`, a single loopback host, db `tfe_qa[_suffix]`, no `host/hostaddr/port/dbname/service/options/user` query overrides, no `PG*` target env vars, and a `current_database()` check before `DROP` (`test_qa_pg_guard.py`, 14 tests) |
| `tests/backend/test_qa_*.py` | Security sweeps, isolation sweep, reward integrity, policy parity, timers/history/world |
| `tests/frontend/` | `vitest.qa.config.mjs` (uses the frontend's own deps/setup) + `routes.qa.test.tsx` |

## 5. Run log (latest completed runs)
| Date | Command | Environment | Result |
|---|---|---|---|
| 2026-10-06 | `python3 -I -m unittest discover -s tests/reference` | Python 3.13.9 | 28 passed |
| 2026-10-07 | `python3 -I -m unittest discover -s tests/security` | same | 8 passed |
| 2026-10-07 | `python3 -I tests/security/scan_secrets.py` (repo) and on a temp `vite build` output | same | 0 findings |
| 2026-10-07 | `backend/.venv/bin/python -m pytest tests/backend` | SQLite | 1676 passed, 4 failed (QA-01..04); timers/world file run separately: 2 failed (QA-05, QA-06) |
| 2026-10-07 | same with `QA_TEST_DATABASE_URL` | local PG17, real migrations | identical results |
| 2026-10-07 | backend own suite `pytest` | SQLite | 104 passed, 3 skipped |
| 2026-10-07 | backend own suite with `TEST_DATABASE_URL` → `tfe_test_qa` | local PG17 | 107 passed |
| 2026-10-07 | `ruff check app tests ../scripts` | backend venv | clean |
| 2026-10-07 | `npm run typecheck`, `npx vitest run` | frontend | clean; 24 passed |
| 2026-10-07 | `npx vitest run --config ../tests/frontend/vitest.qa.config.mjs` | frontend deps, jsdom | 28 passed |
| 2026-10-07 | `pytest tests/backend/test_qa_pg_guard.py` | backend venv | 14 passed; without opt-in a PG run errors before connecting |
| 2026-10-07 ~02:00 | `pytest tests/backend/test_qa_reward_integrity.py test_qa_timers_history_world.py` (after backend fixes) | SQLite + PG17 | 28/28 + 28/28 (QA-01..06 fixed) |

Not done: Playwright viewport/mobile pass on the final frontend (it was still being finished), live Supabase, AI mode (not in MVP), Docker image build.
