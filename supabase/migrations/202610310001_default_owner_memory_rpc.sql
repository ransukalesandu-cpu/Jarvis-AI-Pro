-- Read-only service-role RPC for the single JARVIS default owner profile.
-- The profile remains in the private schema; clients cannot query it directly.
create or replace function public.jarvis_get_default_owner_memory()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select profile
  from private.jarvis_default_owner_memory
  where profile_key = 'default_owner'
  limit 1;
$$;

revoke all on function public.jarvis_get_default_owner_memory() from public, anon, authenticated;
grant execute on function public.jarvis_get_default_owner_memory() to service_role;
