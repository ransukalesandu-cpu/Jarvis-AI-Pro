# JARVIS Agentic AI OS Upgrade — Phases 0–12

Status: active engineering rollout. This is an architecture and execution record, not a claim that every phase is implemented.

## Non-negotiable product decisions

- JARVIS remains a Windows desktop-first assistant with a secure multi-device architecture; it does not replace Windows with a new operating system.
- The main UI keeps the existing Neural Brain / spherical visual as its central identity.
- Do not reintroduce a human holographic face, a Heart Reactor, or heart-reactor energy connections.
- Keep the existing Python backend, Gemini Live voice path, provider router, ActionDispatcher, AuthManager, Privacy Lock, and existing working features unless an audited reason justifies a controlled replacement.
- Prefer cloud persistence for long-lived agent tasks and memory; do not silently fall back to local task persistence when cloud persistence fails.
- Autonomy is bounded by explicit permissions, budgets, audit logs, cancellation, and verification. Consequential operations remain approval-gated.
- Use feature branches and pull requests. Merge by squash only after required CI, security checks, review requirements, and conflict checks pass. Never bypass a failed or unavailable required gate.

## Phase 0 — Repository audit (completed)

Repository: `ransukalesandu-cpu/Jarvis-AI-Pro`; default branch: `main`.

### Findings

- The project is a Python desktop application with PyQt6 and a React/TypeScript frontend bundled under `jarvis/webui/dist`.
- The web UI is hosted in Qt WebEngine. `jarvis/webui/host.py` and `bridge.py` provide a restricted host and typed request/event bridge; the frontend does not receive privileged backend objects directly.
- The frontend already contains a Three.js / React Three Fiber scene, a procedural NeuralBrain, state-reactive neural visualisation, an orb, particles, performance controls, widgets, glass windows, settings, command bar, and task-flow UI.
- `frontend/src/store.ts` defaults `centerStyle` to `brain`; `HologramScene.tsx` renders NeuralBrain in that mode. The alternate face render path still exists and needs an explicit compatibility/dependency audit before removal.
- The repository already contains an autonomous task stack: planner, dependency graph, policy engine, executor, runner, bounded parallel engine, event bus, screen vision, computer use, browser automation, cloud task store, and tests.
- `jarvis/core/brain_engine.py` already provides bounded conversation context and privacy-filtered memory context through the existing provider router.
- Supabase-backed agent persistence exists in `jarvis/agent/cloud_store.py`; it intentionally fails closed rather than writing task state locally when cloud persistence is unavailable.
- Existing CI includes Python lint/tests, Windows UI smoke tests, frontend type/lint/format/unit/build/storybook/dist checks, secret scanning, Semgrep reporting, OSV scanning, and Supabase domain tests.
- The repo has one open Draft PR (#287) for ElevenLabs dual-voice TTS. Its own description says a real Windows audio smoke test is still required; it is not part of this upgrade and must not be merged merely because unrelated checks pass.
- Existing roadmap documents are not fully aligned: `docs/ROADMAP.md` describes a smaller unfinished sequence, while the current code already contains several of those capabilities. Future work must be driven by code/tests and not by stale status tables.
- The existing UI proposal `docs/architecture/NEXT_GEN_UI.md` describes a human face and heart/orb composition. That part is superseded by the product decision above and must not be treated as the current target.

### Repository configuration observed

- Squash merge is enabled.
- Repository-level GitHub Auto-merge is currently disabled (`allow_auto_merge=false`).
- Branch protection/ruleset details were not confirmed through the connected GitHub integration; do not assume required reviews or checks are absent.

### Phase 0 risks / audit questions

1. Establish a single authoritative runtime entry path and document the native-vs-web UI startup/fallback behavior.
2. Map existing agent, computer-control, scheduler, skills/MCP, memory, and security systems to avoid duplicate orchestrators.
3. Verify actual Supabase schema/RLS/functions against the cloud task and memory adapters.
4. Identify which CI checks are required branch gates; report-only scanners must not be mistaken for blocking security gates.
5. Inspect the open PR queue and merge conflicts before any integration.
6. Run the full test suite and Windows smoke tests in a real checkout before claiming runtime verification; repository API inspection alone is not a test run.

## Phase 1 — Target architecture and contracts

Adopt a layered architecture that composes existing subsystems rather than replacing them wholesale.

### Layers

1. **Experience layer** — existing React/TypeScript UI inside Qt WebEngine, plus the native PyQt fallback. The NeuralBrain remains the central visual; UI telemetry must be sourced from real backend events.
2. **Interaction layer** — voice, text, keyboard, browser and device requests. Every entry point normalizes to a typed request with a correlation ID.
3. **JARVIS orchestrator** — owns task lifecycle, planning, dependency ordering, agent selection, budgets, cancellation, and final verification. Reuse `jarvis/agent` and the existing computer-control orchestrator where appropriate; do not create a competing task runner.
4. **Specialist agents** — research, coding, browser, computer-use, memory, workflow, system-monitoring, and communications capabilities. Each agent has a narrow typed contract and declared permissions.
5. **Tool/skills gateway** — MCP and internal ActionDispatcher tools behind one policy/authorization boundary. Tool results are treated as untrusted data.
6. **Knowledge and memory** — Supabase Postgres/pgvector and Storage where supported, with provenance, timestamps, retention, user consent, and RLS. Provider-generated claims are not automatically promoted to verified facts.
7. **Security and governance** — owner authentication, guest role, Privacy Lock, step-level risk classification, approvals for consequential actions, secrets isolation, budgets, audit trail, and emergency stop.
8. **Device and runtime layer** — local Windows agent for OS control, remote hub/device nodes over authenticated encrypted connections, cloud coordination for long-running tasks. Local actions remain on the user's machine.
9. **Observability and recovery** — structured events, traces, task checkpoints, health checks, bounded retries, crash recovery, and truthful status reporting.

### Core task lifecycle

`REQUESTED → AUTHENTICATING → PLANNING → POLICY_CHECK → WAITING_FOR_APPROVAL (if required) → EXECUTING → VERIFYING → COMPLETED | PARTIAL | BLOCKED | FAILED | CANCELLED`

A task may only report COMPLETED when its acceptance criteria have evidence. A missing provider, permission, or cloud service is a blocker, not a success.

### Required contracts

- `TaskRequest`: objective, source, owner/device identity, constraints, deadline, budget, acceptance criteria, correlation ID.
- `PlanStep`: stable ID, agent/tool, typed input, dependencies, risk tier, timeout, retry policy, expected evidence.
- `PolicyDecision`: allow/deny/approval-required, reason, policy version.
- `TaskEvent`: task/step IDs, timestamp, state, redacted summary, provenance.
- `StepResult`: status, bounded output, error class, evidence references, resource usage.
- `TaskReport`: completed/partial/blocked/failed state, acceptance criteria, tests/evidence, remaining limitations.

### Architecture invariants

- No model can grant itself permissions.
- All tools execute through the existing security/dispatch boundary.
- Parallel execution is restricted to independent, safe steps; desktop input and conflicting writes remain serialized.
- Retries are bounded and only used for retryable failures.
- Stop/cancel is always available and checked between actions.
- Credentials never enter prompts, UI state, task events, or logs.
- UI progress is event-backed; never fabricate percentages or completion.
- Cloud persistence errors are visible and do not trigger unannounced local persistence.
- No breaking rewrite of the current Brain UI or legacy fallback without parity tests.

## Phases 2–12 — Implementation sequence

### Phase 2 — Core orchestrator hardening
Audit and consolidate the existing AgentService/TaskRunner/computer-control orchestrator. Add typed request/result contracts, correlation IDs, lifecycle invariants, bounded queueing, idempotency, and integration tests. Remove duplication only after proving call-site compatibility.

### Phase 3 — Specialist multi-agent system
Add a registry and contracts for research, coding, browser, computer-use, memory, workflow, system, and communications agents. Start with deterministic routing; model-assisted routing must be schema-validated and policy-checked. Do not grant agents unrestricted shell or desktop access.

### Phase 4 — Execution engine
Harden dependency graphs, safe parallel reads, sequential mutations, background jobs, pause/resume/cancel, deadlines, retry classification, checkpoints, and acceptance-criteria verification. Add task budgets and resource limits.

### Phase 5 — Cloud memory and knowledge
Audit existing Supabase migrations, RLS, Edge Functions, pgvector and adapters. Unify episodic, semantic, procedural and task memory with provenance, consent, retention, deduplication, retrieval limits, and opt-out tests. Cloud failures must be explicit.

### Phase 6 — Skills, MCP and workflow automation
Unify the skill registry and MCP gateway with schemas, capability declarations, trust levels, versioning, timeouts, audit records, and safe workflow templates. Add scheduled workflows only with owner-defined scope and budgets.

### Phase 7 — Computer and browser control
Consolidate the existing browser and desktop controllers. Require named targets, screen re-observation, origin/domain restrictions, download handling, isolated browser profiles, dry-run, action budgets, and approvals for consequential actions.

### Phase 8 — Security and identity
Audit multi-owner enrollment, guest notifications/monitoring, role separation, voice/PIN fallback, Privacy Lock, device pairing, token revocation, secret storage, RLS, and audit-log redaction. Fail closed when authorization state cannot be established.

### Phase 9 — Voice and realtime interaction
Preserve Gemini Live as the current primary low-latency voice path. Improve interruption, VAD, streaming, Sinhala/English handling, provider fallback, device routing, and observable latency. Optional TTS providers must not weaken privacy or playback recovery.

### Phase 10 — Multi-device runtime
Separate the cloud/hub coordinator from the local Windows execution agent and phone/tablet clients. Use authenticated pairing, encrypted transport, least-privilege device capabilities, heartbeat, offline states, and remote revocation. Keep local machine control local.

### Phase 11 — Neural Brain UI and observability
Preserve the existing NeuralBrain/spherical visual and its current identity. Do not add a human face or Heart Reactor. Improve only event-backed agent/task states, accessible controls, responsive glass panels, performance tiers, error/recovery states, and parity between React UI and native fallback.

### Phase 12 — Reliability, release and operations
Run full Python, frontend, security, Supabase, and Windows verification. Add end-to-end smoke tests, install/upgrade checks, migration rollback guidance, health diagnostics, resource baselines, release notes, and a known-limitations report. Merge only when the repository's actual required gates are green and review/conflict conditions are satisfied.

## Merge policy

- Work on a feature branch and use focused commits/PRs.
- Do not merge Draft PRs.
- Do not merge with failing, pending, skipped-required, or unknown required checks.
- Do not bypass configured review approvals or branch protections.
- Squash merge after CI/security/review requirements are satisfied and the PR head has not changed since verification.
- Repository-level GitHub Auto-merge is disabled at the time of this audit; enabling it requires a repository setting change by an authorized GitHub administrator. Until then, merge eligibility must be checked explicitly for each PR.


### Phase 2 preliminary code-map (audit extension)

The repository has two orchestration surfaces that overlap but are not interchangeable:

- `jarvis/agent/AgentService` + `TaskRunner`: general multi-step assistant tasks, typed `TaskStep` kinds, dependency graph, bounded parallel read execution, cloud task persistence, screen vision, browser automation, and policy checks.
- `jarvis/computer_control/orchestrator/HostAgent` + `jobs.run_objective`: computer-control-specific plans, app-agent registry, shared step context, trace, limited recovery, expectation verification, and JobManager/StateBus progress.

The computer-control host delegates individual actions through the existing computer-control runner/policy layer; the general agent runner has a separate plan/model and task-state contract. A wholesale replacement of either stack would risk breaking the existing computer-control tool contract and background-job lifecycle.

**Phase 2 decision:** keep the computer-control HostAgent as a specialist execution adapter initially, and make the general AgentService/TaskRunner the candidate top-level lifecycle owner only after a compatibility adapter is designed and tests cover cancellation, approvals, trace/evidence, cloud persistence, and existing `cc_task` JobManager behavior. Do not merge the two codepaths by renaming classes or deleting files. First add contract/adapter tests; then migrate one entry point at a time.

Current evidence includes `jarvis/tests/test_agent_integration.py`, `test_agent_runner.py`, `test_computer_control_orchestrator.py`, and `test_computer_control_workflows.py`. Repository API inspection does not execute these tests; they remain required verification in CI/local checkout.
