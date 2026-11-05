# Registry-aware planning — plan (no code changes in this PR)

Status: **proposal, waiting for owner approval.** This PR only adds this document.

Origin: ideas taken from microsoft/JARVIS (HuggingGPT): plan → select a tool by its
description → run with dependencies → trace each stage. Nothing is copied from that repo
(it needs 24 GB VRAM / 284 GB disk and is no longer maintained); only the patterns.

## 1. What already exists (audit of `main` @ 96e06a4)

| Piece | Where | State |
|---|---|---|
| One-file tools with `TOOL` dict + description | `core/action_loader.py`, `actions/*.py` (~59 tools) | done |
| Plugins, skills (name+description index), MCP, remote-device tools | `core/plugin_loader.py`, `core/skills.py`, `core/mcp_client.py`, `hub/remote_tools.py` | done |
| Dependency-aware planner, topological order, cycle rejection | `agent/planner.py`, `agent/dependency_graph.py` | done |
| Parallel execution of independent steps | `agent/parallel_engine.py`, `agent/executor.py` | done |
| Action log, risk/timeout/available metadata | `core/tool_runtime.py`, `core/action_log.py` | done |

So the "tool registry with descriptions" idea is **already implemented for the voice path**:
every registered tool is declared to Gemini Live with its description.

## 2. The real gap

The task planner (`agent/planner.py`) chooses from its **own small fixed set of typed
tools** (workspace/file/command/web steps). It does not know about the live registries.
Result: a multi-step plan cannot use `browser_control`, `phone_control`, `calendar`,
`email`, `send_message`, installed plugins, skills, MCP tools or tools on another device,
even though the voice path can call all of them one at a time.

Secondary gaps:
- All ~60+ full tool schemas are sent to the model every session; the planner has no
  compact catalog to read.
- No stage-by-stage trace of "what was planned / which tool was chosen / what came back".

## 3. Proposed change (3 small PRs)

**PR A — `ToolCatalog` (read-only).** New `core/tool_catalog.py`: builds a compact list
`{name, one-line description (<=150 chars, same rule as `_describe_tools`), risk, device,
available}` from `ActionRegistry`, `PluginRegistry`, `CompositeRegistry`/remote tools and
MCP. Honors `available()`. No behavior change. Unit tests with fake registries.

**PR B — `registry_call` plan step.** Planner may emit a step
`{"tool": "registry_call", "name": <catalog name>, "args": {...}, "depends_on": [...]}`.
- Planner prompt receives the catalog, filtered to the top-K (default 20) by simple
  keyword/BM25 match on the objective, so the prompt stays small on a 4–8 GB laptop.
- Planner validates: name exists in catalog, args match the declared schema, no unknown names.
- Executor dispatches through the **existing** dispatcher path, so security tier,
  Full Access, injection guard, action log and `device` routing apply unchanged.
- Output of a step can be referenced by later steps (`{{step:N}}`), text-only, capped,
  and treated as untrusted data (not as instructions).
- Falls back to today's deterministic planner when the model or catalog is unavailable.
- Feature flag `JARVIS_REGISTRY_PLANNING=1`, **off by default** until tested on Windows.

**PR C — stage trace.** Write `plan → selection → results` per task to the existing action
log / task store and show it in the existing diagnostics view (`self_check`). No UI redesign.

## 4. Explicitly out of scope
- Main UI, hologram, security design (Security V2) — untouched.
- No changes to Gemini Live declaration building (changing declarations mid-session would
  force a reconnect and risk the mid-sentence voice issue).
- No local model downloads, no new heavy dependencies.

## 5. Tests
- Catalog: unavailable tools hidden, collisions, long descriptions truncated.
- Planner: unknown tool rejected, schema mismatch rejected, cycle still rejected,
  fallback when model fails, top-K retrieval picks the right tool for sample objectives
  (a small TaskBench-style fixture of ~20 objectives → expected tool).
- Executor: dispatch goes through the normal dispatcher; guest/Normal tiers still block
  what they block today; untrusted output is not executed as a command.
- All tests runnable on Linux with mocks (Windows cannot be tested right now).

## 6. Risks
- Planner could chain powerful tools (phone, email) → mitigated by reusing the dispatcher
  and security tiers; flag off by default.
- Prompt size → top-K retrieval + 150-char cap.

## 7. Decisions needed from the owner
1. Approve this plan as written (A → B → C), or drop C?
2. Should `registry_call` steps be allowed to use remote-device tools (phone/second PC) in
   the first version, or local tools only?
3. Default top-K (20)?
