# JARVIS Mobile — Android Tablet Voice Client

This is a native Java/Gradle companion for the JARVIS Python desktop assistant. The tablet uses its own microphone, speaker, screen, and GPU/CPU for the local HUD animation while the desktop keeps running the JARVIS/Gemini Live session.

## Features

- Native Android microphone capture at **16 kHz, mono, signed PCM16**.
- Live audio transport over the existing authenticated `/ws/phone-audio` WebSocket.
- JARVIS reply audio played on the tablet at **24 kHz, mono, signed PCM16**.
- Visible microphone foreground-service notification and automatic reconnects.
- AES-encrypted local storage for the persistent device token using Android Keystore-backed EncryptedSharedPreferences.
- A locally rendered animated orb; no remote image or animation assets are required.
- Keeps the display on while the app screen is in the foreground.
- Microphone audio is streamed live and is not written to local audio files.

## Build

Open the `android-client` folder in Android Studio with JDK 17 installed, then run **Build → Build Bundle(s) / APK(s) → Build APK(s)**. The debug APK is created at:

`android-client/app/build/outputs/apk/debug/app-debug.apk`

The GitHub Actions workflow also builds the debug APK and uploads it as an artifact.

## Pair and use

1. Start JARVIS on the desktop and open **REMOTE CONTROL** to generate a fresh one-time pairing code.
2. Keep remote access private. Configure the desktop's `JARVIS_REMOTE_URL` with its root HTTPS URL and use Tailscale Serve with the desktop and tablet on the same tailnet. Do **not** expose dashboard port 8000 through a public tunnel.
3. Install and open JARVIS Mobile on the tablet.
4. Enter the root HTTPS URL (no path) and the six-character code shown by desktop JARVIS, then tap **PAIR TABLET**.
5. Tap **START VOICE**, approve microphone permission, and keep the notification visible while voice is active. Tap **STOP VOICE** when done.

The one-time code is rate-limited and consumed after successful pairing. Only the device token is retained on the tablet; it is encrypted by Android Keystore-backed preferences. Server-side paired-device tokens are held in memory by the current desktop dashboard implementation, so you may need to pair again after restarting the desktop JARVIS process or revoking devices.

## Current scope

This first native client implements manual voice start/stop and live duplex audio. It does not yet implement QR scanning, BLE proximity-based automatic handoff, or the full browser dashboard UI. Those can be added after the basic tablet microphone/speaker path has been tested on the target hardware.

## Security notes

- Use a private HTTPS URL from Tailscale Serve.
- Never publish pairing codes, device tokens, or the private dashboard URL.
- Do not point a public reverse proxy/tunnel at the dashboard.
- Stop voice when you are not using it; Android displays an ongoing notification while the microphone service is active.
