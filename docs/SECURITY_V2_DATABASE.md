# Security V2 — Database and Security ON/OFF (Phase 4)

## Status (honest)
| Item | Status |
|---|---|
| SQL migration `supabase/migrations/202611050001_security_v2_guest_audit.sql` | **Applied** to the JARVIS-AI-PRO project on 2026-11-24 (migration `security_v2_guest_audit`). Verified: RLS on, `anon`/`authenticated` have no table or purge-function access, `service_role` can write, table empty. Advisors: only the expected INFO "RLS enabled, no policy" (deny-all by design). |
| Server-side 7-day purge | `jarvis_purge_expired_guest_audit()` is deployed. **No hourly schedule yet:** `pg_cron` is not enabled on the project, so nothing calls it automatically. Enable `pg_cron` and re-run the `do $$ … $$` block, or call it from a scheduled Edge Function. Expired rows still fail the 7-day check and are purged on the next call. |
| Edge Function / desktop sync client that uploads Guest events | **NOT IMPLEMENTED.** Guest events currently live only in the local `owner.db`. |
| Local Security ON/OFF | Implemented and unit tested. |
| Guest log local expiry (7 days) | Implemented and unit tested. |

## Schema rules
- Table `jarvis_guest_audit_events`: fixed event types, fixed categories, outcome, a metadata object limited to the keys `tool`, `tier`, `reason`, and a hard `expires_at <= created_at + 7 days` check. No column can hold speech, audio, screenshots, commands, paths or passwords.
- RLS enabled; `anon` and `authenticated` have no grants; only `service_role` (used by an Edge Function, never by the desktop app) can read or write.
- No service-role key is added to the desktop app, QWebChannel or JavaScript.

## Applying it
Applied directly to production (JARVIS-AI-PRO) on the owner's request on 2026-11-24, after checking the table did not exist yet. For a new project: `supabase db push`, then confirm RLS with the Supabase advisors.

## Security ON/OFF
- Scope: **OFF stops Guest monitoring only** (no new Guest log entries; the Guest notice says logging is off). Existing entries stay and still expire at 7 days.
- Who: a signed-in owner only; turning OFF also needs a step-up (second factor within 5 minutes). Guests are denied by `guard()` and by the tool itself.
- Always enforced, in both states: Guest default-deny allowlist, owner session for dangerous tools, hashed PINs never sent to voice/cloud AI, task passwords never elevate, owner/security/history changes need an owner, Privacy Lock and the action ledger.

## Known gaps carried forward
- Full Access defaults to on and `JARVIS_PERSONAL_MODE` relaxes confirmation prompts for the legacy single-owner path. They are unchanged in this phase; Guest sessions are not affected because the identity check runs first.
- Voice-ID model accuracy (false accept/reject) is unmeasured; it needs your recordings.
- Biometric templates stay local (DPAPI/AES-GCM); nothing biometric is sent to the cloud by this change.
