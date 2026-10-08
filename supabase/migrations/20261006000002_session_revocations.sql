-- «Всё успею» — local session revocation on logout (version 20261006000002).
--
-- Access tokens are verified locally (JWKS), so a captured, unexpired token would stay usable after
-- logout. The backend records revocations here (before calling Supabase /logout, which may fail) and
-- checks them on every request and on refresh. Keys hold no secrets: `sid:<session_id claim>`,
-- `at:<sha256(access token)>`, `rt:<sha256(refresh token)>`.
-- Internal table: RLS on, no policies, no Data API grants.

create table public.revoked_sessions (
  key        text primary key constraint revoked_sessions_key_check
             check (key ~ '^(sid:[A-Za-z0-9-]{1,128}|at:[0-9a-f]{64}|rt:[0-9a-f]{64})$'),
  user_id    uuid not null,
  kind       text not null constraint revoked_sessions_kind_check
             check (kind in ('session','access_token','refresh_token')),
  revoked_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index revoked_sessions_expires_idx on public.revoked_sessions (expires_at);
create index revoked_sessions_user_idx on public.revoked_sessions (user_id);

alter table public.revoked_sessions enable row level security;
revoke all on table public.revoked_sessions from anon, authenticated;

insert into public.app_schema_migrations (version) values ('20261006000002');
