# Autonomous Task 2 — Recovery, memory and efficiency

This phase builds on the existing agent engine rather than replacing it.

## Existing capabilities retained

- The task runner provides bounded retries, exponential backoff, loop detection,
  deadlines, pause/cancel, checkpoints and restart resume.
- The executor checks observable postconditions and records verification evidence.
- Existing security retains owner authorization, Privacy Lock, risk classification
  and explicit approval for consequential work.
- Opt-in, user-scoped Supabase profile memory validates evidence and sensitive
  categories; raw conversations are not uploaded.
- Hybrid provider routing and lazy UI/action loading remain in place.

## Explicit workflow library

The new agent workflow library stores only workflows the user explicitly saves
after a task reaches COMPLETED. It is stored in Supabase and bounded to 40 templates per user.

A template stores its label, objective, criteria and step titles/kinds. It does
not store commands, paths, file contents, screen targets, tool output or evidence.
Suggestions are informational only. Reuse returns planner input, not executable
steps; callers must pass it through AgentService.start, which rechecks owner
authorization, autonomy settings and Privacy Lock before normal planning,
policy checks and approvals.

The workflow library is separate from personal profile memory: procedures are
not silently uploaded to Supabase or mixed with personal facts. Deletion is
explicit and history is bounded.

## Validation

From JarvisAI run:
python -m pytest tests/test_agent_workflows.py tests/test_agent_core.py tests/test_agent_runner.py -q

Then run the full regression suite:
python -m pytest tests -q

Windows laptop validation is still required for real audio devices, desktop
permissions, Supabase credentials and measured process memory.


## AgentService integration

The application facade exposes protected operations for `save_workflow`,
`list_workflows`, `suggest_workflows` and `run_workflow`. Each operation
rechecks the existing autonomy-enabled, owner-authorized and Privacy Lock
conditions. The `run_workflow` path passes only the saved objective and
acceptance criteria to `AgentService.start`; the planner creates a new plan
and all steps pass through the normal policy and approval gates. Saved commands
are never replayed.

The workflow library is imported lazily and uses the existing Supabase Auth session,
keeping startup and local memory cost negligible.


## Cloud-only persistence (current architecture)

Autonomous task snapshots, restart checkpoints, task history, event journals,
reports and explicitly saved workflow templates are stored in the user's
Supabase Auth-scoped cloud account. The desktop agent uses the authenticated
`jarvis-personal-memory` Edge Function; it does not write these records to
`memory/agent`, JSON files or SQLite. Cloud writes fail closed when the
Supabase session or network is unavailable: there is no local persistence
fallback.

The database tables `jarvis_agent_tasks`, `jarvis_agent_task_events` and
`jarvis_agent_workflows` have RLS enabled and deny direct client-role access.
Only the server-side Edge Function accesses them with the service role after
resolving the caller's Supabase Auth identity. Task history is bounded to 40
records per user; events are bounded when read. Saved workflow templates keep
only the user-approved name, objective, criteria and step title/kind summaries;
reuse always creates a fresh plan through AgentService and its existing
owner-authentication, Privacy Lock, policy and approval gates.

The only local persistence required for this cloud identity is the Supabase
refresh token in the operating system's credential vault (Windows Credential
Manager/DPAPI, macOS Keychain or Linux Secret Service). It is an authentication
secret, not a local copy of task or personal data. Do not put service-role keys
or private cloud credentials in the desktop app.
