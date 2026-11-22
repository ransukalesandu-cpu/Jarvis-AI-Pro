# Knowledge base

Local document search (RAG) for JARVIS — P1 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`.

## What it does
- Named knowledge bases ("work", "university", …) built from **files, folders, web pages and dictated text**.
- Formats: PDF, DOCX, PPTX, HTML, Markdown/TXT, CSV/JSON/YAML and source code. Folders are scanned
  recursively (max 2000 files, files over 25 MB skipped, `.git`/`node_modules`/hidden folders ignored).
- Search = SQLite FTS5 keyword rank (offline) blended with **Gemini embeddings** when enabled.
- `ask` returns numbered excerpts wrapped as untrusted content, and JARVIS answers with `[1]`, `[2]` citations.

## Voice examples
| Say | Tool call |
|---|---|
| "Add my Documents\Clients folder to my work knowledge" | `knowledge(action="add", base="work", target=...)` |
| "Add https://example.com/pricing to research" | `add` with a URL |
| "Remember this in my ideas knowledge: …" | `add_text` |
| "Use my work knowledge" | `use` (sets the active base) |
| "What does my contract say about payment?" | `ask` |
| "Refresh my work knowledge" | `refresh` (re-indexes changed files, drops deleted ones) |
| "Delete my old knowledge base" | `delete_base` (needs confirmation) |

## Settings
| Env var | Default | Meaning |
|---|---|---|
| `JARVIS_KB_EMBEDDINGS` | off | `1` = embed chunks with Gemini `gemini-embedding-001` (256 dims) for meaning-based search. Off or `OFFLINE=1` = keyword search only. |
| `JARVIS_DATA_DIR` | per-user data folder | The index lives in `<data>/knowledge/kb.sqlite`. |

## Security
- `list`, `sources`, `ask`, `search`, `stats` → SAFE; `add`, `add_text`, `use`, `refresh`, `remove_source`,
  `create` → SENSITIVE; `delete_base` → DANGEROUS (confirmation).
- Guest Mode cannot use the tool (deny-by-default guest allowlist).
- Retrieved text is passed through `injection_guard.wrap_untrusted`, so instructions inside documents are data.
