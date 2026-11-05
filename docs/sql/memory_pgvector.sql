-- Optional cloud memory with semantic search (Supabase + pgvector).
-- NOT applied by Jarvis automatically and NOT yet exercised against a live
-- Supabase project: review, then run it yourself in the Supabase SQL editor.
create extension if not exists vector;

create table if not exists jarvis_memories (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  memory_id text not null,
  content text not null,
  embedding vector(256),
  updated_at timestamptz not null default now(),
  unique (owner_id, memory_id)
);
alter table jarvis_memories enable row level security;
create policy "owner reads own" on jarvis_memories for select using (auth.uid() = owner_id);
create policy "owner writes own" on jarvis_memories for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);
create index if not exists jarvis_memories_embedding_idx
  on jarvis_memories using hnsw (embedding vector_cosine_ops);

create or replace function match_jarvis_memories(query_embedding vector(256), match_count int default 5)
returns table (memory_id text, content text, similarity float)
language sql stable security invoker as $$
  select memory_id, content, 1 - (embedding <=> query_embedding) as similarity
  from jarvis_memories where owner_id = auth.uid()
  order by embedding <=> query_embedding limit least(match_count, 20);
$$;
