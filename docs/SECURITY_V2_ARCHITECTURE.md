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

## Phase 3 — Guest Mode

**Status: implemented locally (PARTIAL overall: no server copy yet, see Phase 4).**

- **When it starts.** `GuestService.start()` runs at launch (`JarvisLive._start_guest_session`) only if the owner registry has at least one owner. Installs that still use the single legacy PIN are unchanged.
- **Visible notice.** The notice (`guest_audit.NOTICE`) is written to the HUD log and read out once. It says what is logged (start/end, blocked actions as tool name + risk level + reason code) and what is not (speech, passwords, keystrokes, audio, screen), and that entries are deleted after 7 days.
- **What is stored.** Only `guest_audit_events` rows: random session id, event type from a fixed list, category from a fixed list, outcome, timestamps, and up to three allowlisted metadata keys (`tool`, `tier`, `reason`). There is no free-text column; unknown keys and values are dropped before writing (tested).
- **Isolation.** `guard()` denies by default for a Guest and records a `restricted_action_denied` event. The `guest_history` tool is DANGEROUS-tier, not on the Guest allowlist, and re-checks for an owner session inside its handler.
- **Passwords.** Only `OwnerRegistry.authenticate_pin` (or voice) can end Guest Mode. Typed text counts as a credential attempt only when the legacy gate is asking for a PIN or the text starts with `/owner `; it is checked locally and never reaches the model or logs. A task/website password is checked by `verify_task_credential`, which cannot touch identity (tests cover both).
- **Owner view.** After owner sign-in the owner is told what Guest sessions attempted since they last looked. `guest_history` offers `summary`, `latest` and `delete_latest` (needs `confirm=true`; deletion is re-read and verified before it is reported).
- **Retention (local).** Rows carry `expires_at = ts + 7 days`; they are purged at Guest start and before every read. Server-side purge is Phase 4.

**Known limits.** When owners exist, the legacy single PIN no longer signs anyone in as owner during a Guest session (by design: it has no owner identity). Voice sign-in during Guest Mode is not yet wired to the live audio path (the registry supports it). Windows behaviour and real microphone paths were not exercised here.

## Phase 5 — Security UI

The existing HUD security panel now embeds `GuestSecurityView` (`ui/panels/guest_security_view.py`), fed by `core/security_view.py`.

- **Guest** sees only the Guest notice and a "restricted" line. Owner names, history and all controls are hidden, and the view-model does not even return that data for a Guest.
- **Owner** sees who is signed in, the owner list (name, admin, revoked), a short Guest history summary, a Security ON/OFF button and "Delete latest Guest history". Delete and turn-OFF ask for confirmation first.
- The panel has no privileges of its own. Its actions call the same gated code as the voice tools (step-up for OFF, verified delete), and re-check for an owner session.
- **Legacy** (no owners yet): a one-line hint to run `scripts/security_owners.py`.

**Not in the UI yet:** adding/revoking owners and enrolling voices (still `scripts/security_owners.py`, because adding an owner needs a PIN field with its own review), and a typed owner-PIN box (sign-in is the `/owner <pin>` text command). The panel was only tested headless (offscreen Qt); I have not seen it rendered on a real screen or on Windows.
