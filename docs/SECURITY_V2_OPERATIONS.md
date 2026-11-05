# Security V2 — Operations guide

## First-time setup (once, on the owner's PC)
1. `python scripts/security_owners.py` — create the first owner (becomes the primary administrator) and note the **recovery code**. It is shown once and stored only as a hash.
2. Restart JARVIS. With at least one owner, every launch starts in **Guest Mode** with a visible notice.
3. Sign in by typing `/owner <pin>` in the command box (or the PIN when the old prompt asks). PINs are checked locally and never reach the model, voice pipeline or logs.

## Day to day
- Owner commands: "show Guest history", "delete the latest Guest history" (asks for confirmation), "security status", "turn Guest monitoring off/on" (off needs a recent second-factor confirmation).
- The HUD Security panel shows the same: Guest banner, ON/OFF, owner list, history summary, delete latest.
- Guest log entries expire after 7 days (local). Nothing else about Guests is stored.

## Adding / removing owners
Use `scripts/security_owners.py` (add, revoke, set-admin, enroll-voice). Revoking needs an administrator with a recent step-up; the last administrator cannot be revoked. Lost the only admin PIN: use the recovery code.

## Cloud (not active until you deploy it)
The Guest audit table and purge function are in `supabase/migrations/202611050001_security_v2_guest_audit.sql`. **They are not applied anywhere.** To adopt: review the SQL, apply to a Supabase branch/staging project, run the advisors, then production; add an Edge Function that writes events with the service role (never put that key in the desktop app). Until then the 7-day purge runs only locally.

## Verifying on Windows (not done by the developer)
Run `python -m pytest jarvis/tests/test_security_v2_*.py`. The Windows CI job runs these too. Then manually: start JARVIS (notice appears), ask a Guest-blocked thing ("run a command") and confirm it is refused, sign in with `/owner`, open the Security panel.

## Incident basics
- Suspect a PIN leak: change it (`change_pin`) and revoke/re-add the owner; check `scripts` audit ledger for `owner_auth` events.
- Turn monitoring OFF only for a reason; baseline protections stay on either way.
