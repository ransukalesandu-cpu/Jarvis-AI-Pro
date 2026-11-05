# SECURITY V2 — Phase 0 audit

Scope: what is actually in `ransukalesandu-cpu/Jarvis-AI-Pro` `main` today (after PRs #229–#244).
Every finding names the file it came from. Items marked **not inspected** were not read in this pass
and must be treated as unknown, not as safe.

## 1. Baseline

| Item | Value |
|---|---|
| Python used for the run | 3.13.18 (project supports 3.11–3.13; owner has used 3.12) |
| Command | `QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:cacheprovider jarvis/tests` |
| Result (4 runs) | 1276 passed, 4 skipped, 0 failed in three runs; **1 failed / 1275 passed in one run** |
| Intermittent failure | One run of four had one failing test. The test name was not captured and it did not reproduce in the next three runs. Treat as a flaky test of unknown identity; it must be pinned down before Security V2 can claim a clean regression baseline. |
| Skipped | 4 (for example `test_live_replay_regressions.py` needs `JARVIS_SLOW_TESTS=1`) |
| Environment limits | Linux sandbox, offscreen Qt, no microphone, no Gemini Live, no Windows, no live Supabase project, no GitHub Actions run of new workflows |

## 2. What exists today (inspected)

| Area | Finding | Where |
|---|---|---|
| Single-owner auth state machine | `AuthManager` with states `RESTRICTED_MODE`, `FULL_ACCESS_MODE`, `CHALLENGE_MODE`, `PRIVACY_LOCK`; 3 failed PIN attempts then Privacy Lock with cooldown; state persisted for lockouts only | `jarvis/security/auth_manager.py` |
| PIN storage | Argon2 (`argon2-cffi`) hash, protected with Windows DPAPI; setting a PIN raises if argon2 is missing | `auth_manager.py` |
| Voice ID | One embedding model, similarity threshold `0.35`, profiles keyed by a *role* string (`owner` plus other roles), encrypted with DPAPI on Windows and AES-GCM elsewhere; `identify_speaker` picks the best role above threshold | `jarvis/core/voice_id.py` |
| Liveness | `verify_owner_voice` returns `(matched, score, live)`; the guard requires `live` for voice-authenticated sensitive turns | `security.py`, `auth_manager.py` |
| Central gate | `security.guard()` wraps tool dispatch: risk tier (`SAFE`/`SENSITIVE`/`DANGEROUS`), Privacy Lock check, untrusted-content provenance check, adaptive step-up auth, `ActionDispatcher.can_dispatch`, rate limit, human confirmation for `DANGEROUS` | `security.py` `guard()`, `tier_for()` |
| Dispatch coverage | `live_tools.py` routes memory, undo, screen capture and registry actions through `security.guard(...)` | `jarvis/core/runtime/live_tools.py` |
| Audit | Local append-only JSONL ledger, SHA-256 chain, HMAC per record, HMAC checkpoint outside the checkout; `verify_log()` | `security.py` |
| Injection defence | `injection_guard.wrap_untrusted` marks the turn untrusted; state changes are refused afterwards | `security.py` `mark_untrusted_seen` |
| Full Access mode | Default **on**: skips confirmation banners, tool allowlists and rate limits (Privacy Lock, owner identity and provenance check remain) | `jarvis/core/full_access.py` |
| Cloud | Every Supabase table has RLS enabled and `revoke all ... from anon, authenticated`, `grant ... to service_role`; access goes through Edge Functions (`jarvis-cloud-ai`, `jarvis-personal-memory`, `jarvis-default-owner-memory`); desktop signs requests with an Ed25519 device key held in the OS keyring | `supabase/migrations/*.sql`, `jarvis/security/host_device_identity.py` |
| Secrets in Git | `.gitignore` excludes `config/api_keys.json`, `config/secrets.json`, `.env`, `config/pin_vault.dat`, `*.vault`; no key file is tracked (`git ls-files` check) | `.gitignore` |
| Service-role key | Appears only in SQL grants; no Python, TS or workflow file embeds it | grep over repo |
| Local servers | `dashboard/server.py` binds `127.0.0.1` unless LAN is allowed (then `0.0.0.0`); bearer tokens expire and can be revoked. `hub/server.py` requires a paired device token (one-time code to token) | `dashboard/server.py`, `hub/server.py` |
| CI | `python-checks.yml` (lint, tests) and `supabase-personal-memory-checks.yml` | `.github/workflows/` |

## 3. Gaps against the Security V2 requirements

| Requirement | Status in code today |
|---|---|
| A. Multiple owners | **Missing.** There is one PIN vault and one auth state. Voice ID has *roles*, not owner identities: no Owner ID, per-owner PIN, per-owner revocation or per-owner session exists. `owner_store.py` is a rules/context store, not an identity store. |
| B. Guest notice and minimal audit | **Missing.** Anyone not authenticated lands in `RESTRICTED_MODE` (an access level), not a Guest *session* with an ID, a notice, or Guest events. |
| C. Task password never elevates | **Not separable today.** `verify_pin` and `grant_owner_access` are the only password paths and both mean owner. There is no task-credential API, so the risk is future-facing: a task password feature added carelessly could reuse `verify_pin`. Needs an explicit separate interface plus tests. |
| D. Security ON/OFF | **Missing.** Only Full Access (default on), Personal Mode (`JARVIS_PERSONAL_MODE`) and Privacy Lock exist. `JARVIS_PERSONAL_MODE` is an **environment variable**, so anything that can set the process environment relaxes checks; it is not owner-authenticated. |
| E. Guest history, 7-day expiry | **Missing** locally and in Supabase (no guest tables, no retention job). |
| Server-side enforcement of expiry | **Missing.** No `pg_cron` or scheduled Edge Function exists in the migrations. |
| Authorization engine | The tier table plus `guard()` acts as the policy engine. There is no role/resource/action model and no default-deny for *unknown* tool names beyond what `tier_for` returns. |
| Biometric protection | Profiles are encrypted at rest (DPAPI / AES-GCM). The AES-GCM key lives in a key file on non-Windows; on Windows DPAPI binds to the OS account. Embeddings are local only (good: no sync). |

## 4. Vulnerabilities and bypass possibilities (from inspected code)

1. **Full Access default-on weakens every tier.** With it on, `guard()` returns `_run_and_audit(..., rate_limit=False)` before the confirmation gate. Security ON/OFF must define exactly which baseline checks survive; today the baseline is implicit.
2. **`JARVIS_PERSONAL_MODE` is unauthenticated.** `_personal_mode_relaxes()` is consulted at the top of `tier_for()` and lowers a tier to SENSITIVE for an allowlist of local actions. Any process that can set the environment can enable it.
3. **Role label is not identity.** `get_current_speaker_role()` returns `"owner"` when `_manual_user_turn` is set or Voice ID is not required. Trusted typed input counts as owner. That is intended for local typing, but it means there is no notion of *which* owner.
4. **Guard coverage is by convention.** `live_tools.py` calls `guard()` at each branch; a new execution path that forgets to call it is unprotected. There is no test that enumerates every registered action and asserts it passes through `tier_for`. (A completeness test is part of Phase 1.)
5. **`shell=True` call sites** exist in `actions/computer_settings.py` (two Linux brightness fallbacks). The strings are fixed constants with no user input, so no injection path was found, but they are the only `shell=True` hits and should be removed.
6. **LAN dashboard** binds `0.0.0.0` when LAN is enabled; protection then depends on token handling and TLS (`use_ssl`). Token handling was read at the surface only.
7. **No QWebChannel in this repository.** The prompt assumes one; `grep QWebChannel` finds nothing and no `registerObject` call exists. The UI uses PyQt slots directly. The "do not expose Python objects through QWebChannel" requirement is therefore satisfied vacuously; Phase 5 must not introduce one carelessly.

## 5. Not inspected in this pass (unknown, not safe)

Plugin loading and sandboxing (`jarvis/plugins`), the automation engine's own authorization, `ActionDispatcher.can_dispatch` internals, every individual action module's input validation, `dashboard/server.py` request handlers and WebSocket auth, `hub/files.py`, log redaction (whether secrets can reach logs), `scripts/setup_owner_auth.py`, and the Edge Function code. Each needs reading before its Security V2 claim is made.

## 6. Reuse, change, new

- **Reuse:** `AuthManager` (extend with an owner registry), `security.guard`/`tier_for` (becomes the enforcement point), HMAC ledger (keep for local audit), `voice_id` encryption helpers, `host_device_identity` signing, Edge Function + service-role pattern for all cloud tables.
- **Change:** make Personal Mode and Full Access owner-authenticated settings; replace implicit "owner" for typed input with a session object carrying an Owner ID.
- **New (small, no new framework):** `core/identity.py` (owner registry + session objects), `core/guest_audit.py` (allowlisted events, 7-day purge locally), `core/security_settings.py`, task-credential interface separate from `verify_pin`, Supabase migration + scheduled purge, completeness test for the guard.

## 7. Dependency notes

- **pycasbin:** not installed; the current tier table already provides default-deny. Adopt only if a role/resource matrix proves too large for the table (decide in Phase 1 with the real action list; do not add it speculatively).
- **Voice models:** the existing embedding model is already integrated. Resemblyzer vs SpeechBrain was **not benchmarked** here (no audio, no Windows). The false-accept/false-reject procedure in Phase 2 can only be run by the owner on real recordings.
- **argon2-cffi:** already a dependency; reuse for any new owner PIN.

## 8. Regression risks

Changing `guard()` ordering can break Gemini Live tool flow; changing `get_current_speaker_role()` can lock the owner out of typed commands; Full Access default change alters daily behaviour. Each needs the existing `test_security_*` and `test_owner_identity_security.py` suites green plus new tests.

## 9. Limits of this audit

No live Supabase, Windows, microphone or Gemini Live access. Findings come from reading code and running the unit suite, not from penetration testing.
