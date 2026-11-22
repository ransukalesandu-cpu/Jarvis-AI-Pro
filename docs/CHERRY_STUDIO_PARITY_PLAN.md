# Cherry Studio parity plan

Goal: add to JARVIS every Cherry Studio (github.com/CherryHQ/cherry-studio, v2.2.3) feature that JARVIS
does not have yet, and wire each one into the JARVIS brain, voice, tool registry and web UI, so it is a
JARVIS feature, not a separate app.

Status: **plan only, waiting for owner approval.** Nothing below is implemented in this PR.

## License rule (clean-room)

Cherry Studio is **AGPL-3.0**. JARVIS is **Apache-2.0**. Copying Cherry Studio code would force JARVIS
under AGPL. So this work takes **ideas and behaviour only**: no files, functions, prompts, assets or
translations are copied. Every feature is written fresh in Python (backend) and React/TypeScript
(`frontend/`). Reviewers should reject any PR that pastes Cherry Studio code.

## Audit: what JARVIS already has (skipped)

| Cherry Studio feature | JARVIS today | Action |
|---|---|---|
| OpenAI-compatible API gateway | `jarvis/dashboard/openai_bridge.py` | skip |
| MCP servers | `core/mcp_client.py`, `actions/mcp.py` | skip |
| Skills | `core/skills.py`, `actions/skills.py` | skip |
| Web search / read pages | `actions/web_search.py`, browser automation | skip |
| OCR, PDF/DOCX processing | `actions/screen_ocr.py`, `actions/file_processor.py` | skip |
| Image generation | `core/media_generation.py`, `actions/generate_media.py` | skip |
| Scheduled tasks | `core/routines.py`, `core/cron_expr.py`, `core/jobs.py` | skip |
| Local models (Ollama / LM Studio) | `core/llm_client.py`, hybrid router | skip |
| Multi-provider chat, export, Markdown/Mermaid | `web/` (NextChat) | skip |
| Agents with tools, computer use | `agent/`, `computer_control/` | skip |
| TTS | `voice/speech_engine.py` | skip |

## Gaps to build (one PR each, stacked)

Every feature follows the same wiring contract:

1. **Core module** under `jarvis/<area>/`, pure Python, unit-tested, no network on import.
2. **Tool** registered in `jarvis/actions/` so Gemini Live and the Claude brain can call it by voice
   and it shows up in `ToolCatalog` / registry-aware planning.
3. **Security tier** declared (Normal / Full Access / owner-only) through the existing security layer;
   Guest Mode gets read-only or nothing.
4. **Web UI window** in `frontend/` as a floating window, using the `webui/bridge.py` QWebChannel contract.
5. **Task Flow** steps emitted so the Task Flow window shows progress.
6. **Privacy**: any cloud call is optional, off by default, listed in `NETWORK.md`; `OFFLINE=1` still boots.
7. Docs page in `docs/` and tests in `jarvis/tests/`.

### P1. Knowledge Base (document RAG)
- `jarvis/knowledge/`: knowledge bases made of files, folders and web pages; chunking, local SQLite
  FTS5 index plus optional embeddings (reuses `memory/vector_index.py` design: off by default,
  local embedding model preferred, Gemini embedding optional).
- Folder watch: re-index changed files. Formats: PDF, DOCX, TXT/MD, HTML, images through existing OCR.
- Tool `knowledge`: `create`, `add` (file/folder/url), `search`, `ask` (answer with cited sources),
  `list`, `remove`. Voice: "add this PDF to my work knowledge", "what does my contract say about payment".
- Brain hook: when a KB is active, top chunks go into the prompt as untrusted content (existing
  `injection_guard`).
- Web UI: Knowledge window (bases, sources, index status, test search).

### P2. Channels (remote control through messaging)
- `jarvis/channels/` with a channel interface; first adapter **Telegram Bot API** (long-polling, no
  inbound port needed), designed so Discord/WhatsApp-business adapters can be added later.
- Only paired chat IDs are accepted (pairing code shown in JARVIS); everything else is dropped and logged.
- Incoming text goes through the normal brain + tool pipeline with the sender's tier (owner chat =
  owner's normal access; Full Access never granted remotely without PIN in chat).
- Replies, files (e.g. "send me the invoice PDF from my laptop") and job notifications back to the chat.
- Hooks into the "stop" word and the emergency stop.
- Web UI: Channels window (pair, revoke, recent messages).

### P3. Multi-model compare
- `jarvis/compare/`: send one prompt to N configured providers in parallel (hybrid router clients),
  collect answer, latency, tokens, cost estimate.
- Tool `compare_models`; voice "ask Claude, Gemini and GPT which is better for…"; JARVIS reads a short
  verdict, full answers in the window.
- Web UI: Compare window with side-by-side columns, "pick winner" stored as a routing hint for the
  hybrid router (owner opt-in).

### P4. Translation
- `jarvis/translate/`: text, selection, clipboard and whole documents (DOCX/TXT/MD/PDF→DOCX/MD) with
  layout kept where possible; language auto-detect; history.
- Provider: active LLM via hybrid router; offline fallback through Ollama when present.
- Tool `translate`; voice "translate this to Sinhala"; Web UI Translate window.

### P5. Quick Assistant + text selection actions
- Global hotkey (reuses `core/hotkey.py`) opens a small floating Quick Assistant bar anywhere.
- Selection actions: select text in any app, press the hotkey → explain / summarize / translate /
  fix grammar / ask / send to KB / send to notes. Text is read with a safe clipboard round-trip that
  restores the old clipboard; password fields are never read (`computer_control` rule).
- Screenshot-to-chat: region capture → ask about it (reuses `agent/screen_capture.py`).

### P6. Notes
- `jarvis/notes/`: Markdown notes in a folder the owner chooses (can be an Obsidian vault), tags,
  search, links to KB.
- Tool `notes`: create / append / read / search / list by voice ("note that the client wants blue").
- Web UI: Notes window with Markdown editor and preview.

### P7. Backup and restore
- `jarvis/backup/`: one archive of memory DB, owner/security data (encrypted, never plain), settings,
  skills, notes, KB metadata; manual and scheduled (cron), keep last N.
- Targets: local folder (default), WebDAV, S3-compatible (both optional, credentials in
  `config/api_keys.json`).
- Restore with owner PIN; dry-run preview first. Tool `backup` is owner-only.

### P8. Provider & model manager + usage budget
- Web UI Providers window over existing `core/provider_settings.py` / hybrid router: add keys, list
  models, test connection, set default per task (voice, brain, vision, translate, KB), see latency.
- Usage and cost per provider per day (extends `core/claude_usage.py` to all providers) with a budget
  notification.

### P9. Assistant profiles
- Several named assistants, each with its own instructions, default model, allowed tools and KB
  (Cherry "assistants/agents"). Switch by voice ("switch to coding assistant"). Built on existing
  persona/personality code, not replacing JARVIS's identity.

### P10. Mini Apps + file library
- Mini Apps: owner-defined web tools (URL + icon) opened as floating QWebEngine windows inside the
  JARVIS workspace, separate profile per app. Voice "open my Figma mini app".
- File library: index of files JARVIS generated or received (media, translations, exports, channel
  downloads) with search, preview and "send to phone/Telegram".

### P11. Local speech-to-text fallback
- Optional `faster-whisper` STT for offline / non-Live mode and dictation into any text box, model
  under the data dir, off by default (RAM-aware: small model on 16 GB target).

### P12. Global search
- One search across chat history, memory, KB, notes and file library; voice "find where I talked
  about the logo price"; Web UI Search window (command palette entry).

## Order and delivery

- Branches `feature/cherry-p1-knowledge` … `feature/cherry-p12-search`, one PR per phase, stacked on
  this plan PR, each with tests, docs and `NETWORK.md` updates. `python -m jarvis.webui.selfcheck` and
  the test suite must stay green.
- Suggested order by value: P1 → P2 → P5 → P4 → P6 → P3 → P8 → P7 → P9 → P12 → P10 → P11.
- Windows-only behaviour (hotkeys, selection, QWebEngine windows) gets unit tests with fakes here; the
  owner runs the Windows smoke test (`docs/WINDOWS_SMOKE_TEST_CHECKLIST.md` gets new rows) after the set
  is done.

## Owner decisions (2026-11-22)

1. First channel: **Telegram**.
2. KB embeddings: **Gemini embeddings** allowed (still opt-in via `JARVIS_KB_EMBEDDINGS=1`; FTS5-only
   search works offline without it).
3. Merge rule: **merge when CI is green**, no need to wait for the owner's word.

## Web UI delivery note

The web UI bridge contract is a closed, strictly validated set. Instead of adding a new message family
for every phase, the backend phases (P1–P12) ship core + voice tool + tests first, and one extra phase
**P13 (Features windows)** adds a single generic `feature.*` bridge family plus the floating windows for
all new features at once. This keeps each backend PR small and the contract change reviewable in one place.
