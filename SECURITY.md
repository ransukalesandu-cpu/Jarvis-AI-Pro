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

## Privacy Lock alert integration

Privacy Lock uses the existing `JarvisAI/security/auth_manager.py` state machine, persistent lockout handling, and Argon2/DPAPI-backed PIN vault. The alert integration does not replace or duplicate that authentication system.

When the state machine activates a lock, the application suppresses pending voice output, clears queued microphone audio, publishes a non-sensitive dashboard event, and revokes active companion sessions. Remote command, wake, and phone-audio entry points reject activity while the lock is active.

Twilio SMS is an optional best-effort alert. It requires valid configured credentials and an explicit `alert_recipient_number`; it is not sent to the Twilio sender number by default. SMS delivery is performed off the real-time audio loop. Missing configuration or provider failure does not disable local Privacy Lock protections.
