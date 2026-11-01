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
after a task reaches COMPLETED. It is local and bounded to 40 templates.

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
