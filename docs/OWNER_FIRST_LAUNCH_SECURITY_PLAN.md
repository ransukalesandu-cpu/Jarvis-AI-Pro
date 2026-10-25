# JARVIS Owner Privacy Setup and Sensitive-Action Authentication

## Intended behavior

- After API-key setup on the first run, show a local **Privacy & Owner Security** dialog.
- Require an owner-created PIN/password and confirmation. Use the existing `AuthManager` and Argon2 hash; never store or send the raw credential.
- Voice enrollment is optional and uses the existing encrypted Voice ID enrollment flow.
- Face authorization remains disabled until a reliable local verifier, secure enrollment, liveness checks, and tests are available.
- On later launches, start normally without asking for the PIN at startup.
- Harmless conversation/basic commands remain available. Before a sensitive action executes, verify the owner if the current session has not already authenticated them.
- Successful PIN verification authorizes the current app session. Restart/lockout clears the authorization; a command that is cancelled or not verified must not execute.
- Keep the authorization gate central so tools and plugins cannot bypass it. Preserve the separate confirmation prompt for dangerous operations.

## Code changed on this branch

- `JarvisAI/ui/__init__.py`: adds the first-run Privacy & Owner Security dialog after API setup and resumes incomplete enrollment on a later launch. It asks for and confirms a local PIN/password, offers optional Voice ID enrollment, and explicitly keeps Face authorization unavailable.
- `JarvisAI/core/security.py`: runs adaptive owner verification before the privileged-action dispatcher rejects a sensitive action. Speaker similarity by itself no longer grants owner access.
- `JarvisAI/security/adaptive_auth.py`: requires a verified-live voice result before voice can unlock sensitive actions; without a validated anti-spoof verifier, the flow falls back to the local PIN/password. Face verification remains disabled by `security/face_auth.py`.
- `JarvisAI/security/auth_manager.py`: existing Argon2 PIN hashing, Windows DPAPI vault protection, three-failure Privacy Lock, and session-only full access are reused.

## Current biometric limitations

The repository has speaker matching but no validated anti-spoof detector configured. Therefore, optional Voice ID enrollment can be performed, but **it must not automatically unlock sensitive actions yet**; the safe fallback is the PIN/password. Face authorization is explicitly disabled. These controls must not be described as complete biometric unlock until their verification backends are implemented and tested.

## Validation still required

- Run syntax checks and the repository's available tests/CI on a supported environment.
- Test first-run PIN enrollment, ordinary startup without PIN prompts, sensitive-action PIN fallback, cancellation/wrong PIN denial, and session-only access.
- Test that all tool/plugin/background dispatch paths use the same gate.
- Implement and validate anti-spoof voice verification before enabling automatic voice unlock.
- Implement and validate face verification before enabling face unlock.
- Keep this pull request unmerged until the above checks are reviewed.