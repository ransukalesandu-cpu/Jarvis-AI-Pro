# Security Policy

## Supported Versions

Security updates are prioritized for the latest stable version of Jarvis AI. Older versions may not receive security fixes.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately to the repository maintainer.

**Please do not publish exploitable vulnerability details in public issues before a fix is available.**

When reporting an issue, include:
- A description of the vulnerability.
- Steps to reproduce it safely.
- The potential impact.
- Relevant logs or screenshots, with secrets and personal information removed.

Use GitHub's **Private vulnerability reporting** feature if it is enabled for this repository. Otherwise, contact the maintainer through an officially listed contact channel.

## API Keys and Secrets

- Never commit Gemini API keys, access tokens, passwords, private keys, or `.env` files.
- Store credentials in environment variables or an appropriate secrets manager.
- Keep local configuration files out of version control.
- If a credential is exposed, revoke or rotate it immediately.
- Never share credentials in logs, screenshots, bug reports, or public discussions.

## Local Computer Access and Automation

Jarvis AI may interact with local applications, files, devices, cameras, microphones, or system commands, depending on the enabled features.

- Grant only the permissions required for the intended functionality.
- Review commands and file operations before granting elevated privileges.
- Do not execute untrusted commands or AI-generated scripts without appropriate validation.
- Require user confirmation for sensitive or destructive operations.
- Do not expose remote-control interfaces directly to the public internet without appropriate authentication and security controls.

## Third-Party Services

Jarvis AI may use external AI providers and other third-party services. Users should review the relevant providers' privacy policies, security practices, and data-handling terms.

Do not send passwords, API secrets, or unnecessary sensitive personal information to AI models.

## Responsible Disclosure

Please allow the maintainer reasonable time to investigate and address a reported vulnerability before publicly disclosing technical details.

Thank you for helping improve Jarvis AI security.

## 🔐 Autonomous Biometric Authority & Authentication State Machine

JARVIS uses a 4-state authentication state machine in `JarvisAI/security/auth_manager.py` backed by local Argon2id PIN vault hashing and DPAPI / native OS credential encryption:

1. **`RESTRICTED_MODE` (Stranger Mode):** Default unverified state. Access is sandboxed to Tier-1 basic tasks (weather, time, web search, public telemetry reads).
2. **`FULL_ACCESS_MODE` (Verified Owner):** Session-only verified state granted via local PIN entry or an enrolled owner match plus explicit anti-spoof verification of live speech. Speaker similarity, role labels, and disabled Voice ID never authorize access by themselves. Dangerous actions still require confirmation.
3. **`CHALLENGE_MODE`:** Prompted when voice identification is unverified or degraded, requiring local PIN re-authentication.
4. **`PRIVACY_LOCK`:** Activated after 3 consecutive failed PIN attempts or explicit trigger.

### Privacy Lock & Hardware Timer Clamping

When `PRIVACY_LOCK` triggers:
- Attempts to lock the Windows desktop via `ctypes.windll.user32.LockWorkStation()`, verifying non-zero return code and logging `ctypes.GetLastError()` on failure.
- Mutes the audio graph cleanly via defensive `teardown_audio_stream`.
- Suppresses pending assistant output and wipes sensitive memory buffers.
- Enforces a monotonic hardware timer clamp `max(60, min(duration, 300))` ensuring the lock duration stays strictly bounded between 60 seconds (1 minute) and 300 seconds (5 minutes).
- Broadcasts emergency alerts via paired dashboard devices and optional Twilio SMS.

### Voice authorization and PIN fallback

Voice-based owner access and spoken confirmations require `SpeakerAuthenticator` to verify both the encrypted owner profile and a separately validated anti-spoof detector returning literal `True`. The acoustic quality check is not liveness proof. No anti-spoof detector is installed/configured by default: missing or failing verification denies voice authorization and falls back to local PIN/password entry or the manual HUD confirmation path. PIN-authenticated sessions remain usable when voice verification is unavailable. Privacy Lock, including the post-cooldown PIN reauthentication requirement, remains enforced.
