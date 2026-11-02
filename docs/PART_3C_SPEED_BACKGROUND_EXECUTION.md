# Part 3C — Speed and Background Execution

Part 3C completes the task execution roadmap by improving queue bounds, live
progress delivery, safe reuse of validated plans, and provider fallback speed.
It builds on the existing task runner rather than adding another runtime.

## Background task lifecycle

- The existing start/submit/resume/pause/cancel/status API remains the single
  background task entry point.
- Pending queue capacity is configurable and hard-bounded (default 32, maximum
  128); queue saturation returns an explicit error instead of consuming memory.
- Queue status includes depth and configured capacity.
- Removing queued work during cancellation also transitions and persists those
  tasks as CANCELLED, so they cannot remain indefinitely in PLANNING.
- Existing task snapshots, journal events, retry budgets, backoff, deadlines,
  pause/resume, and crash recovery remain in force.

## Live progress stream

- EventBus events receive monotonic sequence numbers.
- Consumers can subscribe live or replay events after a cursor with a bounded
  wait, making reconnecting progress panels able to catch up.
- History remains bounded; if a client cursor falls behind retained history,
  it can detect the gap from the returned sequence numbers.
- Event delivery remains isolated from UI subscriber exceptions.

## Validated plan cache

- Successful plans are cached in memory with a bounded LRU and TTL.
- Cache keys include normalized objective, acceptance criteria, workspace,
  model identity, and step limit.
- Cached plans are deep-copied on read/write so caller mutations cannot corrupt
  later tasks.
- Model-failure fallback plans are not cached, allowing the provider to recover.
- Cache size and TTL are configurable; no task output, credentials, or private
  execution results are cached.

## Provider latency-aware fallback

- The configured preferred provider is always attempted first.
- Only configured fallback providers are ranked by observed successful latency.
- Unknown providers retain the original stable provider order until measured.
- Offline mode still prioritizes local Ollama, then uses measured fallback order.
- Provider performance reports latency aggregates and sample counts only; no
  credentials or prompt content are exposed.
- Existing provider failover and total request latency fields remain compatible.

## Benchmark

Run from the JarvisAI directory:

    python -m benchmarks.benchmark_agent_engine --steps 12 --delay-ms 30

The synthetic benchmark compares sequential waits with bounded parallel
dispatch. It reports observed timings and speedup, but does not claim to model
real network, disk, browser, or Windows laptop performance.

## Security and compatibility

Owner verification, PolicyEngine, Privacy Lock, ActionDispatcher integration,
consequential-action approval, and existing retry authorization checks are
unchanged. Cache entries contain validated plans only. The queue and event
history are bounded to protect low-memory devices. No new third-party package
or always-on worker is introduced.
