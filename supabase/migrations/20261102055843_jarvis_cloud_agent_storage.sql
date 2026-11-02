-- Cloud-only persistence for autonomous tasks, checkpoints, events and saved workflows.
-- Direct client access is intentionally denied; the authenticated Edge Function
-- uses the server-only service role after resolving the caller's Supabase Auth ID.

create table if not exists public.jarvis_agent_tasks (
  user_id uuid not null references auth.users(id) on delete cascade,
  task_id text not null check (char_length(task_id) between 1 and 100),
  state text not null check (char_length(state) between 1 and 40),
  objective text not null check (char_length(objective) <= 1200),
  task_data jsonb not null check (pg_column_size(task_data) <= 65536),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, task_id)
);
create index if not exists jarvis_agent_tasks_user_updated_idx
  on public.jarvis_agent_tasks(user_id, updated_at desc);

create table if not exists public.jarvis_agent_task_events (
  user_id uuid not null,
  task_id text not null,
  event_id bigint generated always as identity,
  event_data jsonb not null check (pg_column_size(event_data) <= 12000),
  created_at timestamptz not null default now(),
  primary key (user_id, task_id, event_id),
  foreign key (user_id, task_id)
    references public.jarvis_agent_tasks(user_id, task_id) on delete cascade
);
create index if not exists jarvis_agent_task_events_recent_idx
  on public.jarvis_agent_task_events(user_id, task_id, event_id desc);

create table if not exists public.jarvis_agent_workflows (
  user_id uuid not null references auth.users(id) on delete cascade,
  workflow_id text not null check (char_length(workflow_id) between 1 and 100),
  name text not null check (char_length(name) between 1 and 80),
  objective text not null check (char_length(objective) between 1 and 500),
  criteria jsonb not null default '[]'::jsonb
    check (jsonb_typeof(criteria) = 'array' and pg_column_size(criteria) <= 3000),
  steps jsonb not null default '[]'::jsonb
    check (jsonb_typeof(steps) = 'array' and pg_column_size(steps) <= 6000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, workflow_id)
);
create index if not exists jarvis_agent_workflows_user_updated_idx
  on public.jarvis_agent_workflows(user_id, updated_at desc);

alter table public.jarvis_agent_tasks enable row level security;
alter table public.jarvis_agent_task_events enable row level security;
alter table public.jarvis_agent_workflows enable row level security;

revoke all on public.jarvis_agent_tasks from anon, authenticated;
revoke all on public.jarvis_agent_task_events from anon, authenticated;
revoke all on public.jarvis_agent_workflows from anon, authenticated;
grant all on public.jarvis_agent_tasks to service_role;
grant all on public.jarvis_agent_task_events to service_role;
grant all on public.jarvis_agent_workflows to service_role;
