# Android Phone Voice Control (ADB)

JARVIS can send a limited set of voice-command actions to an Android phone through ADB. No JARVIS companion app is required for these actions, but the phone must first be paired/authorized by its owner.

## Android 11+ / Android 16 wireless setup

1. Install Android Platform Tools on the Windows computer and make sure `adb.exe` is on PATH.
2. On the phone, enable Developer options and USB debugging/Wireless debugging.
3. Use **Pair device with pairing code** once, then run `adb pair PHONE_IP:PAIRING_PORT` on the computer.
4. On the Wireless debugging main screen, use the separate connection IP/port with `adb connect PHONE_IP:DEBUG_PORT`.
5. Verify with `adb devices`; the device must show status `device`, not `unauthorized` or `offline`.
6. Keep the computer and phone on a network that allows them to reach each other. Mobile data by itself does not make the laptop and phone reachable to each other; a working shared Wi-Fi/hotspot or USB connection is needed.

Do not share pairing codes or debugging authorization prompts. Disconnecting from a trusted network or turning Wireless debugging off can require reconnecting.

## Supported voice actions

- `phone_control(action="status")`: model, Android version, battery level and charging state
- `phone_control(action="open_app", app_name="YouTube")`: launch a supported installed app
- `home`, `back`, `volume_up`, `volume_down`, `mute_volume`
- `wake_screen` (does not bypass the lock screen)
- `open_dialer` and `open_messages` (opens the app only; does not place calls or send messages)

Supported app aliases: WhatsApp, YouTube, Chrome, Settings, Spotify, Maps, Gmail, Telegram, Messages, Phone.

## Safety and limitations

- The tool only exposes a fixed allow-list; it does not accept arbitrary shell commands.
- If multiple authorized devices are connected, JARVIS refuses to guess which one to control. Supply the exact serial from `adb devices` as `target_device`, or disconnect the extra device.
- Android permissions and OS restrictions still apply. This is not root access and does not bypass the lock screen.
- Calls, SMS sending, flashlight toggling, notification reading and unrestricted UI tapping are intentionally not included in this first version. They need device-specific verification and appropriate confirmation/permission handling.
- Automated tests mock ADB; actual Moto G75 behavior must still be smoke-tested after download.
