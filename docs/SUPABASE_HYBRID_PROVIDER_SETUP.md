# Supabase hybrid provider setup

JARVIS's existing Gemini Live session remains the primary realtime voice/vision/tool path. The Supabase route is used by `HybridLLMRouter` for text fallback and SmartHybridAssistant chat only; it does not replace Live audio or the action dispatcher.

## Server-side provider secrets

In Supabase project `JARVIS-AI-PRO`, configure these Edge Function secrets (values never belong in the repository):

- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `GROQ_API_KEY`
- `ANTHROPIC_API_KEY`

The Edge Function is `jarvis-cloud-ai` and requires a signed-in Supabase Auth user. The public/anon key by itself is intentionally insufficient.

## Desktop environment

Set these environment variables for the JARVIS process; do not commit them to Git:

- `SUPABASE_URL=https://pitsvturrmtqrhfxtclg.supabase.co`
- `SUPABASE_ANON_KEY=<Supabase legacy anon JWT or publishable key>`
- `SUPABASE_EMAIL=<Supabase Auth user email>`
- `SUPABASE_PASSWORD=<Supabase Auth user password>`

Use a dedicated Supabase Auth account for JARVIS. The Python client signs in with Supabase Auth, caches the access token in memory, and refreshes it using the refresh token. Provider API keys remain server-side.

## Current scope and limitations

- Provider selection and bounded failover use the existing hybrid router order.
- Cloud text requests support Gemini, OpenAI, Groq, and Anthropic.
- Gemini Live's primary audio/vision/tools pipeline remains unchanged and still uses its existing Gemini configuration. This change does not move realtime audio streaming to Edge Functions.
- A cloud provider error can cause the existing router to try another configured provider; this may incur usage on more than one provider for a request.
- The desktop environment must be configured and a Supabase Auth user must exist before live cloud requests work.
- CI/unit tests do not prove provider keys are valid. Validate each provider with a low-cost prompt and check provider quotas/billing before routine use.
