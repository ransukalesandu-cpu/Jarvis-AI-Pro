# JARVIS Owner Authentication and Privacy Lock

## First-time setup

1. Open PowerShell in the repository folder.
2. Run:

   \`\`\`powershell
   python scripts/setup_owner_auth.py
   \`\`\`

3. Create and confirm a PIN/password locally. Do not put it in a command-line argument, config file, issue, or log.
4. Optional Voice ID enrollment: install the local SpeechBrain/Torch and secure platform key-store dependencies required by \`JarvisAI/core/voice_id.py\`, connect a working microphone, then run:

   \`\`\`powershell
   python scripts/enroll_master.py
   \`\`\`

The profile is written via JARVIS's existing encrypted Voice ID store. If model/key-store dependencies or microphone capture are unavailable, enrollment fails; no synthetic sample or plaintext embedding is created.

## Authentication behavior

- A recognized enrolled owner voice can grant owner access for the current JARVIS process.
- An uncertain/unrecognized speaker remains restricted. Basic public queries are allowed; private files, memory, system control, and unknown tools require owner access.
- When privileged access is requested, JARVIS asks the owner to type the PIN/password into the local command box or paired dashboard. It is intercepted locally and is not sent to Gemini or added to conversation logs.
- A successful PIN/password grants access for the current process even if Voice ID remains uncertain.
- Full access is never restored from persistent state after a JARVIS restart.

## Privacy Lock

Three consecutive incorrect owner PIN/password attempts activate Privacy Lock. JARVIS persists the lockout, attempts to lock the Windows workstation, stops forwarding microphone frames to Gemini, suppresses assistant/private output, blocks private dashboard endpoints/history, and sends a generic alert to connected paired dashboard clients.

The default cooldown is 1 minute. Set the environment variable before starting JARVIS to use any duration from 1–5 minutes:

\`\`\`powershell
$env:JARVIS_PRIVACY_LOCK_MINUTES = "3"
python main.py
\`\`\`

Values outside \`1\` through \`5\` fall back to 1 minute. When the timer expires, JARVIS remains silent and requires owner PIN re-authentication. The Windows workstation is not automatically unlocked; unlock Windows through its normal sign-in process.

## Dashboard privacy

The tablet dashboard still requires its paired bearer token. Before owner verification, it receives only generic status/auth events, not private log/transcript history; upload/list/download of private files requires owner access. During Privacy Lock, only generic lock/auth status messages are sent to connected clients. In-app notifications require the paired dashboard to be connected.

## Limitations

Voice similarity can be fooled by high-quality replays or voice clones. The acoustic check is only a heuristic, not hardware-backed liveness detection. Keep Windows sign-in protection enabled and do not expose JARVIS control endpoints to the public internet.