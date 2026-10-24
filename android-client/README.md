# JARVIS Mobile — Android Tablet Remote HUD

This is a native Java/Gradle Android companion for the JARVIS Python desktop assistant. The tablet displays a local animated HUD, relays status/transcript events, and can send typed commands. **All microphone capture and speaker playback stay on the desktop PC.** This is the intended setup when a better external microphone and speaker are connected to the PC.

## Features

- Native Android remote-control HUD with animated orb rendered locally on the tablet.
- Secure, one-time pairing code exchanged for a random persistent device token.
- Token encrypted at rest using Android Keystore-backed EncryptedSharedPreferences.
- Authenticated WebSocket event feed with automatic reconnects.
- Send typed commands to the existing JARVIS desktop session.
- Keeps the screen on while the app is in the foreground.
- Requires no tablet microphone, Bluetooth, or audio permissions.
- Does not capture, transmit, play, or store raw audio.

## Audio routing

- **PC microphone:** JARVIS listens through the input device selected in the desktop JARVIS settings.
- **PC external speaker:** JARVIS plays its spoken responses through the output device selected in desktop settings.
- **Tablet:** HUD, status, conversation transcript, and remote command input only.

The tablet does not use `AudioRecord`, `AudioTrack`, or the tablet's built-in audio devices. If the PC selects the wrong microphone or speaker, correct it in JARVIS's desktop audio-device settings; the tablet does not change the PC's selected devices.

## Build

Open the `android-client` folder in Android Studio with JDK 17 installed, then run **Build → Build Bundle(s) / APK(s) → Build APK(s)**. The debug APK is created at:

`android-client/app/build/outputs/apk/debug/app-debug.apk`

The GitHub Actions workflow builds the debug APK and uploads it as an artifact once the workflow succeeds.

## Pair and use

1. Start JARVIS on the PC and open **REMOTE CONTROL** to create a fresh one-time pairing code.
2. Keep remote access private. Configure the PC's `JARVIS_REMOTE_URL` with its root HTTPS URL and use Tailscale Serve with the PC and tablet on the same tailnet. Do **not** expose dashboard port 8000 through a public tunnel.
3. Install and open JARVIS Mobile on the tablet.
4. Enter the root HTTPS URL (no path) and the six-character code shown in desktop JARVIS, then tap **PAIR TABLET**.
5. Tap **CONNECT REMOTE HUD**. The status feed should show desktop events.
6. Type a command into the command field and tap **SEND**. Voice interaction itself remains on the PC: speak into its external microphone and listen to its external speaker.
7. Tap **DISCONNECT REMOTE HUD** when finished.

The one-time pairing code is rate-limited and consumed after successful pairing. The long-lived device token is encrypted in Android app storage. Server-side device tokens are held in memory by the current desktop dashboard implementation, so the tablet may need to pair again after restarting desktop JARVIS or revoking devices.

## Current scope

This client uses manual URL/code pairing, text commands, and a live status feed. QR scanning, the full browser-dashboard file-transfer controls, and BLE proximity-based automatic handoff are not implemented in this native app yet.

## Security notes

- Use a private HTTPS URL from Tailscale Serve.
- Never publish pairing codes, device tokens, or the private dashboard URL.
- Do not expose dashboard port 8000 through a public tunnel.
