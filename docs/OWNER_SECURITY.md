# JARVIS Owner Authentication and Privacy Lock

## First-time setup

The desktop UI offers local owner Master Password enrollment after API setup, and skips enrollment once a password exists. The password is hashed with Argon2 and protected by the local vault (Windows DPAPI on Windows). The current Windows user is trusted for ordinary local startup after enrollment, so JARVIS does not show a routine login prompt. The command-line setup remains available:

1. Open PowerShell in the repository folder.
2. Run:

   ```powershell
   python scripts/setup_owner_auth.py
   ```

3. Create and confirm a PIN/password locally. Do not put it in a command-line argument, config file, issue, or log.
4. Optional Voice ID enrollment: install the local SpeechBrain/Torch and secure platform key-store dependencies required by `JarvisAI/core/voice_id.py`, connect a working microphone, then run:

   ```powershell
   python scripts/enroll_master.py
   ```

The profile is written via JARVIS's existing encrypted Voice ID store. If model/key-store dependencies or microphone capture are unavailable, enrollment fails; no synthetic sample or plaintext embedding is created.

## Authentication behavior

- An enrolled owner match grants voice access only when a separately validated anti-spoof detector confirms live speech. A role label or speaker-similarity score alone never grants access. Missing, failing, or unavailable anti-spoof verification falls back to the local PIN/password.
- Spoken confirmations also require verified live owner speech. A PIN session does not bypass the liveness check for spoken approval; manual HUD confirmation remains available.
- An uncertain/unrecognized speaker remains restricted. Basic public queries are allowed; private files, memory, system control, and unknown tools require owner access.
- After first-time enrollment, normal launches restore local owner access for the same OS user without asking for the password again. This trusts the protected local vault; it is not a cloud identity or a defense against someone who already controls the same Windows account.
- Host-only cloud capabilities still require the live Voice ID factor in the current process; setup trust alone does not satisfy both host factors.
- Privacy Lock and mandatory post-lock PIN re-authentication override startup trust. A successful owner PIN/password can recover from that lock after the cooldown.
- Dangerous operations still use their separate confirmation gate and audit trail.

## Privacy Lock

Three consecutive incorrect owner PIN/password attempts activate Privacy Lock. JARVIS persists the lockout, attempts to lock the Windows workstation, stops forwarding microphone frames to Gemini, suppresses assistant/private output, blocks private dashboard endpoints/history, and sends a generic alert to connected paired dashboard clients.

The default cooldown is 1 minute. Set the environment variable before starting JARVIS to use any duration from 1–5 minutes:

```powershell
$env:JARVIS_PRIVACY_LOCK_MINUTES = "3"
python main.py
```

Values outside `1` through `5` fall back to 1 minute. When the timer expires, JARVIS remains silent and requires owner PIN re-authentication. The Windows workstation is not automatically unlocked; unlock Windows through its normal sign-in process.

## Dashboard privacy

The tablet dashboard still requires its paired bearer token. Before owner verification, it receives only generic status/auth events, not private log/transcript history; upload/list/download of private files requires owner access. During Privacy Lock, only generic lock/auth status messages are sent to connected clients. In-app notifications require the paired dashboard to be connected.

## Limitations

Voice similarity can be fooled by high-quality replays or voice clones. The acoustic quality check does not prove liveness; no anti-spoof verifier is configured by default, so voice authorization fails closed until a validated verifier is supplied. Keep Windows sign-in protection enabled and do not expose JARVIS control endpoints to the public internet.
