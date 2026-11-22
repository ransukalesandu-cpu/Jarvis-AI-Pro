# Multi-model compare

P3 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`. Tool: `compare_models`.

- "Ask Claude, Gemini and GPT which logo style is better for a coffee shop" → the same prompt goes to each
  provider **in parallel** (max 5, 90 s timeout; a hung provider never blocks the others). JARVIS gives a short
  verdict; "show the full comparison" repeats every answer.
- Each answer shows model, latency and a rough cost estimate (list prices, chars/4 tokens — an estimate only).
- "Claude won" → `pick_winner`, counted per task label (coding, writing, …); "which AI wins most?" → `wins`.
  Use that to decide a task route with `ai_providers set_route` (P8) — nothing is changed automatically.
- Providers without a key fail fast with a clear message; empty provider list = all configured + local Ollama.
- Tiers: compare/show/wins SAFE, pick_winner SENSITIVE.
