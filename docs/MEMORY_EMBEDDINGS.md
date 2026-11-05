# Memory embeddings (optional)

Retrieval = FTS5 + local similarity (unchanged). Setting `JARVIS_MEMORY_EMBEDDINGS=1` adds a
Gemini embedding signal (`gemini-embedding-001`, 256 dims) so differently-worded memories match.

- Off by default; nothing is sent to Google when off.
- Vectors cached in `memory/vectors.sqlite3`; missing ones are filled by a background thread,
  retrieval never waits for them. The query itself costs one call with a 2.5 s timeout.
- Secret/restricted memories are never embedded. Any error falls back to the old ranking.
- A memory surfaces on meaning alone only at cosine >= 0.72.

## Cloud (pgvector) — not wired
`docs/sql/memory_pgvector.sql` is a reviewed schema (RLS per owner, HNSW index, match function) for
a future cloud sync. It is **not applied or tested against a live Supabase project**; the existing
Supabase personal-facts provider is unchanged.
