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

## Biometric + PIN + Emergency Privacy Lockout Architecture

Jarvis AI employs a multi-tiered security defense protocol to prevent unauthorized access:

- **Voice Biometric Authorization:** Speaker voice embeddings verify owner identity before sensitive actions or spoken confirmations are authorized.
- **Argon2 / DPAPI Secured PIN Vault:** Core state management uses Argon2/DPAPI protected vaults for PIN credential verification.
- **3-Strike Emergency Privacy Lockout (`JarvisAI/security/lockdown.py`):**
  - **Trigger:** 3 consecutive incorrect PIN/credential attempts trigger an immediate transition to `PRIVACY_LOCK` state.
  - **OS Lockdown:** Calls native Windows `ctypes.windll.user32.LockWorkStation()` to immediately switch the desktop to the Windows lock screen.
  - **Process Silencing:** Instantly terminates active TTS speech playback and suspends microphone streaming (PyAudio/WASAPI).
  - **Data Zeroing (`SecureZeroMemory`):** Zeroes out sensitive conversation memory, revokes active session tokens, and closes handles to private vaults and files.
  - **Clamped Hardware Monotonic Timer:** Enforces countdown using `time.monotonic()` strictly clamped between 60 seconds (1 minute) and 300 seconds (5 minutes) (`effective_duration = max(60, min(configured_duration, 300))`), bypassing system clock manipulation. Upon expiration, resets failed attempts to 0 and restores microphone in `RESTRICTED_MODE`.
  - **Multi-Device Emergency Alerts (`JarvisAI/notifications/alert_service.py`):** Dispatches SMS/voice alerts via Twilio and broadcasts emergency WebSocket payloads (`{"event": "PRIVACY_LOCK", "duration": effective_duration}`) to all connected companion HUDs and mobile devices.

## Third-Party Services

Jarvis AI may use external AI providers and other third-party services. Users should review the relevant providers' privacy policies, security practices, and data-handling terms.

Do not send passwords, API secrets, or unnecessary sensitive personal information to AI models.

## Responsible Disclosure

Please allow the maintainer reasonable time to investigate and address a reported vulnerability before publicly disclosing technical details.

Thank you for helping improve Jarvis AI security.
