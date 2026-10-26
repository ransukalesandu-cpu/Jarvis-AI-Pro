# Step 1B — Hybrid Routing & RAM Audit

## Scope and safety
This phase preserves the Gemini Live voice/vision/tool pipeline and does not redesign the UI. No credentials, prompts, responses, or private memory are written to diagnostics. The changes are on `audit/hybrid-routing-ram-step-1b`; this PR must not be merged until CI and review pass.

## Request-path trace (static inspection)

- **Primary real-time voice/vision/tools:** `JarvisAI/main.py` uses the Google GenAI client and the Gemini Live session. This is not routed through `HybridLLMRouter`.
- **Typed/text fallback when Gemini Live is disconnected:** `main.py` reads `config/api_keys.json`, creates `HybridLLMRouter`, calls `query()`, and presents a text answer. Its system prompt explicitly denies Live tool/computer-control capability.
- **Hybrid text provider order:** preferred configured provider first, then configured cloud providers (Gemini, Groq, OpenAI, Claude). If the connectivity heuristic says offline, existing behavior tries local Ollama first and then configured cloud providers. This preserves the product's offline fallback; this PR does not silently disable it.
- **One-shot provider settings:** `core/ai_providers.py` uses `core/provider_settings.py` and `ai_provider` for one-shot OpenAI/Anthropic work. **Local LLM backend setting:** `core/llm_client.py` uses `llm_provider` to select Ollama versus an OpenAI-compatible local server. These are different contracts. The hybrid text router now uses `hybrid_provider` when set, otherwise `ai_provider`; it no longer treats the local-backend `llm_provider` as the hybrid cloud preference. `anthropic` is mapped to the router's canonical `claude` label.
- **SmartHybridAssistant / SmartIntentRouter:** modules exist, but static tracing did not establish a call from the primary `main.py` Live path. They should not be assumed to be active in normal voice requests without runtime evidence.
- **Local inference/TTS:** Ollama is only used through the hybrid text router. The project includes optional local TTS/model code, but its presence alone does not prove the primary Gemini Live voice path loads those models. This audit does not remove optional/offline features.

## RAM and audio findings

- The Live playback queue is created as `asyncio.Queue()` at session startup, with no max size. PCM is enqueued in approximately 50 ms slices and drained by the playback worker. If speaker output stalls, the queue can grow; this is a plausible RAM/latency risk, not a measured leak.
- Existing playback code includes a ~300 ms prebuffer, short-tail flush at turn completion, interrupt draining, and underrun diagnostics.
- **No queue bound/drop policy was added in this phase.** Dropping queued PCM can truncate valid speech. A safe backpressure strategy needs Windows runtime tests under slow/stalled playback, short replies, cancellation/barge-in, and sustained output before changing queue semantics.
- The new diagnostic line reports process RSS (when psutil is available), queue depth, selected provider, request latency, and speaking/idle state. It is best-effort and contains no user content or credential values.
- Provider credential diagnostics report only which providers have a non-empty key from config/environment. This proves presence, not validity or successful API connectivity.

## Automated checks

New/updated tests cover:
- Explicit `llm_provider` precedence and `ai_provider` fallback mapping.
- Credential-presence reporting without exposing values.
- Runtime diagnostic field contents and safe behavior when queue depth is unavailable.
- Existing hybrid failover and offline Ollama behavior.

CI results are intentionally not stated here before GitHub Actions runs on this branch. Actual provider connectivity, memory measurements, and microphone-to-speaker behavior require runtime checks on the target Windows machine with real configured keys; never paste keys into an issue or PR.
