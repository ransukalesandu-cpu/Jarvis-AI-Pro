# JARVIS Owner Authentication and Privacy Lock

## First-time setup

The desktop UI offers local owner PIN enrollment after API setup, and skips enrollment once a PIN exists. The command-line setup remains available:

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
- When privileged access is requested, JARVIS asks the owner to type the PIN/password into the local command box or paired dashboard. It is intercepted locally and is not sent to Gemini or added to conversation logs.
- A successful PIN/password grants access for the current process even if Voice ID remains uncertain, but it does not by itself enable Owner Autopilot.
- Full access is never restored from persistent state after a JARVIS restart.
- Owner Autopilot suppresses JARVIS's own action-confirmation banners only after both PIN and live enrolled Voice ID/anti-spoof factors are verified in the current process, and only when the current command's live speech is verified as the owner. Untrusted external-content provenance checks, action rate limits and audit logging remain active. If any check fails, the ordinary confirmation/authorization path remains in force.
- Owner Autopilot does not hide or bypass native Windows/macOS security prompts, UAC, browser permission dialogs, or permissions required by third-party applications.

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
