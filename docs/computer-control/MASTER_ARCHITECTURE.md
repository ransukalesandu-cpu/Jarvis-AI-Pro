# Computer Control Engine — Master Architecture

Status: Phase 0 (foundation) implemented. Projects 1–8 build on it; see
[INTEGRATION_ROADMAP.md](INTEGRATION_ROADMAP.md) and [PROGRESS.md](PROGRESS.md).

## Goal

```
USER REQUEST → UNDERSTANDING → PLANNING → TOOL SELECTION → COMPUTER CONTROL → VERIFICATION → MEMORY
```

JARVIS must understand the whole objective (for example "open VS Code and inspect my
project"), plan it, choose the right controller (Windows native, browser, visual,
fallback input), act, verify the result, and only then report — never "success"
because an action was merely attempted.

## One pipeline, no side doors

Every action of the engine — whether the model calls a `cc_*` tool, the
orchestrator runs a planned step, or a saved workflow replays — goes through
`jarvis/computer_control/runner.py`. **Exception:** the older tools
`computer_control`, `desktop_automation` and `ui_interaction` (actions/) are not
routed through the runner; they keep their existing gates (security.guard,
confirm gate) and get neither the new policy nor verification (see PROJECT_AUDIT.md).

```
feature flag ─► emergency stop ─► policy (LOW/MEDIUM/HIGH) ─► native approval (HIGH)
     │                                                              │
     └── disabled                         denied / not approved ◄───┘
                                                                     │
  audit(end) ◄─ verify ◄─ execute (bounded pool, timeout, cancel) ◄─ dry-run?
```

| Stage | Module | Fail mode |
|---|---|---|
| Feature flag | `flags.py` (`JARVIS_COMPUTER_CONTROL`, `JARVIS_COMPUTER_CONTROL_DRY_RUN`, or the owner's saved `computer_control` setting via `jarvis_settings`) | off by default → `disabled`; `cc_engine_status` stays available |
| Readiness | `readiness.py` | per-part checks with reason codes for `cc_engine_status` |
| Emergency stop | `estop.py` (generation counter + optional latch) | `cancelled` |
| Policy | `policy.py` (`ActionPolicy`) | `denied`; unknown action → HIGH |
| Approval | `approval.py` (`NativeApprover` → AuthManager / PIN; `qt_prompt.py`) | no approver → deny |
| Audit | `audit.py` → `core/action_log.py` (+ HMAC ledger for approvals) | never raises; failsoft |
| Redaction | `redaction.py` (password fields, tokens, screenshot masking) | — |
| Untrusted content | `untrusted.py` (fencing + injection markers) | content origin → only LOW |
| Execute | `runner.py` (4 workers, 16 pending max) | `timeout` / `error` / `busy` |
| Verify | spec/step verifier or handler `verified` flag — optional: with neither, `verified` is `None` and non-LOW results say "not independently verified" | `unverified` (not ok) when a check fails |
| Tool contract | `contract.py` (`ToolSpec` → existing `TOOL` declaration) | invalid spec rejected at load |
| Monitoring | `monitoring.py` (psutil RSS/CPU/threads) | `None` values when psutil missing |

## Reused, not duplicated

| Existing piece | How the engine uses it |
|---|---|
| `core/action_loader.py` + `actions/` | `actions/computer_control_engine.py` exposes `TOOLS`; same discovery, same `available` gate |
| `core/tool_runtime.py` `ToolMeta` | `risk` = `Level.tool_risk` (read/write/destructive), `timeout`, `long_running` |
| `core/tool_catalog.py` | cc tools appear in the catalog/planner automatically (when enabled) |
| `core/action_log.py` | every action logged as `cc.<action>`; `show_recent_actions` sees them |
| `core/security.py` | `audit()` ledger for approvals/denials, `mark_untrusted_seen()` |
| `security/auth_manager.py` | Privacy Lock, owner session, `verify_pin` (lockout counts) |
| `core/path_guard.py` | protected secrets/code roots (plus Windows system dirs) |
| `core/injection_guard.py` | same `=== BEGIN EXTERNAL CONTENT` fence convention |
| `core/jobs.py` | task-level work runs as `JobManager` jobs; `cancel_event` feeds the stop token |
| `core/runtime/live_tools.py` `_stop_everything` | also triggers `estop` (stop word path) |
| `JarvisLive.interrupt` (`_do_interrupt`) | also triggers `estop` |
| `core/failsoft.py` | every swallowed error is recorded |
| `ui` `prompt_pin` signal (`_pin_prompt_sig`) | the native approval dialog is marshalled the same way |
| `agent/` (planner, dependency_graph, computer_use, screen_vision, accessibility, workflow_library) | Projects 2/4/5 build on them (see roadmap) |

## Package layout (adapted to repo conventions)

```
jarvis/computer_control/
  flags.py  policy.py  approval.py  qt_prompt.py  estop.py  audit.py  redaction.py
  untrusted.py  contract.py  runner.py  monitoring.py  tools.py
  bench/            baseline + synthetic suite (Project 8)
  windows/          controller API, UIA/Win32 backend, fake backend, fallback input (Projects 1+6)
  orchestrator/     host agent, app agents, task context, trace, recovery (Project 2)
  browser/          browser controller (Playwright on installed Edge/Chrome) (Project 3)
  visual/           perception engine, hybrid locate order (Project 4)
  workflows/        recorder, validator, versioned library (Project 5)
jarvis/actions/computer_control_engine.py   registration in the existing registry
```

## Threading model

* The Qt thread never runs an action. The model's tool call arrives on the asyncio
  loop; the registry handler calls the runner, which executes on the `cc-action`
  pool (max 4 workers, max 16 outstanding → `busy`).
* Approval blocks only the worker thread: the Qt dialog is posted to the UI thread
  through the existing `_pin_prompt_sig` signal and the worker waits with a timeout.
* Handlers use `ctx.wait()`/`ctx.check()`; the emergency stop wakes `wait` at once
  (condition variable) or within `estop.POLL_S` (20 ms) when a job cancel event is used.

## Security summary

See [SECURITY_MODEL.md](SECURITY_MODEL.md). HIGH actions always need the native
approval — Full Access does not waive it. Content (screens, pages, documents, tool
output) can never cause a state change.
