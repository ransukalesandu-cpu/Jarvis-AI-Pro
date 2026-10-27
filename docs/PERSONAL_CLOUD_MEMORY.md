# JARVIS Supabase Personal Profile Memory

## What it does

When enabled, JARVIS can remember a small set of facts the user explicitly says about themself, then use relevant facts to personalize later Live and text-fallback replies. Example categories include the user's preferred name, whether they have siblings, study/work context, interests, goals, language, and response preferences.

The feature uses the existing authenticated Supabase identity for the local installation. Facts are stored in public.jarvis_personal_memories and linked to the Supabase Auth user ID. A separate jarvis_personal_memory_settings table records opt-in. Both tables have RLS enabled and deny direct anon/authenticated table access; the Edge Function verifies the request's Auth user and applies user-scoped database operations server-side.

## Privacy defaults and boundaries

- Personal cloud memory defaults **off**. Enable personal_cloud_memory through JARVIS's allowlisted settings tool; enabling asks for confirmation and writes consent to Supabase first.
- The local setting, server-side consent and persistent OS credential-store session must all be available before the feature reads or writes personal facts.
- The app checks for personal-disclosure cues before starting a separate extraction request. Only the single matching utterance is sent to the configured text provider for extraction; the memory endpoint never receives raw chat histories.
- Each stored fact must include a short evidence quote from that exact utterance and its value must be present in that quote. Local and Edge Function validators use an allowlist and reject credential, contact, URL and common address patterns. Extracted/model-generated guesses are not promoted to facts.
- Memory is reference data, never instructions. The current user's correction should take priority. The memory endpoint does not store a provider's answer as a user fact.
- User can say “list my personal memory”, “forget my name” / another fact category, or “clear my personal memory”. Deleting a category or clearing all profile facts goes through JARVIS's confirmation gate.
- Turning the feature off blocks future capture and retrieval on this device. If the network is unavailable during disable, server-side consent may remain on until reachable; the local feature still stays off. Use the clear operation when connectivity returns to remove already-stored profile facts.
- Supabase anonymous identity is device/session scoped here; it is not a cross-device user account unless account linking is added separately.

## Supported fact keys

name, siblings, family_context, education, occupation, interests, preferences, goals, language, communication_style.

One value per key is kept, so a later directly stated correction replaces the previous value for that key. Sensitive facts and raw transcripts are not intended to be stored.

## Supabase deployment

1. Apply supabase/migrations/202610270001_jarvis_personal_memory.sql to the intended JARVIS-AI-PRO project.
2. Deploy supabase/functions/jarvis-personal-memory/index.ts with domain.ts and keep verify_jwt set to true.
3. Keep SUPABASE_SERVICE_ROLE_KEY server-only. Never put it in api_keys.json, a desktop configuration file, or a public repository. The desktop uses only SUPABASE_URL and SUPABASE_ANON_KEY.
4. Enable Supabase anonymous sign-ins and make sure the local installation can persist the anonymous refresh token in Windows DPAPI, macOS Keychain, or Linux Secret Service. The feature fails closed if no stable identity is available.
5. Run the Python tests and the Deno validation tests. Run Supabase security advisors and verify the tables, RLS state, and jarvis-personal-memory deployment status after applying the migration.

The Edge Function uses the existing per-user nonce/replay protection and cloud daily quota. Its database calls use the authenticated user ID; client input never chooses a different user ID.
