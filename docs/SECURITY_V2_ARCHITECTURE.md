# SECURITY V2 — architecture (Phase 1)

Status legend: **done** = in code with tests, **planned** = later phase, **not possible here** = needs the owner's machine or a live project.

## Flow in the actual code

```
tool call (voice / text / agent / trigger)
   -> live_tools.py  ->  security.guard(name, params, run)
        1. tier_for()                         risk tier (SAFE / SENSITIVE / DANGEROUS)
        2. identity.guest_mode_active()?      Guest session -> IdentityManager.authorize() -> default-deny   [Phase 1, done]
        3. Privacy Lock / Voice-ID recheck / untrusted-content provenance
        4. step-up (PIN / voice) for SENSITIVE+DANGEROUS when owner access is not allowed
        5. ActionDispatcher.can_dispatch
        6. Full Access shortcut -> run (audited)            (default on today; see "Security ON/OFF")
        7. rate limit, then human confirmation for DANGEROUS
        8. run + audit ledger (HMAC chain)
```
No new framework or server: the tier table in `core/security.py` stays the policy table; `core/identity.py` adds who is acting.

## Identity and sessions (done: `core/identity.py`)

| State | Meaning |
|---|---|
| UNAUTHENTICATED | process start / after `end_session` |
| GUEST | `start_guest()` was called; Guest rules apply in `guard()` |
| OWNER_AUTHENTICATING | owner auth started |
| OWNER_AUTHENTICATED | live owner session (12 h) bound to one Owner ID |
| STEP_UP_REQUIRED | owner signed in, stronger proof demanded |
| SESSION_EXPIRED | timeout; behaves as Guest level |
| REVOKED | owner removed; all access denied |

Allowed transitions are listed in `_ALLOWED`; anything else raises `IdentityError`.
`Session` is a frozen dataclass: nothing outside the manager can change a role.

**Owner sessions** are created only by `complete_owner_auth(OwnerProof)`. `OwnerProof` is minted by `mint_owner_proof()`, which accepts only the methods `pin`, `voice`, `voice+pin`. A task password is not one of them.

**Task passwords** go through `verify_task_credential()`, which returns a `TaskCredentialResult` and cannot reach the manager (tested at the bytecode level). A correct task password leaves a Guest a Guest (Requirement C; tests in `test_security_v2_phase1.py`).

**Guest default-deny:** a Guest may use only `GUEST_ALLOWED_TOOLS` (`weather_report`, `web_search`, `quiz`, `battery_status`) and only at tier SAFE. Unknown tools are denied. Categories (`category_for`) map tools to the spec's permission categories for audit.

## What Phase 1 deliberately does not do yet

- Guest Mode is not switched on anywhere in the app: `guard()` applies Guest rules only after `start_guest()`. Until Phase 3 wires the start-up path and the visible notice, behaviour is unchanged.
- `AuthManager` (single PIN, Voice ID roles) is not yet connected to `IdentityManager`; multi-owner enrollment, per-owner PIN and Voice ID profiles are Phase 2. Today `identity` is in-process only.
- Security ON/OFF, Guest audit storage, Supabase tables, retention and UI are Phases 3-5.
- `JARVIS_PERSONAL_MODE` (environment variable) and Full Access (default on) are unchanged. They are documented in the audit as weaknesses; the ON/OFF design in Phase 4 must define the baseline that survives both.

## Fix shipped in this phase: untiered PC tools

`run_command` (PowerShell/cmd), `ui_automate`, `open`, `phone_control`, `files` (write/move/copy/delete), `software` (install/upgrade/uninstall), `email` (send) and `jarvis_settings` (set) had no explicit tier and fell back to SENSITIVE, which runs without confirmation. They are now DANGEROUS (reads stay SAFE/SENSITIVE). With Full Access on (the default) day-to-day behaviour is unchanged; with it off they now ask first, as their older equivalents (`file_controller`, `email_gmail`) already did.

`test_every_action_has_an_explicit_or_reviewed_tier` is a ratchet: a new tool must get an explicit tier or be added, on purpose, to the reviewed-default list.

## Limits

In-process Python cannot stop code that already runs inside JARVIS from calling the manager directly; the proof object and frozen session stop accidents and logic bugs, not a compromised process.

---

# Phase 2 — multiple owners (`core/owner_registry.py`, `scripts/security_owners.py`)

**Done and tested:** owner registry, per-owner PIN (Argon2) and per-owner Voice ID role, lockout, revocation,
administrator rules, recovery code, local admin CLI. **Not done:** `AuthManager` and the running app do not
consult the registry yet (Phase 3 switches the login path); the old single-PIN vault keeps working unchanged.

## Owner model
Each owner row: UUID, display name, Argon2 PIN hash, `is_admin`, own Voice ID role `owner-<id8>`, `voice_enrolled`,
`status` (`active`/`revoked`), timestamps. Table `security_owners` lives in the existing owner SQLite store
(`OwnerStore`); no new database. At most 8 owners.

## Administration model
- First owner (created only through the local `init` command, only while no owner exists) = primary administrator.
- All owners have normal owner capabilities; administrators can additionally add, revoke, promote and demote.
- Management requires a live owner session **and** a fresh step-up (PIN re-entry within 5 minutes).
- The last active administrator cannot be revoked or demoted.
- A Guest cannot enroll: `bootstrap_first_owner` refuses once any owner exists and `add_owner` demands an administrator session.
- Because `init` is an unauthenticated first-run action, it is reachable only through the local CLI; no voice tool exposes it.

## Authentication
- `authenticate_pin(pin, owner_id="")` returns an `OwnerProof` or `None`. 3 wrong PINs lock **that owner** for 60 s, doubling per further failure up to 15 min; a locked owner refuses even the right PIN until the delay passes. Other owners are unaffected. Lockout state is in memory (a restart clears it), which is a known limit.
- `authenticate_voice(audio, owner_id="")` verifies against each enrolled owner's own profile and returns the best match. It returns `None` when Voice ID is disabled or unavailable: it never uses `voice_id.identify_speaker`, whose fallback treats everyone as the owner when Voice ID is off.
- `login(manager, proof)` is the only bridge to `IdentityManager`.
- Voice alone is single-factor (`strength=1`); actions that need two factors use step-up with the PIN.

## Recovery and lockout avoidance
`init` prints a recovery code once; only its Argon2 hash is stored. `recover` takes the code and a new PIN, restores an administrator (never promotes a non-admin), clears that owner's lockout, and **rotates the code**. 5 wrong codes per run stops further attempts until restart. Losing both every PIN and the code means no in-app recovery: the owner must reset the owner database (`security_owners`) by hand, which is documented as a manual, data-destroying step.

## Voice profiles
One profile per owner, created by `enroll-voice` after PIN proof; re-enrolling replaces it; revocation deletes it. Audio is not stored. Embeddings stay local (DPAPI on Windows, AES-GCM elsewhere, from the existing `voice_id` module).

## Not measured
False-accept/false-reject rates, Sinhala vs English performance, and the Resemblyzer/SpeechBrain comparison need real recordings on the owner's Windows machine. No claim about accuracy is made here.
