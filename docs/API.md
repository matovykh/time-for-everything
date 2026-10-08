# «Всё успею» — HTTP API contract v1 (MVP backend)

Status: **implemented contract for the MVP backend** in `backend/`. Owner: backend.
Frontend implements against this document. Changes to this file are announced; fields are
only added in a backward-compatible way within `/api/v1`.

Everything below is served by one FastAPI process (`app.main:app`) under the same origin as the
SPA. There is **no CORS**: the browser must call the API same-origin (`/api/v1/...`). In Vite dev,
proxy `/api` to the backend (e.g. `http://127.0.0.1:8000`).

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Prefix | `/api/v1` for all routes below. Unknown `/api/*` paths → JSON `404 not_found`. |
| Format | JSON, UTF-8. Request body limit 64 KiB (`413 payload_too_large`). |
| IDs | UUID strings (`"3f1c…"`). Default activities additionally have a stable `code` slug. |
| Dates | Local calendar dates `"YYYY-MM-DD"` in the **child's profile timezone** (IANA). |
| Timestamps | RFC 3339 UTC, e.g. `"2026-10-06T09:15:00.123Z"`. |
| Durations | Integer **seconds** (`duration_seconds`) for entries; integer **milliseconds** for timers. Never float minutes. |
| Integers | JSON body integers are **strict**: `"600"`, `60.5` or `true` → `422 validation_error` (query parameters are parsed from strings as usual). |
| Pagination | `?limit=&cursor=` → `{ "items": [...], "next_cursor": "opaque" \| null }`. |
| Concurrency | Mutable resources carry `revision` (int). Mutations send the expected `revision` in the body; mismatch → `409 revision_conflict` with the current resource in `details.current`. |
| Request id | Every response has header `X-Request-ID`; errors repeat it in the body. |

### 1.1 Error body

All non-2xx responses (except `204`) use:

```json
{
  "code": "validation_error",
  "message": "Человекочитаемое описание (ru)",
  "field_errors": [{ "field": "duration_seconds", "code": "out_of_range", "message": "…" }],
  "request_id": "b0c1…",
  "details": null
}
```

`field_errors` is `[]` when not applicable; `details` is an object or `null`.

| HTTP | `code` values |
|---|---|
| 400 | `bad_request`, `idempotency_key_required`, `invalid_idempotency_key` |
| 401 | `not_authenticated` (no/invalid session), `session_expired` (call `POST /auth/refresh`, then retry once), `invalid_credentials` (login only) |
| 403 | `csrf_failed`, `forbidden` (role/permission) |
| 404 | `not_found` (missing **or not yours** — other users' resources are indistinguishable from missing), `not_in_collection` |
| 409 | `revision_conflict`, `invalid_timer_state`, `idempotency_conflict`, `already_owned`, `prerequisite_missing`, `insufficient_balance`, `not_in_collection`, `activity_archived` |
| 413 | `payload_too_large` |
| 422 | `validation_error`, `future_date`, `duration_too_short`, `daily_total_exceeded`, `long_session_confirmation_required`, `session_too_long`, `not_scheduled`, `date_not_allowed`, `idempotency_key_reuse`, `wrong_activity_kind` |
| 429 | `rate_limited` (header `Retry-After` seconds) |
| 503 | `service_not_configured` (DB or Supabase settings missing; `details.missing` lists env names), `schema_missing` (migrations not applied), `auth_unavailable` (Supabase unreachable), `logout_incomplete` (logout could not revoke the session server-side; cookies were still cleared) |

### 1.2 Authentication and cookies

The backend talks to Supabase Auth server-side. The browser **never** receives Supabase tokens in
JSON and never stores tokens in `localStorage`. Cookies set by the backend:

| Cookie | HttpOnly | SameSite | Path | Purpose |
|---|---|---|---|---|
| `tfe_at` | yes | Lax | `/api` | Supabase access token (JWT), verified on every request |
| `tfe_rt` | yes | Strict | `/api/v1/auth` | Supabase refresh token |
| `tfe_csrf` | **no** | Strict | `/` | CSRF double-submit token (readable by JS) |

All cookies are `Secure` except when `APP_ENV=development` and `COOKIE_SECURE=false` (local http dev only).
Cookie lifetimes are 30 days; the access JWT inside `tfe_at` is short-lived (Supabase default 1 h) and
its `exp` is always verified, so an old cookie yields `401 session_expired`, never silent access.

**Client rule:** on `401 session_expired` call `POST /auth/refresh` once, then retry the original
request; if refresh fails (or the code is `not_authenticated`) show the login screen.

### 1.3 CSRF

Every unsafe request (`POST`, `PUT`, `PATCH`, `DELETE`) to `/api/v1/**` — **including login** — must
send header `X-CSRF-Token` equal to the `tfe_csrf` cookie value. Otherwise `403 csrf_failed`.
If an `Origin` header is present it must equal the origin of `APP_BASE_URL` (when configured).

Bootstrap: call `GET /api/v1/auth/csrf` once on app start (sets cookie, returns token). Login and
refresh return the (possibly rotated) token as well; always use the latest value.

### 1.4 Acting child (`X-Child-Id`)

The server derives the child from the session. MVP: one account = one child, so most clients never
send anything. A **guardian** may add header `X-Child-Id: <child uuid>` to act on a linked child;
any other value → `404 not_found`. Guardian links and the `guardian`/`admin` roles are assigned by
an operator in the database only (no API in MVP). Owner fields in bodies are never accepted.

### 1.5 Idempotency

Header `Idempotency-Key` (8–128 chars of `A-Z a-z 0-9 _ - : .`, e.g. a UUID v4).

- **Required** for `POST /activities/{id}/timer/{start|pause|reset|save}` and
  `POST /worlds/{theme_code}/purchases` (`400 idempotency_key_required`).
- Optional for `POST /activities/{id}/entries`.
- Scope is (user, **acting child**, key); stored for 24 h. Only successful (2xx) responses are stored.
  A guardian reusing a key for a different `X-Child-Id` gets a fresh execution for that child, never
  the other child's stored response.
- Same key + same method/path/body → the stored status and body are replayed with header
  `Idempotent-Replay: true`. Same key + different body → `422 idempotency_key_reuse`.
  Same key still in flight → `409 idempotency_conflict` (retry later with the same key).
- Generate a **new** key per user action; reuse the key only when retrying the same action
  (network error / timeout).

---

## 2. Shared objects

### 2.1 `Me`

```json
{
  "id": "uuid",
  "email": "child@example.com",
  "display_name": "Алексей",
  "grade": "3",
  "timezone": "Europe/Moscow",
  "theme": "system",
  "role": "child",
  "active_world": "settlers",
  "onboarding_version": 0,
  "rewards_started_on": "2026-10-06",
  "today": "2026-10-06",
  "acting_child_id": "uuid",
  "children": [],
  "permissions": { "can_confirm_quality": false, "can_manage_rewards_settings": false,
                   "can_edit_timezone": false, "can_set_workload": false,
                   "can_delete_reviewed_entries": false, "is_admin": false }
}
```

- `role`: `child` | `guardian` | `admin` (read-only; never set by clients).
- `theme`: `light` | `dark` | `system`. `grade`: string `"1"`–`"11"` or `null`.
- `onboarding_version`: `0` = wizard never completed/skipped; current wizard version is `1`.
- `children`: for guardians, `[{ "id": "uuid", "display_name": "…" }]`.
- `today`: today's local date in the acting child's timezone (use it instead of the browser date).
- `permissions.*` (except `is_admin`): true only when the actor is a guardian acting for a linked child
  (`X-Child-Id`). For a child: hide/lock quality confirmation, the timezone selector, the workload
  selector (always `normal`), editing time/date of reviewed entries and deleting them (note stays editable).

### 2.2 `Activity`

```json
{
  "id": "uuid",
  "code": "math",
  "name": "Математика",
  "icon": "∑",
  "kind": "timed",
  "category": "lesson",
  "objective": "decrease",
  "target_seconds": null,
  "sort_order": 10,
  "reward_eligible": true,
  "archived_at": null,
  "schedule": null,
  "revision": 1,
  "created_at": "…",
  "updated_at": "…",
  "timer": { "…": "TimerState, timed activities only; null for boolean" }
}
```

- `kind`: `timed` | `boolean` (boolean = chore with a checkbox).
- `category`: `lesson` | `walk` | `reading` | `custom` (timed) or `chore` (boolean).
- `objective`: `decrease` | `reach` | `maintain` | `none`.
- `target_seconds`: walk/reading reach target; for lessons an optional guardian floor (see §6.2).
- `code`: stable slug for provisioned defaults, `null` for user-created activities.
- `schedule` (boolean only): `null` = voluntary chore (no schedule), otherwise
  `{ "weekdays": [1,2,3,4,5], "starts_on": "2026-10-06", "ends_on": null }` — ISO weekdays,
  1 = Monday … 7 = Sunday. This is the schedule version effective today or the next future one.

**Default activities** (provisioned at first login, in this order):

| code | name | icon | kind | category | objective | target_seconds | reward_eligible |
|---|---|---|---|---|---|---|---|
| `math` | Математика | `∑` | timed | lesson | decrease | null | true |
| `russian` | Русский язык | `Аа` | timed | lesson | decrease | null | true |
| `literature` | Литературное чтение | `▤` | timed | lesson | decrease | null | true |
| `nature` | Окружающий мир | `❀` | timed | lesson | decrease | null | true |
| `english` | Английский язык | `En` | timed | lesson | decrease | null | true |
| `walk` | Прогулка | `☀` | timed | walk | reach | 7200 | true |
| `reading` | Внеклассное чтение | `▥` | timed | reading | reach | 1200 | false |
| `bag` | Собрать рюкзак на завтра | `null` | boolean | chore | none | null | true · weekdays 1–5 |
| `plants` | Полить цветы | `null` | boolean | chore | none | null | true · weekdays [5] |
| `room` | Навести порядок на столе | `null` | boolean | chore | none | null | true · daily 1–7 |
| `help` | Помочь дома | `null` | boolean | chore | none | null | false · voluntary (`schedule: null`) |

The default schedules start on the provisioning date.

### 2.3 `TimerState`

```json
{
  "activity_id": "uuid",
  "state": "running",
  "accumulated_ms": 600000,
  "running_since": "2026-10-06T09:00:00.000Z",
  "elapsed_ms": 645120,
  "session_started_at": "2026-10-06T08:40:00.000Z",
  "started_on": "2026-10-06",
  "long_session": "none",
  "revision": 7,
  "server_now": "2026-10-06T09:00:45.120Z"
}
```

- `state`: `idle` | `running` | `paused`. Idle timers have `accumulated_ms=0`, `elapsed_ms=0`, nulls.
- `elapsed_ms` = `accumulated_ms + (server_now − running_since)` when running. The UI should tick
  locally from `elapsed_ms` + (`Date.now()` − time of response); the server is the source of truth.
- `started_on`: local date the current session started (default date for save).
- `long_session`: `none` | `confirm` (elapsed > 4 h → save needs `confirm_long_session: true`)
  | `correct` (elapsed > 24 h → save needs an explicit `duration_seconds`).
- An activity that never had a timer reports `state: "idle", revision: 0`.

### 2.4 `TimeEntry`

```json
{
  "id": "uuid",
  "activity_id": "uuid",
  "activity_date": "2026-10-05",
  "duration_seconds": 1500,
  "source": "manual",
  "quality_status": "pending",
  "workload": "normal",
  "note": "",
  "revision": 1,
  "created_at": "…",
  "updated_at": "…"
}
```

- `source`: `timer` | `manual` (`timer` only via the timer `save` command).
- `quality_status`: `pending` | `confirmed` | `rejected` for lessons; `not_required` for other categories.
  Only a guardian changes it (§5.6).
- `workload`: `normal` | `increased` | `excluded` (excluded stays in charts/history, not in reward math).
  Only a guardian sets a non-`normal` value or changes it (child → `403 forbidden`).
- **Reviewed** = lesson entry with `quality_status` `confirmed` or `rejected`. For a child such an entry is
  frozen except `note`: changing `duration_seconds`/`activity_date`/`workload` or deleting it →
  `403 forbidden` (adult correction required). `pending`/`not_required` entries stay child-editable.
- `note`: ≤ 500 chars.

### 2.5 `ChoreItem`

```json
{
  "activity_id": "uuid",
  "code": "bag",
  "name": "Собрать рюкзак на завтра",
  "icon": null,
  "date": "2026-10-06",
  "scheduled": true,
  "voluntary": false,
  "due": true,
  "completed": false,
  "completed_at": null,
  "reward_eligible": true,
  "schedule": { "weekdays": [1,2,3,4,5], "starts_on": "2026-10-06", "ends_on": null }
}
```

- `voluntary`: chore without schedule (always checkable, never counts in the mandatory percentage).
- `scheduled`: has a schedule version active on `date` **and** `date`'s weekday is listed.
- `due` = `scheduled || voluntary`; non-due items are shown disabled (like the prototype).

---

## 3. Health and setup

### `GET /api/v1/health/live`
Always `200 {"status":"ok"}` while the process runs (works with no configuration).

### `GET /api/v1/health/ready`
`200` when DB reachable, schema applied and Supabase auth configured:
```json
{ "status": "ready", "checks": { "database": "ok", "schema": "ok", "auth": "configured" }, "setup": [] }
```
Otherwise `503` with the same shape, `status: "not_ready"`, checks such as
`"database": "not_configured" | "unreachable"`, `"schema": "missing" | "outdated" | "unknown"`,
`"auth": "not_configured"`, and `setup`: list of human-readable steps (no secret values).

When the DB/auth is not configured, every data endpoint returns `503 service_not_configured`
(`details.missing: ["DATABASE_URL", …]`). The server never creates the schema automatically.

---

## 4. Auth and profile

### `GET /auth/csrf`
→ `200 {"csrf_token": "…"}` and sets `tfe_csrf`. No auth required.

### `POST /auth/login`
Body `{"email": "…", "password": "…"}` (CSRF header required).
→ `200 {"me": Me, "csrf_token": "…"}`; sets `tfe_at`, `tfe_rt`, rotates `tfe_csrf`.
On first successful login the server provisions the profile (role `child`), default activities,
default schedules, wallet (balance 0) and the first world (`settlers`, active). Provisioning is
idempotent and never trusts client-supplied roles or Supabase `user_metadata` for permissions.
Errors: `401 invalid_credentials` (same message for unknown email and wrong password),
`429 rate_limited`, `503 service_not_configured | auth_unavailable`.

Accounts are created by an adult/operator in Supabase (dashboard invite or Admin API). Sign-up,
password recovery and child accounts without email are **not in this MVP**.

### `POST /auth/refresh`
No body. Uses `tfe_rt`. → `200 {"csrf_token": "…", "expires_at": "…"}` and new cookies.
`401 session_expired` (cookies cleared) when the refresh token is invalid, was revoked by a logout, or
belongs to a logged-out session → show login.

### `POST /auth/logout`
Body optional `{"pause_running_timers": true}` (default `true`, matching the prototype).
Order: (1) **local revocation** of the session in the database — Supabase `session_id`, access-token
hash and refresh-token hash — independent of Supabase availability; (2) pause this user's running
timers; (3) best-effort Supabase `/logout`; (4) clear all cookies — **always**, whatever the outcome.
- `204` = the session was revoked and the revocation is **committed** (also for an expired access token
  with a valid signature), or there was no verifiable session to revoke (no cookie / forged token).
- `503 logout_incomplete` = a genuine session could not be revoked server-side (database unavailable or
  write failed, or the token could not be verified because Supabase JWKS is unreachable). Cookies of this
  browser are cleared anyway; show the Russian `message` (the session may still work from a copied
  cookie until it expires; suggest signing in and out again later). Supabase `/logout` is still attempted.

After a `204` any copy of the old cookies gets `401 not_authenticated` (API) / `401 session_expired`
(refresh), even before the JWT's own expiry. A new login creates a new session.

### `GET /me` → `200 Me`
### `PATCH /me`
Body (all optional): `{"display_name": "1–40 chars", "grade": "3" | null, "timezone": "Europe/Moscow",
"theme": "dark", "onboarding_version": 1}`. Unknown fields → `422`. Invalid IANA zone → `422`.
`onboarding_version` can only increase. → `200 Me`.
Changing `timezone` is **guardian-only** (`403 forbidden` for a child; re-sending the current value is
accepted): the zone defines the child's "today" for chores and entries.

When a guardian acts with `X-Child-Id`, `PATCH /me` changes the **child's** `display_name`, `grade`,
`timezone`, `onboarding_version`, while `theme` stays a per-account UI preference of the actor.

### `PUT /me/active-world`
Body `{"theme_code": "voxel"}` → `200 {"active_world": "voxel"}`. Theme must be in the user's
collection (`409 not_in_collection`); unknown code → `404 not_found`.

---

## 5. Activities, timers, entries, chores

### `GET /activities?include_archived=false` → `200 {"items": [Activity]}`
Ordered by `sort_order`, then `created_at`. Each timed activity embeds its `timer`.

### `GET /activities/{id}` → `200 Activity`

### `POST /activities` → `201 Activity`
```json
{ "name": "Покормить кота", "kind": "boolean", "icon": null,
  "schedule": { "weekdays": [1,3,5], "starts_on": "2026-10-07" } }
```
- `name` 1–70 chars (trimmed). `icon` ≤ 4 chars or null.
- `kind: "timed"` → `category: "custom"`; optional `objective` (`none` default | `reach` | `maintain`)
  and `target_seconds` (60–86400, required for `reach`/`maintain`). `schedule` must be absent.
- `kind: "boolean"` → `category: "chore"`; `schedule` optional (`null`/absent = voluntary).
  `starts_on` ≥ today; `ends_on` optional ≥ `starts_on`; `weekdays` non-empty, unique, 1–7.
- Activities created by a child have `reward_eligible: false`; guardian-created ones `true`.
- Optional `sort_order` (0–100000, default 1000 → after the defaults).

### `PATCH /activities/{id}` → `200 Activity`
Body `{"revision": 3, ...}` with any of `name`, `icon`, `sort_order`, `objective`, `target_seconds`,
`archived` (bool), `schedule` (`{weekdays, starts_on, ends_on?}` — boolean activities only),
`reward_eligible` (guardian only).
- **Protected fields** — `objective`, `target_seconds`, `schedule`, `archived`, `reward_eligible` — on
  default activities (`code != null`) or `reward_eligible` activities require a guardian (`403 forbidden`).
  A child may change everything on its own non-reward-eligible custom activities.
- Schedule change creates a new version from `starts_on` (must be ≥ today, default today); the previous
  version ends the day before. Past days keep their old schedule (achievement denominators are not
  rewritten). `schedule: null` is rejected — archive the chore instead. A child-created voluntary chore
  becomes scheduled by sending a schedule.
- Archiving a timed activity whose timer is running/paused → `409 invalid_timer_state` (save or reset first).
  Archiving a chore ends its schedule after today.
- Archiving keeps all history; archived activities reject timer commands and new entries
  (`409 activity_archived`). `archived: false` restores.

### Timers

#### `GET /timers` → `200 {"items": [TimerState]}` — all non-idle timers of the acting child.
#### `GET /activities/{id}/timer` → `200 TimerState` (boolean activity → `422 wrong_activity_kind`).

#### `POST /activities/{id}/timer/start` · `pause` · `reset`
Headers `X-CSRF-Token`, `Idempotency-Key`. Body `{"revision": 7}`.

| command | allowed from | effect |
|---|---|---|
| `start` | idle, paused | `running_since=now`; from idle also sets `session_started_at`, `started_on` |
| `pause` | running | `accumulated_ms += now − running_since` |
| `reset` | running, paused | back to idle, discards unsaved time |

→ `200 {"timer": TimerState, "other_running": [{"activity_id": "uuid", "name": "Русский язык", "elapsed_ms": 900000}]}`
(`other_running` only non-empty for `start` — show the overlap warning and offer to pause; the server
never pauses other timers silently). Wrong state → `409 invalid_timer_state` with
`details.current: TimerState`. Stale revision → `409 revision_conflict` with `details.current`.

#### `POST /activities/{id}/timer/save`
```json
{ "revision": 8, "activity_date": "2026-10-06", "confirm_long_session": false,
  "duration_seconds": null, "note": "", "workload": "normal" }
```
Allowed from running or paused. In **one transaction**: freezes elapsed time, creates a `timer`
entry, resets this timer to idle. On DB failure nothing changes (draft keeps its time).
- `activity_date` default = `started_on`; must satisfy `started_on ≤ activity_date ≤ today` (`422 date_not_allowed`).
- Elapsed < 1 s → `422 duration_too_short`.
- Elapsed > 4 h requires `confirm_long_session: true` (`422 long_session_confirmation_required`).
- Elapsed > 24 h requires `duration_seconds` (1–86400 and ≤ elapsed) — `422 session_too_long`.
- `duration_seconds` may also be used to reduce a forgotten timer; it can never exceed elapsed.
- The day's total for that activity may not exceed 86400 s (`422 daily_total_exceeded`).

→ `201 {"timer": TimerState, "entry": TimeEntry}`.
Two devices saving with the same revision: one gets `201`, the other `409 revision_conflict`; exactly one entry.

### Time entries (all-time history)

#### `GET /activities/{id}/entries?limit=50&cursor=` → `200 {"items": [TimeEntry], "next_cursor": …}`
Newest `activity_date` first (then newest `created_at`). `limit` 1–200. Includes all dates ever recorded.

#### `GET /activities/{id}/daily-totals` → `200`
```json
{ "activity_id": "uuid", "points": [ { "date": "2026-06-01", "seconds": 1800, "entries": 2 } ] }
```
All-time, ascending, **only dates with entries** (no zero-filling), multiple entries summed.
Use directly for the line chart.

#### `POST /activities/{id}/entries` → `201 TimeEntry`
`{"activity_date": "2026-10-05", "duration_seconds": 1500, "note": "", "workload": "normal"}`
- Timed activities only. `duration_seconds` 60–86400. Date ≤ today (`422 future_date`), ≥ 2000-01-01.
- A child may only send `workload: "normal"` (default); other values → `403 forbidden`. Same for timer `save`.
- Does not touch the timer draft. Another entry for the same date is a new row (charts sum them).
- `daily_total_exceeded` as above.

#### `PATCH /entries/{id}` → `200 TimeEntry`
`{"revision": 1, "activity_date"?, "duration_seconds"?, "note"?, "workload"?}` — same validation;
audit-logged (the audit stores the note length, not its text). Manual entries keep ≥ 60 s; timer entries
may be edited to 1–86400 s. Child on a reviewed entry: only `note` (see §2.4) — otherwise `403 forbidden`.
A guardian's edit keeps the existing `quality_status`.

#### `DELETE /entries/{id}?revision=1` → `204`
Soft delete with audit; disappears from history, charts and reward math. Reviewed lesson entries can be
deleted only by a guardian (`403 forbidden` for a child).

#### `PUT /entries/{id}/quality` (guardian only) → `200 TimeEntry`
`{"revision": 1, "quality_status": "confirmed"}` — `confirmed` | `rejected` | `pending`. Lessons only.

### Chores

#### `GET /chores?date=2026-10-06` → `200`
```json
{ "date": "2026-10-06",
  "items": [ChoreItem],
  "summary": { "scheduled_total": 2, "scheduled_completed": 1, "voluntary_completed": 0 } }
```
`date` defaults to today; any date allowed for reading. Archived chores are excluded.

#### `PUT /chores/{activity_id}/completions/{date}` → `200 ChoreItem`
Body `{"completed": true}`. Idempotent: repeating `true` keeps one completion; `false` removes it.
false→true→false→true never creates duplicates or extra rewards.
- Child: `date` must be today (`422 date_not_allowed`). Guardian: any date ≤ today.
- Scheduled chore on a non-scheduled date → `422 not_scheduled`. Archived → `409 activity_archived`.
- Voluntary completions never grant immediate stars in MVP.

### Walk day statuses

#### `GET /day-statuses?category=walk&from=&to=` → `200 {"items": [{"date": "…", "status": "no_walk"}]}`
Defaults: `to` = today, `from` = `to` − 27 days; range ≤ 366 days. Only days with a status are listed.
#### `PUT /day-statuses/walk/{date}` → `200 {"date": "…", "status": "no_walk" | "excluded" | null}`
Body `{"status": "no_walk"}`; `null` clears. `no_walk` — child or guardian; `excluded` (illness,
vacation) — guardian only. Date ≤ today. A day with walk entries counts as recorded regardless.

---

## 6. Dashboard, analytics, rewards, wallet

### `GET /dashboard` → `200`
```json
{
  "today": "2026-10-06",
  "timezone": "Europe/Moscow",
  "display_name": "Алексей",
  "balance": 145,
  "walk": { "activity_id": "uuid", "today_seconds": 3600, "target_seconds": 7200 },
  "chores": { "date": "2026-10-06", "items": [ChoreItem], "summary": { "…": "as /chores" } },
  "timers": [TimerState],
  "world": { "active_world": "settlers", "name": "Тихая бухта", "level": 1,
             "next_upgrade": { "code": "workshop", "title": "Ветряная пекарня", "cost": 90 } },
  "rewards": { "next_evaluation_on": "2026-10-20", "preview_total": 28 }
}
```
`timers` lists non-idle timers. `next_upgrade` is `null` when the world is complete.

### `GET /analytics/time`
Query: `bucket=week|day` (default `week`), `group_by=category|activity` (default `category`),
`weeks=4|8|12` (week bucket, default 4, any 1–52 accepted; ends with the current week),
`from`,`to` (day bucket; required; ≤ 366 days).

```json
{
  "timezone": "Europe/Moscow", "bucket": "week", "group_by": "category",
  "from": "2026-09-14", "to": "2026-10-11",
  "series": [ { "key": "lessons", "label": "Уроки" }, { "key": "walk", "label": "Прогулки" },
              { "key": "other", "label": "Другие занятия" } ],
  "buckets": [ { "start": "2026-09-14", "end": "2026-09-20", "complete": true,
                 "totals": { "lessons": 9000, "walk": 25200, "other": 1200 }, "total_seconds": 35400 } ],
  "totals": { "lessons": 36000, "walk": 99000, "other": 4800 },
  "total_seconds": 139800
}
```
- Weeks are Monday–Sunday in the child's timezone; `complete: false` marks the current week
  (and any bucket ending after today). Every bucket is present (zero totals allowed per bucket,
  this is a bar chart, not the line chart).
- `group_by=activity`: series keys are activity UUIDs, labels are names (archived included).
- Category mapping: `lesson` → `lessons`, `walk` → `walk`, `reading`/`custom` → `other`.
- `totals` over the whole range feed the donut (share of tracked time, not of 24 h).

### `GET /rewards` → `200` (read-only, never changes the balance)
```json
{
  "policy_version": 1,
  "mode": "deterministic",
  "rewards_started_on": "2026-10-06",
  "first_evaluation_on": "2026-10-20",
  "next_evaluation_on": "2026-10-20",
  "preview": {
    "as_of": "2026-10-06",
    "window": { "start": "2026-09-29", "end": "2026-10-05" },
    "baseline": { "start": "2026-09-22", "end": "2026-09-28" },
    "categories": [CategoryResult],
    "total": 28
  },
  "evaluations": [ {
    "period_end": "2026-10-19",
    "window": { "start": "2026-10-13", "end": "2026-10-19" },
    "baseline": { "start": "2026-10-06", "end": "2026-10-12" },
    "categories": [ CategoryResult + { "state": "final" | "deferred", "evaluated_at": "…" } ],
    "total_awarded": 28
  } ]
}
```
`CategoryResult`:
```json
{ "category": "chores", "status": "eligible", "amount": 28, "reason_code": "chores_all_done",
  "explanation": "Выполнено 10 из 10 запланированных дел.", "facts": { "scheduled": 10, "completed": 10 } }
```
- `category`: `lessons` | `walk` | `chores` (reading/custom goals, voluntary instant rewards and AI mode
  are not in this MVP).
- `status`: `eligible` (amount > 0) | `no_reward` | `insufficient_data` | `awaiting_data`.
- `facts` per category:
  - lessons: `{"subjects": [{"activity_id", "name", "status", "baseline_days", "current_days",
    "baseline_median_seconds", "current_median_seconds", "progress_percent", "amount"}], "cap": 100}`;
    subject `status`: `eligible` | `no_progress` | `insufficient_data` | `awaiting_data` | `below_floor`.
    Medians/progress are `null` unless both weeks have ≥ 3 comparable days.
  - walk: `{"target_seconds", "included_days", "recorded_days", "goal_days", "required_goal_days",
    "mean_ratio", "baseline_mean_ratio", "missing_dates": []}`
  - chores: `{"scheduled", "completed", "completion_days", "required_days"}`
- `evaluations`: last 10 periods, newest first. Rules are in §8.

### `POST /rewards/evaluate` → `200`
No body. Evaluates **only due periods** of the acting child (deterministic, idempotent; never an
arbitrary payout). Safe to call on every app start. Returns
`{"processed": [{"period_end": "…", "category": "walk", "state": "final", "amount": 40}], "balance": 185}`.
Repeated calls, retries and restarts never pay a period/category twice.

### `GET /wallet?limit=50&cursor=` → `200`
```json
{ "balance": 145,
  "items": [ { "id": "uuid", "amount": -90, "balance_after": 55, "reason_code": "world_purchase",
               "description": "Тихая бухта · Ветряная пекарня", "source_type": "world_unlock",
               "source_id": "uuid", "period_end": null, "created_at": "…" } ],
  "next_cursor": null }
```
`reason_code`: `reward_lessons` | `reward_walk` | `reward_chores` | `world_purchase` | `adjustment`.
Newest first. The ledger is append-only; the balance never goes negative.

---

## 7. Worlds

`WorldTheme`:
```json
{ "code": "settlers", "name": "Тихая бухта", "type": "Поселенцы и путешественники",
  "badge": "ПРИРОДА", "color": "#3ca781", "resource": "Дерево и плоды",
  "inhabitants_label": "поселенцев", "upgrades_total": 4 }
```
Theme codes: `settlers`, `bricks`, `voxel`, `helpers` (same as `prototype/worlds.js`; emblems/scenes
stay in the frontend art module keyed by these codes). Upgrade codes, identical for every theme:
`meadow` (60, no prerequisite) → `workshop` (90, requires `meadow`) → `harbor` (120, requires
`workshop`) → `beacon` (180, requires `harbor`). Titles/effects are per theme.

### `GET /world-catalog?search=&cursor=` → `200`
`{"items": [WorldTheme + {"in_collection": true, "level": 1}], "next_cursor": null}` — case-insensitive
search over name and type.

### `GET /worlds` → `200`
```json
{ "active_world": "settlers", "balance": 145,
  "items": [ WorldTheme + { "position": 0, "added_at": "…", "level": 1, "unlocked": ["meadow"],
                            "next_upgrade": { "code": "workshop", "title": "Ветряная пекарня", "cost": 90 } } ] }
```
`items` = the user's collection in shelf order (new profiles: only `settlers`).

### `POST /worlds` → `201` (added) or `200` (already in collection)
Body `{"theme_code": "bricks"}` → `{"item": <collection item as above>, "created": true}`. Free.

### `GET /worlds/{theme_code}` → `200 WorldDetail`
```json
{
  "theme": WorldTheme, "level": 1, "territories": 2, "inhabitants": 4, "balance": 145,
  "upgrades": [ { "code": "meadow", "index": 0, "title": "Лесная поляна", "effect": "Туман рассеется: …",
                  "kind": "Открытие территории", "space": "+1 территория · +2 жителя", "cost": 60,
                  "requires": null, "owned": true, "purchased_at": "…", "can_purchase": false,
                  "blocked_reason": "already_owned" } ],
  "events": [ { "id": "uuid", "upgrade_code": "meadow", "event_type": "upgrade_unlocked",
                "text": "Туман рассеется: …", "created_at": "…" } ]
}
```
`territories = 1 + (level≥1) + (level≥3)`, `inhabitants = 2 + 2·level`. `blocked_reason`:
`null` | `already_owned` | `prerequisite_missing` | `insufficient_balance`. Theme not in collection →
`404 not_in_collection`. Preview stages 0–4 are a pure frontend feature (no API).

### `POST /worlds/{theme_code}/purchases` → `201`
Headers `X-CSRF-Token`, `Idempotency-Key`. Body `{"upgrade_code": "workshop"}` — price, prerequisites
and effects come from the server only.
→ `{"purchase": {"id": "uuid", "upgrade_code": "workshop", "cost": 90, "purchased_at": "…",
"transaction_id": "uuid"}, "balance": 55, "world": WorldDetail}`.
One DB transaction: lock wallet → check collection, ownership, prerequisite, balance → append ledger
row → update balance → unlock → event. Errors: `409 already_owned | prerequisite_missing |
insufficient_balance`, `404 not_in_collection` (theme not added yet), `404 not_found` (unknown
theme/upgrade). Concurrent
purchases can never make the balance negative or unlock twice. Show a confirmation dialog first.

---

## 8. Reward policy v1 (deterministic, what the server computes)

- Anchor `A = rewards_started_on` (profile provisioning date). Final evaluation dates
  `D_k = A + 14 + 7k`. For date D: window `[D−7, D−1]`, baseline `[D−14, D−8]`. Preview uses
  D = today (window ends yesterday). Unique `(child, period_end, category)` prevents double payment.
- `deferred`: a category with `awaiting_data` (unconfirmed lesson entries, missing walk days) is
  retried on later evaluate calls; 7 days after D it is finalised with what exists
  (unconfirmed/missing data never counts as progress) and amount per the rules.
- **Lessons** (per `lesson` activity, reward-eligible): a day counts when it has entries and all
  of that day's entries are `confirmed` with `workload` = `normal`. Pending entries in either range →
  `awaiting_data`. Need ≥ 3 counted days in both ranges. B/C = medians of daily seconds;
  `p = (B−C)/B`. p ≥ 15% → 30, ≥ 10% → 20, ≥ 5% → 10, else 0. If a lesson `target_seconds` (floor)
  is set and C < floor → 0 with `reason_code: below_floor`. Sum capped at 100.
- **Walk** (target = walk activity `target_seconds`, default 7200): each window day is
  recorded (entries > 0) / `no_walk` (counts as 0) / `excluded` / missing. Missing → `awaiting_data`.
  E = included days ≥ 5, else `insufficient_data`. r_d = min(seconds/target, 1); K = goal days.
  K ≥ ceil(5E/7) → 40. Else if baseline has E ≥ 5 without missing, R − R_base ≥ 0.10, R ≥ 0.60 and
  ≥ 4 recorded days → 20. Else 0.
- **Chores** (reward-eligible scheduled chores): N = scheduled instances in the window from the
  schedule versions valid on each date; C = completions of those instances. N = 0 →
  `insufficient_data`. C/N < 0.6 → 0. Completions must fall on ≥ min(3, days with scheduled chores)
  distinct days. Amount `floor(20C/N) + min(15, floor(C/3)) + (C=N ? 5 : 0)`, max 40.
- Explanations are fixed Russian templates (no AI in MVP).

---

## 9. Settings (read-only in MVP)

### `GET /settings` → `200`
```json
{
  "app": { "env": "production", "version": "0.1.0" },
  "integrations": {
    "database": { "configured": true },
    "supabase_auth": { "configured": true },
    "openai": { "configured": false }
  },
  "rewards": { "policy_version": 1, "mode": "deterministic", "ai_available": false },
  "deferred": ["admin_connections_write", "ai_assisted_rewards", "signup", "password_recovery",
               "guardian_management", "wallet_adjustments", "chore_exceptions"]
}
```
Never returns secret values, URLs with credentials or key suffixes. `PATCH /settings` and
`/admin/connections` are **not implemented** in this MVP (phase 5 per spec).

---

## 10. Not in this MVP (explicitly deferred)

AI-assisted rewards; admin `.env` writes; sign-up / password recovery / child login without email;
guardian linking API (operator SQL only); wallet adjustments API; chore schedule exceptions
(vacation/illness for chores; walks use `excluded` day status); reading/custom goal rewards and
voluntary instant rewards; data export/deletion; audit-log read API. Their absence is reflected in
`GET /settings → deferred`.
