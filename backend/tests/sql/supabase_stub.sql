-- TEST-ONLY stand-in for the Supabase-managed objects the migration references.
-- Used exclusively against a disposable local PostgreSQL (TEST_DATABASE_URL).
-- NEVER run this against a real Supabase project.
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key, email text);
create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
do $$
begin
  if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end;
$$;
grant usage on schema auth to authenticated;
grant usage on schema public to anon, authenticated;
