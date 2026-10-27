# JARVIS Brain Engine — Architecture and rollout

## Goal

Give JARVIS a stronger, consistent reasoning/context layer without replacing the existing Gemini Live audio/vision session, the hybrid text-provider router, the action registry, or security confirmation gates.

## Request paths

1. **Primary voice/vision path:** Gemini Live remains responsible for low-latency audio, vision, and tool calls. `core.brain_protocol.build_brain_protocol()` adds concise quality rules to the Live session system instruction. The available `deep_reasoning` plugin remains the route for genuinely complex questions. Tool execution still goes through the current action/plugin registries and `core.security`.
2. **Text fallback:** `core.brain_engine.BrainEngine` assembles a bounded request profile, recent labelled user/assistant turns, and optional provider-safe memory context, then calls the existing `query_text_fallback()` provider failover. Provider configuration and credential handling remain in the existing router.
3. **Memory:** retrieval uses `memory.memory_controller.retrieve_context()` and requests `provider_safe=True`. Content is redacted again and labelled with provenance/verification metadata. The engine does not promote provider-generated answers directly into confirmed semantic facts; the app's separate end-of-session summary workflow remains in force.
4. **Verification:** the engine reports provider/model/mode/latency and local context counts, not credentials or memory text. The fallback must not claim to perform browser/computer actions because it has no action tools. The Live path continues to verify tool results and protected operations using existing guards.

## Boundaries

- History is limited to 12 labelled user/assistant entries, 8,000 characters total and 1,600 characters per entry.
- The current request is limited to 12,000 characters.
- At most 5 provider-safe memory records and 4,000 characters of serialized record data are included.
- When memory retrieval fails, JARVIS continues without memory and logs only the exception type.
- If the memory-sharing preference is disabled, this engine does not call the memory retriever.
- Context labels and prompt instructions reduce confusion but are not a substitute for model safety, tool authorization, or data validation.

## Model/provider choice

The engine intentionally reuses the configured hybrid router instead of hardcoding a model or silently introducing an extra API/provider. The configured provider, failover settings, and local Ollama fallback remain authoritative. A more capable model can be selected through the app's existing provider configuration once a model is configured and available.

## Tests

`tests/test_brain_engine.py` verifies bounded/labelled conversation context, provider-safe memory context, the memory opt-out, failure tolerance, task profiling, and prompt routing without making live API calls. The repository's existing Python checks continue to compile the project, run runtime dependency diagnostics, and execute pytest.

## Limits

This is not model training and does not give JARVIS the same weights or capabilities as ChatGPT. It improves orchestration, context selection, prompt quality, and verification while relying on the configured model/provider. Real microphone-to-speaker testing and live provider quality/cost assessment still require running JARVIS with the owner's local configuration.
