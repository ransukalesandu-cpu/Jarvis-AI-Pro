-- JARVIS host-bound cloud authentication, replay protection, and quotas.
create table if not exists public.jarvis_host_devices (
  user_id uuid primary key references auth.users(id) on delete cascade,
  public_key_b64 text not null,
  created_at timestamptz not null default now(),
  revoked_at timestamptz
);
alter table public.jarvis_host_devices enable row level security;
revoke all on public.jarvis_host_devices from anon, authenticated;
grant all on public.jarvis_host_devices to service_role;

create table if not exists public.jarvis_cloud_nonces (
  user_id uuid not null references auth.users(id) on delete cascade,
  nonce text not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  primary key (user_id, nonce)
);
alter table public.jarvis_cloud_nonces enable row level security;
revoke all on public.jarvis_cloud_nonces from anon, authenticated;
grant all on public.jarvis_cloud_nonces to service_role;

create table if not exists public.jarvis_cloud_daily_usage (
  user_id uuid not null references auth.users(id) on delete cascade,
  usage_date date not null default (timezone('utc', now()))::date,
  request_count integer not null default 0 check (request_count >= 0),
  primary key (user_id, usage_date)
);
alter table public.jarvis_cloud_daily_usage enable row level security;
revoke all on public.jarvis_cloud_daily_usage from anon, authenticated;
grant all on public.jarvis_cloud_daily_usage to service_role;

create or replace function public.jarvis_consume_cloud_request(
  p_user_id uuid,
  p_nonce text,
  p_timestamp bigint,
  p_daily_limit integer default 100
) returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_date date := (timezone('utc', now()))::date;
  v_count integer;
begin
  if p_user_id is null
     or p_nonce is null
     or length(p_nonce) < 16
     or length(p_nonce) > 128
     or p_timestamp is null
     or abs(extract(epoch from clock_timestamp())::bigint - p_timestamp) > 300
     or p_daily_limit < 1 or p_daily_limit > 1000 then
    return 'invalid';
  end if;

  delete from public.jarvis_cloud_nonces where expires_at < now();
  insert into public.jarvis_cloud_nonces(user_id, nonce, expires_at)
  values (p_user_id, p_nonce, now() + interval '10 minutes')
  on conflict do nothing;
  if not found then
    return 'replay';
  end if;

  insert into public.jarvis_cloud_daily_usage(user_id, usage_date, request_count)
  values (p_user_id, v_date, 1)
  on conflict (user_id, usage_date) do update
    set request_count = public.jarvis_cloud_daily_usage.request_count + 1
    where public.jarvis_cloud_daily_usage.request_count < p_daily_limit
  returning request_count into v_count;

  if v_count is null then
    return 'quota';
  end if;
  return 'ok';
end;
$$;

revoke all on function public.jarvis_consume_cloud_request(uuid, text, bigint, integer) from public, anon, authenticated;
grant execute on function public.jarvis_consume_cloud_request(uuid, text, bigint, integer) to service_role;
