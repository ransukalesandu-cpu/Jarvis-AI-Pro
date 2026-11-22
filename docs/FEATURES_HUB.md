# Features Hub (web UI)

P13 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`. Open it from the command palette (Ctrl+K → "Open Features Hub window").

One floating, draggable glass window with a tab per Cherry-parity feature: **Knowledge, Notes, Telegram,
AI Providers, Compare, Backup, Profiles, Files, Mini Apps**. Each tab shows a live summary and list, quick
action buttons and (where useful) an ask box.

## Security design
- The page never calls a feature. It can only ask for a **read-only snapshot** (`feature.refresh` → `feature.snapshot`)
  and every button or ask box submits an **ordinary typed command** through the existing `CommandGate`, so tiers,
  confirmations, rate limits and the audit log apply exactly as for typing or voice.
- Snapshots are built only while typing a command would be allowed (not locked, waiting for a PIN, silent or in
  Guest Mode); otherwise the tab just says why.
- Both sides validate the closed contract: known feature names only, max 30 items, title ≤ 120 and detail ≤ 200
  characters, summary ≤ 200; every field is scrubbed for secrets and home paths (`webui/redact.py`).
- The window kind `features` is accepted in saved workspace layouts.

Files: `jarvis/webui/features_feed.py`, `jarvis/webui/{contract,bridge,workspace_store}.py`,
`frontend/src/ui/Features.tsx`, `frontend/src/bridge/contract.ts`, built into `jarvis/webui/dist`.
