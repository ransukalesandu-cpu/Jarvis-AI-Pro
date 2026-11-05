# Task 6 audit: brain/router and agent engine

Checked against the v2 goals; no code change was needed.

| Goal | Where it already lives |
|---|---|
| Provider failover | `core/hybrid_llm_router.py` ladder (gemini/groq/openai/claude/ollama), `provider_fallback.py` tool-using Claude first, then text ladder |
| Demote failing providers | `_provider_failures` counter, reset on success |
| Latency awareness | `_record_provider_latency`, per-call `provider_latency_ms` |
| Task-aware routing | `core/task_router.py` (`classify`, opt-in `task_routing`) |
| Step/attempt/retry/time budgets | `agent/runner.py` `RunnerConfig` (`max_steps`, `retry_budget`, backoff) |
| Loop detection | `loop_detection_repeats` (3 identical failures stop the task) |
| Interruptible backoff, cancel | `_backoff`, `StepResult.stopped()` |

Not done (needs real traffic to tune, so deliberately left): time-based provider cooldowns and cost-aware routing.
