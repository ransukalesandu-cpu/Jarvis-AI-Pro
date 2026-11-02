# Part 3C — Background Lifecycle and Speed Optimization

Part 3C completes the task lifecycle and performance layer around the existing
Part 3A planner and Part 3B bounded parallel read engine.

## Background task management

- The background runner remains a single bounded worker; queued tasks are
  persisted to the existing cloud task store before they are reported as queued.
- A configurable queue cap (default 8, hard cap 64) applies backpressure instead
  of allowing unbounded memory growth.
- Queue capacity checks and queue insertion are serialized to prevent concurrent
  submitters from exceeding the limit.
- Status now includes queue count/capacity and aggregate performance telemetry.
- Pause, resume, cancel, restart recovery, and live EventBus progress remain
  available through the existing APIs.

## Safe task retry

- retry_task creates a fresh task with the original objective and criteria.
- It is allowed only for failed tasks whose already-completed steps were
  read-only (inspection, file reads, public browser reads, verification, notes).
- If completed work may have changed files, run commands, or controlled the
  desktop, automatic whole-task replay is refused to prevent duplicate side
  effects. The user can inspect the report and choose a narrower recovery.
- The new task continues through the normal planner, owner revalidation,
  PolicyEngine, Privacy Lock, and consequential-action approval.

## Performance and provider routing

- A bounded in-memory monitor tracks aggregate task durations, p95 duration,
  completion/failure/cancellation counts, and success rate.
- Telemetry retains no objectives, prompts, outputs, credentials, or file data.
- The text HybridLLMRouter keeps the configured preferred provider first and
  ranks configured fallbacks using recent observed provider latency and failure
  history. A provider failure is deprioritized; successful latency uses a
  smoothed moving average.
- Offline routing still prefers local Ollama first, then health-ranked configured
  cloud providers. Gemini Live audio routing is unchanged.
- Provider health is observable as aggregate provider names, latency, successes,
  and failures only; keys and request content are never exposed.
- Default parallel file-read workers are reduced to two for lower-memory laptops.

## Bounds and compatibility

- No new third-party dependencies, persistent local cache, or always-on pool.
- Existing cloud-only task persistence remains unchanged.
- The queue, telemetry sample history, retry limits, provider list, and worker
  count are all bounded.
- Browser actions remain read-only and thread-affine.
- Existing UI and voice integrations continue to use the same TaskRunner,
  EventBus, and HybridLLMRouter interfaces.

## Validation

Tests cover queue backpressure, safe retry eligibility, duplicate-side-effect
protection, bounded aggregate telemetry, provider failure-aware fallback
ordering, and the existing task, policy, and browser regression suites.
CI must pass on the latest PR head before Part 3C is considered complete.
