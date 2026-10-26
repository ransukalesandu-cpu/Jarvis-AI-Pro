# Supabase hybrid provider setup

JARVIS's existing Gemini Live session remains the primary realtime voice/vision/tool path. The Supabase route is used by `HybridLLMRouter` for text fallback and SmartHybridAssistant chat only; it does not replace Live audio or the action dispatcher.

## Server-side provider secrets

In Supabase project `JARVIS-AI-PRO`, configure these Edge Function secrets (values never belong in the repository):

- `SUPABASE_SERVICE_ROLE_KEY` (server-side only; required for protected database RPCs)
- `JARVIS_HOST_ENROLLMENT_TOKEN` (temporary token for first host enrollment)
- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `GROQ_API_KEY`
- `ANTHROPIC_API_KEY`

The Edge Function is `jarvis-cloud-ai`, requires a valid Supabase Auth JWT, and validates it through the Auth API. The public/anon key alone is not an authenticated session.

## Desktop environment

Set only these public configuration values for the JARVIS process; do not commit local values to Git:

- `SUPABASE_URL=https://pitsvturrmtqrhfxtclg.supabase.co`
- `SUPABASE_ANON_KEY=<Supabase anon/publishable key>`

No email or password is required. The client creates an anonymous Supabase Auth session and refreshes its access token in memory. Enable anonymous sign-ins in Supabase Auth settings. The host enrollment token is only needed for first host-device registration; remove it from the desktop environment after enrollment.

## Current scope and limitations

- Provider selection and bounded failover use the existing hybrid router order.
- Cloud text requests support Gemini, OpenAI, Groq, and Anthropic.
- Gemini Live's primary audio/vision/tools pipeline remains unchanged and still uses its existing Gemini configuration. This change does not move realtime audio streaming to Edge Functions.
- A cloud provider error can cause the existing router to try another configured provider; this may incur usage on more than one provider for a request.
- Provider API keys stay in Supabase Edge Function secrets. Never put them in the desktop app, tracked config, or GitHub.
- CI/unit tests do not prove provider keys are valid. Validate each provider with a low-cost prompt and check provider quotas/billing before routine use.
