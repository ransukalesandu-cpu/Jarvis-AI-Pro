-- Privacy-first, per-anonymous-user personal profile memory for JARVIS.
-- The Edge Function validates the Supabase Auth JWT and performs all access
-- with the service role. Direct access from anon/authenticated is denied.
create table if not exists public.jarvis_personal_memory_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  enabled boolean not null default false,
  updated_at timestamptz not null default now()
);
alter table public.jarvis_personal_memory_settings enable row level security;
revoke all on public.jarvis_personal_memory_settings from public, anon, authenticated;
grant all on public.jarvis_personal_memory_settings to service_role;

create table if not exists public.jarvis_personal_memories (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  fact_key text not null check (fact_key in (
    'name', 'siblings', 'family_context', 'education', 'occupation',
    'interests', 'preferences', 'goals', 'language', 'communication_style'
  )),
  value text not null check (char_length(value) between 1 and 500),
  evidence_quote text not null check (char_length(evidence_quote) between 1 and 700),
  source text not null default 'user_stated' check (source = 'user_stated'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, fact_key)
);
create index if not exists jarvis_personal_memories_user_updated_idx
  on public.jarvis_personal_memories (user_id, updated_at desc);
alter table public.jarvis_personal_memories enable row level security;
revoke all on public.jarvis_personal_memories from public, anon, authenticated;
grant all on public.jarvis_personal_memories to service_role;
