# Windows JARVIS Smoke-Test Checklist

**Purpose:** Manual validation on the actual Windows PC after installing dependencies and launching JARVIS. These checks are not replaced by Linux CI.

## Test record

- Date/time:
- Windows version:
- JARVIS commit / branch:
- Python version or packaged build:
- Microphone device:
- Speaker/headphone device:
- Network:
- Gemini Live model/config:
- Tester:

Mark each check PASS, FAIL, or BLOCKED. Record exact errors and relevant log lines. Do not paste API keys, PINs, tokens, or private messages into the report.

## 1. Pre-flight

- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Confirm .env, API-key files, logs, and private credentials are not shared in screenshots or logs.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Start JARVIS using the documented Windows launch method; no import, Qt plugin, or missing-DLL error appears.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Confirm Windows microphone and speaker permissions are enabled for the Python/JARVIS process.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Confirm the selected input/output devices are intended devices and are not exclusively occupied by another app.

## 2. Microphone input

- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Speak a short phrase at normal volume; input level responds and speech is recognized.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Speak quietly, then normally; input does not remain stuck at zero or permanently clipped.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Pause for several seconds and speak again; capture resumes without restarting the app.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Unplug/disable and restore the selected microphone only if safe; no crash occurs and recovery/error reporting is understandable.

## 3. Speaker output and PCM recovery

- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Ask for a short response; speech is audible, intelligible, and not excessively choppy.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Ask for three responses consecutively; each starts and finishes with no stale audio from a previous turn.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Interrupt a response by speaking or using the configured stop control; playback stops promptly and the new request is heard.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — After interruption, ask a new question; no tail of the cancelled response plays.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Check logs for repeated output-write exceptions, growing playback delay, or repeated PCM-buffer warnings.

## 4. Gemini Live connection and reconnect

- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Start a Live session with a valid configured key and network; connection succeeds.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Complete multiple back-and-forth voice turns without the session hanging.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Briefly disconnect/reconnect the network only when safe; confirm JARVIS recovers or displays a clear recoverable error.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — If a model/config switch is supported, trigger it through the intended UI and confirm the session rebuilds as expected.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Confirm authentication, quota, or invalid-key errors are reported clearly and do not create a tight reconnect loop.

## 5. UI responsiveness

- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Main window opens, paints correctly, and can be moved/resized without freezing.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — State indicators and logs update while listening, thinking, speaking, and after an error.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Stop/mute and other primary controls respond while audio is active.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Repeatedly start/stop listening or run several turns; UI remains responsive and no duplicate audio worker is evident.

## 6. Webcam / vision

- [ ] PASS / [ ] FAIL / [ ] BLOCKED — With explicit user intent, open the selected camera and verify a frame can be captured.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Ask a supported visual question; the image is handled and the answer corresponds to the scene.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Close the camera or finish the vision action; camera indicator turns off and the device is released.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — If no camera is present or permission is denied, JARVIS reports the problem without crashing.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Confirm camera capture is not triggered unexpectedly by unrelated speech or untrusted external content.

## 7. Desktop actions and safety gates

Use harmless, reversible actions first. Never use important files or accounts for a test.

- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Open a harmless app or request read-only system status; result is correct.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Perform a reversible UI action and verify the result.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Request a file write in a disposable test folder; verify the target and result before allowing it.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Request delete, code execution, shutdown, or send-message actions; JARVIS asks for required explicit confirmation and does not execute before approval.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Cancel the confirmation; verify the side effect does not occur.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Verify content from a webpage/document cannot independently approve or initiate a sensitive action.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Confirm denied/cancelled actions are logged without exposing credentials or private message content.

## 8. Recovery and stability

- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Leave JARVIS idle for at least five minutes, then make another request.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Run at least ten short speech turns, including two interruptions; no persistent stuck-speaking/listening state occurs.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Close JARVIS using its normal exit path; audio devices and camera are released.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Relaunch JARVIS and confirm it starts without stale session state.

## 9. Cherry Studio parity features (P1–P13)

- [ ] PASS / [ ] FAIL / [ ] BLOCKED — "Add <a PDF> to my work knowledge", then ask a question about it; the answer cites [1].
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Telegram: set `telegram_bot_token`, say "pair Telegram", send `/pair <code>`, send a command from the phone, get the reply; answer a confirmation with YES; `/stop` works.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Select text in Notepad/Chrome, press Ctrl+Shift+J; JARVIS describes it; "fix the grammar and replace it" pastes back and the old clipboard is restored. Selecting a password box copies nothing.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — "Translate <a .docx> to Sinhala" creates `<name> (Sinhala).docx` next to it with formatting kept.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Notes: create, append, search; the files appear in the notes folder.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — "Ask Claude, Gemini and GPT …" returns a comparison; "Claude won" is recorded.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — "Back up JARVIS now" with and without a backup password; "restore the latest backup" asks for confirmation first.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — "Show my AI provider status", "set a 1 dollar daily budget"; usage shows today's calls.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — "Switch to the coding assistant profile" and back; a profile with a tool allow-list blocks other tools.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — "Open the Figma mini app" opens its own Edge/Chrome app window; "show my recent files" lists translations/backups.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — "Search everything for <topic>" returns conversation, note and knowledge hits.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Optional: `pip install -r requirements-stt.txt`, then "dictate" types into the focused app.
- [ ] PASS / [ ] FAIL / [ ] BLOCKED — Web UI (`JARVIS_UI=web`): Ctrl+K → Features Hub; every tab loads; buttons submit commands; in Guest Mode the tabs are hidden.

## Failure report

- Check number / step:
- Expected:
- Actual:
- Reproduction steps:
- Relevant log excerpt (redact secrets):
- Repeatable?:
- Result after restart:

## Offline voice loop

- [ ] With `OFFLINE=1` (or Wi-Fi off), JARVIS logs "Offline voice active" within ~10 s.
- [ ] A spoken request is transcribed, answered and spoken back; JARVIS does not react to its own voice.
- [ ] Reconnecting the network brings Gemini Live back and the log shows "Offline voice stopped".

## Performance baseline (production-architecture upgrade)

These numbers are the "before" for the engine split (docs/plans/PROD_ARCH_UPGRADE_PLAN.md §4). Take them
once now and again after each milestone that touches the engine, audio or packaging. They contain timings and
memory sizes only, so they are safe to paste.

- [ ] Import and eval numbers: `python -m jarvis.tools.baseline all --save` from the repository folder. Paste the
      printed JSON (it is also saved under `%LOCALAPPDATA%\jarvis\baselines\`).
- [ ] Idle RAM: start JARVIS normally, wait until it is listening, find the PID (Task Manager → Details →
      `python.exe`), then run `python jarvis/tools/profile_ram.py --pid <PID> --duration 120 --label idle`.
      Paste the summary line.
- [ ] Live RAM: start a Gemini Live conversation and, while talking, run
      `python jarvis/tools/profile_ram.py --pid <PID> --duration 60 --label voice --append`. Paste the summary line.
- [ ] Voice latency: close JARVIS, start it again with the trace on (PowerShell: `$env:JARVIS_LATENCY_TRACE=1`,
      then the usual launch command from the same window). In a quiet room, say ten short phrases ("what time is
      it", "hello"), waiting for each answer. Paste the last `[LatencyTrace] turn 10: ...` line, or run
      `python -m jarvis.tools.baseline latency` afterwards and paste its JSON.

## Sign-off

- [ ] All required checks passed on the target Windows machine.
- [ ] Failures are recorded and assigned before considering the build ready.
