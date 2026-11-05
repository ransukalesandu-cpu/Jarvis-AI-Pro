# Security V2 — Implementation status

Legend: **PASS** implemented and covered by automated tests that were actually run (Linux, headless). **PARTIAL** works with stated limits. **BLOCKED** could not be done or verified here. **NOT IMPLEMENTED**.

| Requirement | Status | Evidence / limits |
|---|---|---|
| A. Multiple independent owners | **PASS** (local) | `core/owner_registry.py`, 22 tests: separate PINs, lockout, admin rules, recovery code, revoke. Add/revoke only from `scripts/security_owners.py`, not the UI. |
| A. Per-owner Voice ID | **PARTIAL** | Per-owner voice roles and enrolment tested with fake verifiers. Real accuracy (false accept/reject, Sinhala vs English, model choice) **not measured**; needs the owner's recordings. Voice sign-in is not wired to the live audio path during Guest Mode. Voice fails closed (never "everyone is owner"). |
| B. Guest monitoring, visible and minimal | **PASS** (local) | Notice shown at start; allowlisted fields only; no free-text column; no keylogging, audio, screen or conversation capture (tests inspect schema and stored rows). |
| C. Guest/task password never elevates | **PASS** | Mandatory tests: wrong PIN stays Guest; `verify_task_credential` cannot touch identity; plain typed text never logs in; also while Security is OFF. |
| D. Security ON/OFF, owner-only, baseline kept | **PASS** (scope: Guest monitoring) | OFF needs owner session + step-up; baseline list enforced in both states (tests). Full Access default and `JARVIS_PERSONAL_MODE` for the legacy path are **unchanged**. |
| E. Owner views / deletes latest Guest history | **PASS** (local) | Tool and HUD panel; delete is confirmed and re-read to verify. |
| E. Records expire after 7 days, server side | **NOT DEPLOYED** | Local expiry works and is tested. Server-side purge exists only as SQL (`supabase/migrations/202611050001_…sql`); **never applied to any project, never run against a live database**. No Edge Function/sync client exists, so nothing is uploaded. |
| F. Preserve existing functionality | **PASS** (Linux) | Full suite: see TEST_REPORT. Not exercised on Windows or with real microphone/Gemini Live. |
| Guest default-deny in `guard()` | **PASS** | Identity check runs first; denials are logged. Legacy single-PIN installs behave as before until an owner exists. |
| Dangerous PC tools tiering (found in audit) | **PASS** | `run_command`, files/software/email actions etc. no longer default to SENSITIVE. |
| Security UI | **PARTIAL** | Headless-tested only; no add/revoke/enrol or typed-PIN box in the UI. |
| CI: Semgrep, OSV-Scanner, pinned SHAs | **BLOCKED (not run)** | `.github/workflows/security-scan.yml` written; the action SHAs were read from the upstream tags, but the workflow has never executed. Semgrep is report-only until triaged. The OSV reusable-workflow call follows the project's documented form and is unverified. |
| Windows CI coverage of Security V2 tests | **BLOCKED (not run)** | Added to the `windows-ui-smoke` list; unverified until GitHub runs it. |

## Not inspected / out of scope
Real Windows DPAPI behaviour, the live Gemini audio path, installers beyond the earlier fixes, and any Supabase project state.

## Known risks that remain
- Full Access and `JARVIS_PERSONAL_MODE` relax confirmation for a signed-in legacy owner.
- A flaky test was seen once earlier and not reproduced (see TEST_REPORT).
- Voice ID accuracy is unknown; do not rely on voice alone for dangerous actions.
