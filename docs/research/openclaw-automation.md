# Research: OpenClaw — automation (cron, webhooks, hooks)

Source: `https://github.com/openclaw/openclaw` (MIT) and `https://docs.openclaw.ai/automation`.
Last-commit date was not visible in the fetched page; maintenance activity is **unverified** (the repo shows a very large commit count).
Only the automation docs were read for this task; the rest of the project is covered by later tasks.

## What it does (from the docs)
- **Cron** is the Gateway's own scheduler, not the model. Jobs persist in a JSON store so restarts keep schedules. Schedule kinds: one-shot (`--at`, optional delete-after-run), interval, and 5-field cron expressions with `--tz`.
- Every cron execution creates a **background task record**, so there is a run history (`cron runs --id <job> --limit N`), `run now`, `run only if due`, edit, remove.
- A job targets either the **main session** (inject a system event / wake) or an **isolated** session (own agent turn) and can announce or deliver the result; failures have a retry policy and a separate failure destination.
- **Webhooks**: HTTP endpoints on the gateway, off by default, shared-secret token, fixed path prefix. `POST /hooks/wake`, `POST /hooks/agent`, and **mapped hooks** `POST /hooks/<name>` that transform a payload into a wake/agent action.
- **Hooks**: event-driven scripts fired by lifecycle events (new/reset/stop, compaction, gateway startup, message flow), auto-discovered from directories. Separate **plugin hooks** intercept tool calls in-process.
- **Standing orders** (persistent instructions) and **Task Flow** (durable multi-step flows) are separate features, planned for task 4.

## Decision
| Idea | Decision | Why |
|------|----------|-----|
| Cron expressions + tz | ADOPT pattern | JARVIS only has daily/interval/once |
| Persistent run history | ADOPT pattern | JARVIS keeps only `last_fired` |
| Run now / due-only / enable / disable | ADOPT pattern | cheap, useful by voice and UI |
| Main vs isolated target | ADOPT (as `mode`: `turn` / `task`) | `task` reuses `agent/runner.py` |
| Webhooks with per-hook secret | ADOPT pattern, **stricter** | see security notes in the plan |
| Lifecycle hooks | ADOPT pattern on top of `core/events.py` | bus already exists |
| Running hook *scripts* from directories | ADOPT (owner decision) | subprocess + timeout + owner-only folder + ledger, see plan §3.4 |
| Gmail PubSub watcher | REJECT | JARVIS already polls mail via `event_sources.py` |
| Gateway process / new store file | REJECT | no second scheduler or database |

## Security risks to avoid
Public webhook = remote prompt injection channel; shared secret leakage; replay; oversized bodies; scripts run from watched directories. Mitigations are in `docs/plans/automation.md`.
