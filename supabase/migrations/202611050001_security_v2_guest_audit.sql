-- Security V2: Guest audit trail, server side. SQL FILE ONLY: not applied to any project by this commit.
-- Data minimisation: no free-text, transcript, audio, screenshot, password or command columns exist.
-- Direct client access is denied; an authenticated Edge Function (service role) is the only writer/reader.

create table if not exists public.jarvis_guest_audit_events (
  user_id uuid not null references auth.users(id) on delete cascade,
  event_id text not null check (char_length(event_id) between 1 and 40),
  guest_session_id text not null check (char_length(guest_session_id) between 1 and 32),
  event_type text not null check (event_type in (
    'guest_session_started','guest_session_ended','guest_notice_shown',
    'restricted_action_attempted','restricted_action_denied',
    'authentication_failed','security_policy_blocked_action')),
  action_category text not null check (action_category in (
    'none','general_chat','owner_memory','personal_data','secret_access','settings_read','settings_write',
    'voice_identity','owner_management','security_management','computer_control','file_management',
    'shell_execution','browser_automation','plugin_execution','task_automation','guest_history','unknown')),
  outcome text not null check (outcome in ('allowed','denied','info')),
  safe_metadata jsonb not null default '{}'::jsonb
    check (jsonb_typeof(safe_metadata) = 'object' and pg_column_size(safe_metadata) <= 512
           and safe_metadata - 'tool' - 'tier' - 'reason' = '{}'::jsonb),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '7 days')
    check (expires_at <= created_at + interval '7 days'),
  primary key (user_id, event_id)
);
create index if not exists jarvis_guest_audit_expiry_idx on public.jarvis_guest_audit_events(expires_at);
create index if not exists jarvis_guest_audit_session_idx
  on public.jarvis_guest_audit_events(user_id, guest_session_id, created_at);

alter table public.jarvis_guest_audit_events enable row level security;
revoke all on public.jarvis_guest_audit_events from anon, authenticated;
grant all on public.jarvis_guest_audit_events to service_role;

-- Retention: expired rows are never returned and are deleted by this function.
create or replace function public.jarvis_purge_expired_guest_audit() returns bigint
language plpgsql security definer set search_path = public as $$
declare n bigint;
begin
  delete from public.jarvis_guest_audit_events where expires_at <= now();
  get diagnostics n = row_count;
  return n;
end $$;
revoke all on function public.jarvis_purge_expired_guest_audit() from public, anon, authenticated;
grant execute on function public.jarvis_purge_expired_guest_audit() to service_role;

-- Scheduled purge every hour, only if pg_cron is already enabled for the project.
do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    perform cron.schedule('jarvis-purge-guest-audit', '17 * * * *',
                          'select public.jarvis_purge_expired_guest_audit()');
  else
    raise notice 'pg_cron is not enabled: schedule jarvis_purge_expired_guest_audit() another way (e.g. a scheduled Edge Function).';
  end if;
end $$;
