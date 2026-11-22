# Global search

P12 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`. Tool: `global_search`.

"When did I talk about the logo price?", "search everything for invoice" → one search across:
past **conversations**, **memory**, **knowledge bases**, **notes** and the **file library**, grouped by source.
Results are returned as untrusted data. `sources` narrows it ("search my notes and files for…").

## Conversation archive
Owner and JARVIS lines from the HUD log are kept locally in `<data>/history/YYYY-MM-DD.jsonl` so they can be
searched. Privacy rules (same as the web UI log mirror): nothing is recorded while JARVIS is locked, waiting for a
PIN, silent or in Guest Mode; authentication lines and PIN/password commands are dropped; API keys, tokens and
home paths are scrubbed.
- Off: `JARVIS_CHAT_HISTORY=0`. Retention: `JARVIS_CHAT_HISTORY_DAYS` (default 180).
- "Delete my conversation history" → `clear_history` (DANGEROUS: confirmation).
