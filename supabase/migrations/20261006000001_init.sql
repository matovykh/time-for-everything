-- «Всё успею» — initial application schema (version 20261006000001).
--
-- Applies to an external Supabase project (PostgreSQL 15+). Creates ONLY objects in schema
-- `public` that belong to the application. It never modifies `auth`, `storage` or other
-- Supabase-managed schemas; `profiles.id` merely references `auth.users(id)`.
--
-- Access model:
--   * The FastAPI backend connects with the DATABASE_URL role and enforces ownership
--     (child_id) explicitly in every query (tested). If that role owns the tables it bypasses RLS.
--   * RLS is enabled on every table. The Supabase Data API roles get at most SELECT on the
--     acting user's own/linked-child rows; `anon` gets nothing; nobody writes through the Data API.
--   * Ledger rows are immutable (trigger) and final reward evaluations cannot be changed.
--
-- Apply with: python scripts/db_migrate.py --apply   (one transaction per file; records the version)
-- or:         psql "$DATABASE_URL" --single-transaction -v ON_ERROR_STOP=1 -f <this file>
--
-- Deleting a child's data is a separate, explicit procedure (ledger rows are append-only):
--   begin; set local tfe.allow_ledger_delete = 'on'; delete from public.profiles where id = '<uuid>'; commit;
-- then delete the auth user via the Supabase dashboard / Admin API (never by editing auth.users).

create table if not exists public.app_schema_migrations (
  version    text primary key,
  applied_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- reference data tables
create table public.world_themes (
  code       text primary key check (code ~ '^[a-z0-9_-]{1,32}$'),
  name       text not null,
  sort_order integer not null,
  version    integer not null default 1
);

create table public.world_catalog (
  id            uuid primary key default gen_random_uuid(),
  theme_code    text not null references public.world_themes(code),
  code          text not null check (code ~ '^[a-z0-9_-]{1,32}$'),
  position      integer not null,
  cost          integer not null check (cost >= 0),
  requires_code text,
  version       integer not null default 1,
  constraint world_catalog_theme_code_key unique (theme_code, code),
  constraint world_catalog_requires_fkey foreign key (theme_code, requires_code)
    references public.world_catalog (theme_code, code)
);

create table public.reward_policies (
  version        integer primary key,
  parameters     jsonb not null,
  effective_from date not null,
  created_at     timestamptz not null default now()
);

-- ---------------------------------------------------------------- accounts
create table public.profiles (
  id                 uuid primary key references auth.users (id) on delete cascade,
  email              text,
  display_name       text not null constraint profiles_display_name_check check (char_length(display_name) between 1 and 40),
  grade              text check (grade is null or grade ~ '^([1-9]|1[01])$'),
  role               text not null default 'child' constraint profiles_role_check check (role in ('child','guardian','admin')),
  timezone           text not null default 'Europe/Moscow',
  theme              text not null default 'system' constraint profiles_theme_check check (theme in ('light','dark','system')),
  active_world       text references public.world_themes (code),
  onboarding_version integer not null default 0 constraint profiles_onboarding_check check (onboarding_version >= 0),
  rewards_started_on date not null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  revision           integer not null default 1
);

create table public.guardian_children (
  guardian_id uuid not null references public.profiles (id) on delete cascade,
  child_id    uuid not null references public.profiles (id) on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (guardian_id, child_id),
  constraint guardian_children_distinct check (guardian_id <> child_id)
);
create index guardian_children_child_idx on public.guardian_children (child_id);

-- ---------------------------------------------------------------- activities & schedules
create table public.activities (
  id             uuid primary key default gen_random_uuid(),
  child_id       uuid not null references public.profiles (id) on delete cascade,
  code           text,
  name           text not null constraint activities_name_check check (char_length(name) between 1 and 70),
  icon           text check (icon is null or char_length(icon) <= 8),
  kind           text not null constraint activities_kind_check check (kind in ('timed','boolean')),
  category       text not null,
  objective      text not null default 'none'
                 constraint activities_objective_check check (objective in ('decrease','reach','maintain','none')),
  target_seconds integer constraint activities_target_check check (target_seconds is null or target_seconds between 60 and 86400),
  sort_order     integer not null default 100,
  reward_eligible boolean not null default false,
  archived_at    timestamptz,
  created_by     uuid,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  revision       integer not null default 1,
  constraint activities_id_child_key unique (id, child_id),
  constraint activities_child_code_key unique (child_id, code),
  constraint activities_kind_category_check check (
    (kind = 'timed' and category in ('lesson','walk','reading','custom')) or (kind = 'boolean' and category = 'chore'))
);
create index activities_child_idx on public.activities (child_id, sort_order);

create table public.schedules (
  id            uuid primary key default gen_random_uuid(),
  child_id      uuid not null,
  activity_id   uuid not null,
  weekdays_mask integer not null constraint schedules_mask_check check (weekdays_mask between 1 and 127),
  starts_on     date not null,
  ends_on       date,
  created_by    uuid,
  created_at    timestamptz not null default now(),
  constraint schedules_range_check check (ends_on is null or ends_on >= starts_on),
  foreign key (activity_id, child_id) references public.activities (id, child_id) on delete cascade
);
create index schedules_activity_idx on public.schedules (activity_id, starts_on);
create index schedules_child_idx on public.schedules (child_id);

create table public.chore_completions (
  id           uuid primary key default gen_random_uuid(),
  child_id     uuid not null,
  activity_id  uuid not null,
  local_date   date not null,
  scheduled    boolean not null,
  completed_at timestamptz not null default now(),
  actor_id     uuid,
  constraint chore_completions_activity_date_key unique (activity_id, local_date),
  foreign key (activity_id, child_id) references public.activities (id, child_id) on delete cascade
);
create index chore_completions_child_date_idx on public.chore_completions (child_id, local_date);

-- ---------------------------------------------------------------- timers & entries
create table public.timer_drafts (
  id                 uuid primary key default gen_random_uuid(),
  child_id           uuid not null,
  activity_id        uuid not null,
  state              text not null default 'idle' constraint timer_drafts_state_check check (state in ('idle','running','paused')),
  accumulated_ms     bigint not null default 0 constraint timer_drafts_accumulated_check check (accumulated_ms >= 0),
  running_since      timestamptz,
  session_started_at timestamptz,
  started_on         date,
  revision           integer not null default 0,
  updated_at         timestamptz not null default now(),
  constraint timer_drafts_child_activity_key unique (child_id, activity_id),
  constraint timer_drafts_running_since_check check ((state = 'running') = (running_since is not null)),
  constraint timer_drafts_idle_check check (state <> 'idle' or (accumulated_ms = 0 and session_started_at is null)),
  foreign key (activity_id, child_id) references public.activities (id, child_id) on delete cascade
);
create index timer_drafts_child_state_idx on public.timer_drafts (child_id, state);

create table public.time_entries (
  id               uuid primary key default gen_random_uuid(),
  child_id         uuid not null,
  activity_id      uuid not null,
  activity_date    date not null,
  duration_seconds integer not null constraint time_entries_duration_check check (duration_seconds between 1 and 86400),
  source           text not null constraint time_entries_source_check check (source in ('timer','manual')),
  quality_status   text not null
                   constraint time_entries_quality_check check (quality_status in ('pending','confirmed','rejected','not_required')),
  workload         text not null default 'normal'
                   constraint time_entries_workload_check check (workload in ('normal','increased','excluded')),
  note             text not null default '' constraint time_entries_note_check check (char_length(note) <= 500),
  deleted_at       timestamptz,
  created_by       uuid,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  revision         integer not null default 1,
  foreign key (activity_id, child_id) references public.activities (id, child_id) on delete cascade
);
create index time_entries_child_date_idx on public.time_entries (child_id, activity_date);
create index time_entries_activity_date_idx on public.time_entries (activity_id, activity_date);

create table public.day_statuses (
  child_id   uuid not null references public.profiles (id) on delete cascade,
  category   text not null constraint day_statuses_category_check check (category in ('walk')),
  local_date date not null,
  status     text not null constraint day_statuses_status_check check (status in ('no_walk','excluded')),
  set_by     uuid,
  updated_at timestamptz not null default now(),
  primary key (child_id, category, local_date)
);

-- ---------------------------------------------------------------- wallet & rewards
create table public.wallet_accounts (
  child_id   uuid primary key references public.profiles (id) on delete cascade,
  balance    integer not null default 0 constraint wallet_accounts_balance_check check (balance >= 0),
  updated_at timestamptz not null default now()
);

create table public.wallet_transactions (
  id              uuid primary key default gen_random_uuid(),
  child_id        uuid not null references public.wallet_accounts (child_id) on delete cascade,
  seq             integer not null constraint wallet_transactions_seq_check check (seq >= 1),
  amount          integer not null constraint wallet_transactions_amount_check check (amount <> 0),
  balance_after   integer not null constraint wallet_transactions_balance_after_check check (balance_after >= 0),
  reason_code     text not null constraint wallet_transactions_reason_check
                  check (reason_code in ('reward_lessons','reward_walk','reward_chores','world_purchase','adjustment')),
  description     text not null default '',
  source_type     text,
  source_id       uuid,
  period_end      date,
  idempotency_key text not null unique,
  created_by      uuid,
  created_at      timestamptz not null default now(),
  constraint wallet_transactions_child_seq_key unique (child_id, seq)
);
create index wallet_transactions_child_created_idx on public.wallet_transactions (child_id, created_at);

create table public.reward_evaluations (
  id                    uuid primary key default gen_random_uuid(),
  child_id              uuid not null references public.profiles (id) on delete cascade,
  policy_version        integer not null references public.reward_policies (version),
  category              text not null constraint reward_evaluations_category_check check (category in ('lessons','walk','chores')),
  period_end            date not null,
  window_start          date not null,
  window_end            date not null,
  baseline_start        date not null,
  baseline_end          date not null,
  state                 text not null constraint reward_evaluations_state_check check (state in ('deferred','final')),
  status                text not null,
  amount                integer not null default 0 constraint reward_evaluations_amount_check check (amount >= 0),
  reason_code           text not null,
  explanation           text not null,
  snapshot              jsonb not null,
  mode                  text not null default 'deterministic'
                        constraint reward_evaluations_mode_check check (mode in ('deterministic','ai_assisted')),
  wallet_transaction_id uuid references public.wallet_transactions (id),
  evaluated_at          timestamptz not null default now(),
  finalized_at          timestamptz,
  -- one result per child, period and category, independent of policy version or mode
  constraint reward_evaluations_period_key unique (child_id, period_end, category)
);

-- ---------------------------------------------------------------- worlds
create table public.child_worlds (
  id         uuid primary key default gen_random_uuid(),
  child_id   uuid not null references public.profiles (id) on delete cascade,
  theme_code text not null references public.world_themes (code),
  position   integer not null,
  added_at   timestamptz not null default now(),
  constraint child_worlds_child_theme_key unique (child_id, theme_code),
  constraint child_worlds_identity_key unique (id, child_id, theme_code)
);

create table public.world_unlocks (
  id             uuid primary key default gen_random_uuid(),
  child_id       uuid not null,
  child_world_id uuid not null,
  theme_code     text not null,
  upgrade_code   text not null,
  cost           integer not null constraint world_unlocks_cost_check check (cost >= 0),
  transaction_id uuid not null unique references public.wallet_transactions (id),
  purchased_at   timestamptz not null default now(),
  constraint world_unlocks_world_upgrade_key unique (child_world_id, upgrade_code),
  -- owner and theme must match the collection entry; upgrade must belong to the same theme
  foreign key (child_world_id, child_id, theme_code)
    references public.child_worlds (id, child_id, theme_code) on delete cascade,
  foreign key (theme_code, upgrade_code) references public.world_catalog (theme_code, code)
);
create index world_unlocks_child_idx on public.world_unlocks (child_id);

create table public.world_events (
  id             uuid primary key default gen_random_uuid(),
  child_id       uuid not null,
  child_world_id uuid not null,
  theme_code     text not null,
  upgrade_code   text not null,
  event_type     text not null default 'upgrade_unlocked',
  created_at     timestamptz not null default now(),
  foreign key (child_world_id, child_id, theme_code)
    references public.child_worlds (id, child_id, theme_code) on delete cascade
);
create index world_events_world_idx on public.world_events (child_world_id, created_at);

-- ---------------------------------------------------------------- audit & idempotency
create table public.audit_events (
  id          uuid primary key default gen_random_uuid(),
  actor_id    uuid,
  child_id    uuid,
  action      text not null,
  target_type text not null,
  target_id   text,
  before      jsonb,
  after       jsonb,
  created_at  timestamptz not null default now()
);
create index audit_events_child_idx on public.audit_events (child_id, created_at);

create table public.idempotency_requests (
  actor_id     uuid not null,
  key          text not null,
  request_hash text not null,
  status_code  integer not null,
  response     jsonb not null,
  created_at   timestamptz not null default now(),
  expires_at   timestamptz not null,
  primary key (actor_id, key)
);
create index idempotency_requests_expires_idx on public.idempotency_requests (expires_at);

-- ---------------------------------------------------------------- integrity triggers
create or replace function public.tfe_forbid_ledger_change() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' and current_setting('tfe.allow_ledger_delete', true) = 'on' then
    return old;  -- explicit account-deletion procedure only
  end if;
  raise exception 'wallet_transactions is append-only' using errcode = 'P0001';
end;
$$;

create trigger wallet_transactions_append_only
  before update or delete on public.wallet_transactions
  for each row execute function public.tfe_forbid_ledger_change();

create or replace function public.tfe_protect_final_evaluation() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' and current_setting('tfe.allow_ledger_delete', true) = 'on' then
    return old;
  end if;
  if old.state = 'final' then
    raise exception 'final reward evaluations are immutable' using errcode = 'P0001';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

create trigger reward_evaluations_final_immutable
  before update or delete on public.reward_evaluations
  for each row execute function public.tfe_protect_final_evaluation();

-- ---------------------------------------------------------------- RLS & grants
create or replace function public.tfe_can_read_child(target uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select target = (select auth.uid())
      or exists (select 1 from public.guardian_children g
                 where g.guardian_id = (select auth.uid()) and g.child_id = target);
$$;
revoke all on function public.tfe_can_read_child(uuid) from public, anon;
grant execute on function public.tfe_can_read_child(uuid) to authenticated;
revoke all on function public.tfe_forbid_ledger_change() from public, anon, authenticated;
revoke all on function public.tfe_protect_final_evaluation() from public, anon, authenticated;

do $$
declare
  t text;
  owned_tables text[] := array[
    'profiles','guardian_children','activities','schedules','chore_completions','timer_drafts','time_entries',
    'day_statuses','wallet_accounts','wallet_transactions','reward_evaluations','child_worlds','world_unlocks',
    'world_events'];
  internal_tables text[] := array['audit_events','idempotency_requests','app_schema_migrations'];
  reference_tables text[] := array['world_themes','world_catalog','reward_policies'];
begin
  foreach t in array owned_tables || internal_tables || reference_tables loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on table public.%I from anon, authenticated', t);
  end loop;
  -- read-only own/linked-child access through the Data API (no client writes at all)
  foreach t in array owned_tables loop
    if t = 'profiles' then
      execute 'create policy profiles_select_own on public.profiles for select to authenticated
               using (public.tfe_can_read_child(id))';
    elsif t = 'guardian_children' then
      execute 'create policy guardian_children_select_own on public.guardian_children for select to authenticated
               using (guardian_id = (select auth.uid()) or child_id = (select auth.uid()))';
    else
      execute format('create policy %I on public.%I for select to authenticated
                      using (public.tfe_can_read_child(child_id))', t || '_select_own', t);
    end if;
    execute format('grant select on table public.%I to authenticated', t);
  end loop;
  foreach t in array reference_tables loop
    execute format('create policy %I on public.%I for select to authenticated using (true)', t || '_select_all', t);
    execute format('grant select on table public.%I to authenticated', t);
  end loop;
  -- internal tables: RLS on, no policies, no grants → invisible to the Data API
end;
$$;

-- ---------------------------------------------------------------- reference seed (not demo data)
insert into public.world_themes (code, name, sort_order) values
  ('settlers', 'Тихая бухта', 1),
  ('bricks',   'Брик-сити', 2),
  ('voxel',    'Куболесье', 3),
  ('helpers',  'Банановый залив', 4);

insert into public.world_catalog (theme_code, code, position, cost, requires_code)
select t.code, u.code, u.position, u.cost, u.requires_code
from public.world_themes t
cross join (values
  ('meadow',   0,  60, null),
  ('workshop', 1,  90, 'meadow'),
  ('harbor',   2, 120, 'workshop'),
  ('beacon',   3, 180, 'harbor')
) as u(code, position, cost, requires_code)
order by t.sort_order, u.position;

insert into public.reward_policies (version, parameters, effective_from) values (1, '{
  "version": 1,
  "first_evaluation_after_days": 14,
  "period_days": 7,
  "deferral_grace_days": 7,
  "lessons": {"min_days": 3, "tiers_percent": [[15, 30], [10, 20], [5, 10]], "cap": 100},
  "walk": {"default_target_seconds": 7200, "min_included_days": 5, "goal_share": [5, 7], "goal_reward": 40,
           "improvement_delta": "0.10", "improvement_min_ratio": "0.60", "improvement_min_recorded_days": 4,
           "improvement_reward": 20},
  "chores": {"min_ratio": "0.60", "base": 20, "count_bonus_cap": 15, "count_bonus_per": 3,
             "perfect_bonus": 5, "cap": 40, "min_distinct_days": 3}
}'::jsonb, date '2026-10-06');

insert into public.app_schema_migrations (version) values ('20261006000001');
