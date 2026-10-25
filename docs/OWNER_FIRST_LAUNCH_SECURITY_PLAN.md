# JARVIS Owner First-Launch Security Plan

## Goal

Require an owner-created PIN/password before JARVIS can start its assistant session. Offer optional owner voice enrollment and optional face verification. Preserve existing security controls and avoid duplicating the current authentication implementation.

## Existing code to reuse

- `JarvisAI/security/auth_manager.py`: `AuthManager`, Argon2 password hashing, restricted/challenge/full-access states, failed-attempt lockout and session-only full access.
- `JarvisAI/core/security.py`: public accessors for the existing authentication manager.
- `JarvisAI/core/voice_id.py`: encrypted local Voice ID enrollment/profile support.
- `JarvisAI/security/voice_auth.py`: speaker verification adapter. It intentionally fails closed for owner verification unless a separately validated anti-spoof verifier is supplied.
- `JarvisAI/ui/__init__.py` and `JarvisAI/main.py`: inspect the real startup/UI lifecycle before wiring a gate.

Do not create a parallel PIN store or store plaintext PINs, passwords, voice embeddings, or face templates.

## Required first-run flow

1. Before opening the normal assistant session, detect whether an owner PIN/password has been enrolled.
2. If not enrolled, show a local first-run Owner Setup dialog. Require password/PIN entry and confirmation. Reject empty/weak input and persist only using the existing AuthManager/Argon2 flow.
3. After owner credential setup, show an optional Voice ID step: **Set up voice verification** or **Skip for now**. Enrollment must use the existing encrypted Voice ID flow and explain that a voice match alone is not reliable proof of liveness.
4. Show an optional Face Verification step: **Set up face verification** or **Skip for now**. Do not enable face verification unless a local implementation, secure template storage, reasonable liveness checks, and tests are actually available. Never upload face images/templates to an AI provider.
5. Show a final confirmation screen, then continue to the normal JARVIS UI.

## Subsequent launches

- Start in restricted/challenge state; never restore a prior full-access session.
- Require local PIN/password unlock before enabling private memory, tools, computer control, or other owner-only actions.
- Voice or face can be offered as an optional convenience/second factor only if the implementation is available and passes its security checks. Always retain PIN/password fallback.
- Voice matching without anti-spoof verification must not unlock owner access. A recording or cloned voice may imitate a speaker.
- If face verification is unavailable, disabled, or fails, fall back to PIN/password; do not lock the owner out permanently.
- Apply the existing failed-attempt/Privacy Lock policy. Avoid silently launching a headless or background assistant with owner access when authentication is missing.

## UI and lifecycle integration requirements

- Inspect both normal GUI launch and headless/background launch paths.
- Put the authentication gate before Gemini Live sessions, microphone streaming, camera streaming, proactive actions, plugins, and computer-control dispatch start.
- Keep the UI responsive; never block the Qt main thread with model loading or biometric inference.
- Do not log or send credential text/audio/images to Gemini, logs, telemetry, or crash reports.
- Provide a visible settings screen to re-enroll voice, configure optional face verification, change the PIN/password after current-owner verification, and disable biometrics.
- Keep the current JARVIS experience and all unrelated features intact.

## Tests and acceptance criteria

- First run cannot enter the assistant before PIN/password enrollment succeeds.
- Empty/mismatched credentials are rejected; the password hash is stored through AuthManager, never plaintext.
- Relaunch requires authentication; full access is not persisted.
- Three incorrect PIN attempts follow the existing lockout behavior.
- Skipping voice/face enrollment works without breaking the app.
- Voice verification fails closed when its anti-spoof dependency is missing or errors.
- Face verification cannot unlock access when disabled/unavailable or when liveness checks fail.
- GUI and headless/background startup both fail closed.
- Existing tests and new authentication tests pass on the project's supported platforms.
- Do not merge the PR automatically; report exact files changed, test commands, and actual results.

## Scope note

This PR is a plan for safe integration, not a claim that startup authentication or face verification is already wired. Face verification is optional and should only be enabled after the implementation is validated.
