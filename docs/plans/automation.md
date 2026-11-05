# Gate A — Automation (cron, run history, webhooks, hooks)

Status: **approved by owner with decisions below.** No code in this PR.
Scope: task 1 of the upgrade directive (OpenClaw phase 1). Research: `docs/research/openclaw-automation.md`.

## 1. What exists today (read from code)
| Piece | File | Does | Gap |
|-------|------|------|-----|
| Trigger registry | `core/triggers.py` | `daily_at`, `every_seconds`, `once_at`, `check()` condition; `triggers.json` in user data; quiet hours; atomic save | no cron expr/tz, no history, no catch-up policy, no failure handling, no "run now" |
| Scheduler loop | `core/runtime/live_services.py` `_run_trigger_scheduler` | 5 s tick, one turn at a time, waits while owner/JARVIS speaks, emits `schedule` event | lives inside the Gemini Live session; only injects a spoken turn; nothing runs a background agent task |
| Event bus + rules | `core/events.py`, `core/owner_store.py` `RuleStore` | `emit(source, payload)` → matching rules → action executor | sources only `email`, `file`, `schedule`; no lifecycle or webhook sources |
| Pollers | `actions/event_sources.py` | email (5 min), folder watch (30 s) | fine |
| Voice tool | `actions/proactive_triggers.py` | list / create / delete / quiet hours | no run history, no run-now |
| OS reminders | `actions/reminder.py` | schedules via Task Scheduler / launchd / cron so reminders fire when the app is closed | separate mechanism; unique value (works with app closed) |
| Idle check-in | `actions/proactive.py` | proactive speech after silence | unrelated; KEEP |
| UI | `ui/panels/scheduler_panel.py` | scheduler panel | no history view |
| HTTP | `dashboard/server.py` | bearer-token phone dashboard + a **separate** Twilio app on its own port (public-tunnel-safe pattern) | no inbound webhook surface |

## 2. Decisions (KEEP / UPGRADE / REPLACE / REMOVE)
- `core/triggers.py` — **UPGRADE** (extend `Trigger`; keep file format backward compatible).
- `live_services` scheduler — **UPGRADE** (record runs, catch-up, failure policy, `task` mode).
- `core/events.py` — **UPGRADE** (lifecycle + webhook sources; same `emit`).
- `actions/event_sources.py`, `daily_planner.py`, `proactive.py` — **KEEP**.
- `actions/reminder.py` — **KEEP** (only path that works with the app closed). Revisit in a later task.
- No REPLACE or REMOVE in this task.

## 3. Design
### 3.1 Cron expressions (PR A1)
- New `Trigger.cron: str | None` and `Trigger.tz: str | None` (IANA, default local). Exactly one schedule field still required.
- In-house parser (owner decision) `core/cron_expr.py` (5 fields: `*`, lists, ranges, `*/n`, `a-b/n`, month/day names, `Sun=0|7`), `next_after(now, tz)`. ~100 lines, no new dependency; property tests against a reference table. (Alternative: `croniter`, MIT — see open question 1.)
- Persisted fields gain `cron`, `tz`, `catch_up`, `mode`, `max_per_hour`; old rows load unchanged.
- `catch_up`: `"once"` (default for cron/daily: fire once when late) or `"skip"` (drop missed slots). Today's behaviour (late fire) = `"once"`.

### 3.2 Run history (PR A1)
- Table `trigger_runs(id, name, source, mode, started, finished, status, detail, duration_ms)` in the **existing** owner SQLite (`OwnerStore.ensure_schema`) — no new database.
- Status: `ok | failed | skipped_quiet | skipped_busy | blocked`. Capped to the latest 200 rows per trigger.
- API: `TriggerRegistry.record_run`, `runs(name, limit)`. Voice tool gains `runs`, `run_now`, `enable`, `disable`. Scheduler panel gets a read-only history list.

### 3.3 Execution modes and safety (PR A1)
- `mode="turn"` (today): inject spoken turn.
- `mode="task"` (runs even when the owner is away, per owner decision): submit the prompt to `agent/runner.py` as a background task; the result is announced through the existing `_announcements` queue. Goes through the existing policy/tier gate; DANGEROUS steps still need a UI confirmation token, so unattended runs stop at that step and report.
- Failure policy: 3 consecutive failures → trigger auto-disabled + announcement. `max_per_hour` budget (default 12) and a global cap of 5 concurrent automation tasks. A trigger-run task may not create or edit triggers (prevents self-multiplying loops).

### 3.4 Lifecycle hooks (PR A2)
- Add event sources to the existing bus: `startup`, `shutdown`, `session_start`, `session_end`, `trigger_fired`, `trigger_failed`, `task_finished`, `tool_error`, `privacy_lock`.
- In-process Python handlers via `events.subscribe` plus `HOOKS = [...]` discovered like `TRIGGERS` in `actions/*.py` and plugins. Each handler runs with a 5 s timeout, errors are isolated and logged.
- **Script hooks (owner decision: allowed, as in OpenClaw).** The owner can drop `.py`, `.ps1`, `.bat`, `.sh` files into `<user data>/hooks/<event>/`. They run as a subprocess (never in-process), JSON payload on stdin, 30 s timeout, output capped at 64 KB, working dir = the hook folder, minimal environment (no API keys passed). Guard rails: only that user-data folder is scanned (never the repo, downloads or paths coming from chat/web/tool output); JARVIS never writes into it on its own; each run is written to the security ledger; a hook that fails 3 times in a row is disabled and announced. A tool that tries to create a hook file is DANGEROUS tier and needs a UI confirmation.
- Owner rules can already match these sources with no change.

### 3.5 Webhooks (PR A3) — DEFERRED by owner (not needed now)
- New `dashboard/webhooks.py` with `register_webhook_routes(app)`, mounted on a **separate listener** (same pattern as the Twilio app) so tunnelling it cannot expose dashboard routes. **Off by default**; enabled by config `webhooks_enabled`.
- `POST /hooks/<name>` only for hooks the owner created. Each hook has: own secret (stored in keyring, never in JSON/Git), optional HMAC-SHA256 signature header with timestamp (reject > 5 min old, nonce cache against replay), body ≤ 64 KB, per-hook rate limit (default 30/min), constant-time compare.
- Payload is **untrusted data**: it becomes `events.emit("webhook", {"hook": name, "payload": <trimmed fields>})` and is passed through the existing injection guard; it is never used as a prompt directly. A hook maps to a fixed owner rule/action, so a caller can only trigger what the owner pre-approved.
- Webhook-triggered actions may not run DANGEROUS-tier tools without a UI confirmation.
- Audit: every call (accepted/rejected) written to the existing security ledger.

## 4. Files to change
`core/triggers.py`, new `core/cron_expr.py`, `core/owner_store.py` (schema), `core/events.py`, `core/runtime/live_services.py`, `actions/proactive_triggers.py`, `ui/panels/scheduler_panel.py`, new `dashboard/webhooks.py`, `main.py` (start webhook listener when enabled), `core/security.py` (ledger event names), docs + `CHANGELOG.md`.

## 5. Test plan
- Cron: table-driven next-fire tests incl. DST jumps, month ends, `*/n`, names, invalid input.
- Registry: backward-compat load of old `triggers.json`, catch-up modes, history cap, auto-disable, budget.
- Scheduler: run recorded for ok/failed/skipped; restart mid-run does not double-fire (idempotency via `last_fired` written before dispatch, as today).
- Webhooks: bad/missing secret, bad HMAC, stale timestamp, replay, oversize body, rate limit, unknown hook, disabled flag, DANGEROUS action blocked, injection payload stays data.
- Hooks: timeout, exception isolation, ordering.
- Perf: `jarvis.main` import time and suite time before/after (recorded in the PR).
- **Unverified until the owner tests on Windows:** real app restart persistence, tunnel exposure, voice phrasing of new tool actions.

## 6. Risks
- Webhook exposure is the largest risk → default off, separate port, per-hook secrets, fixed actions.
- Cron/DST edge cases → in-house parser must be tested hard (or use `croniter`).
- Unattended `task` mode could act while the owner is away → tier gate stops at DANGEROUS steps; budgets and auto-disable.
- Owner SQLite schema change → additive table only, no migration of existing data.

## 7. Delivery
Three PRs, each < ~800 lines excluding tests: **A1** cron + history + run-now + modes, **A2** lifecycle hooks, **A3** webhooks (deferred; design kept for later).

## 8. Owner decisions
1. Cron parser: **in-house**, no new dependency.
2. Webhooks: **not needed now** — A3 deferred.
3. Unattended background tasks: **allowed while the owner is away.** Safety stays: DANGEROUS-tier steps still stop for a UI confirmation, budgets and auto-disable apply, and results are announced when the owner returns.
4. Script hooks: **allowed** (OpenClaw-style), with the guard rails in §3.4.
