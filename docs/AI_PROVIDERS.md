# AI provider manager and usage budget

P8 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`. Tool: `ai_providers`.

- "Which AI providers are set up?" → `status`: key set / no key / local, measured speed, calls today.
  Keys are never read out or changed by voice — they stay in `config/api_keys.json`.
- "Test Claude" → `test`: a tiny one-word request to that provider only.
- "Use Claude for coding" → `set_route` (task categories from `core/task_router.py`: coding, planning,
  reasoning, writing, simple, …); "show task routes" → `routes`.
- "How much AI did I use today / this month?" → `usage`: calls, estimated tokens and cost per provider.
- "Warn me if I spend more than 2 dollars a day" → `set_budget` (0 = off). The alert goes to the HUD log
  and your paired Telegram chat, once per day.

## Usage meter (`core/usage_meter.py`)
Every successful hybrid-router answer (and every single-provider ask) records provider, model, character
counts and latency — never prompts, answers or keys — in `<data>/usage/YYYY-MM.json`. Tokens = chars/4 and
list prices are estimates; check each provider's console for exact billing. Custom prices:
`<data>/usage/settings.json` → `"prices": {"claude": [3, 15]}` (USD per 1M input/output tokens).

Tiers: status/test/routes/usage SAFE; set_route/set_budget SENSITIVE.
