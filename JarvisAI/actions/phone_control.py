"""Voice actions for a connected Android phone through an already-authorized ADB link.

This deliberately exposes a small allow-list of fixed commands rather than
allowing the model to execute arbitrary shell commands on the phone. Android
must be paired/authorized by the owner first (USB debugging or Wireless
debugging); this module never enables debugging or pairs a device itself.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any

from services.adb_bridge import find_adb, parse_adb_devices

_APP_PACKAGES = {
    "whatsapp": "com.whatsapp",
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "settings": "com.android.settings",
    "spotify": "com.spotify.music",
    "maps": "com.google.android.apps.maps",
    "gmail": "com.google.android.gm",
    "telegram": "org.telegram.messenger",
    "messages": "com.google.android.apps.messaging",
    "phone": "com.google.android.dialer",
}
_ACTIONS = {
    "status", "open_app", "home", "back", "volume_up", "volume_down",
    "mute_volume", "open_dialer", "open_messages", "wake_screen",
}
_DEVICE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _run(command: list[str], timeout: float = 10.0) -> tuple[bool, str]:
    """Run an argument list without a shell and preserve useful error output."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, shell=False
        )
    except FileNotFoundError:
        return False, "ADB was not found. Install Android Platform Tools and add adb to PATH."
    except subprocess.TimeoutExpired:
        return False, "ADB command timed out. Check that the phone is connected and awake."
    except OSError as exc:
        return False, f"Could not run ADB: {exc}"
    output = (result.stdout or "").strip()
    if result.returncode != 0:
        error = (result.stderr or output or f"ADB exited with code {result.returncode}").strip()
        return False, error[:500]
    return True, output


def _resolve_device(adb: str, requested: str = "") -> tuple[str | None, str]:
    """Require an authorized device; never silently target one of several phones."""
    ok, output = _run([adb, "devices"], timeout=8)
    if not ok:
        return None, output
    devices = parse_adb_devices(output)
    authorized = [d["serial"] for d in devices if d.get("status") == "device"]
    if requested:
        if not _DEVICE_RE.fullmatch(requested):
            return None, "The target device ID has an invalid format."
        if requested not in authorized:
            return None, f"Target device '{requested}' is not connected and authorized."
        return requested, ""
    if not authorized:
        return None, (
            "No authorized Android device found. Pair/connect the phone with ADB first "
            "and accept its debugging authorization prompt."
        )
    if len(authorized) > 1:
        return None, (
            "More than one authorized ADB device is connected. Disconnect the extra "
            "device or specify its exact device ID in target_device."
        )
    return authorized[0], ""


def phone_control(parameters: dict[str, Any] | None = None, player=None) -> str:
    """Execute a limited, allow-listed action on one authorized Android device."""
    params = parameters or {}
    action = str(params.get("action", "")).strip().lower()
    if action not in _ACTIONS:
        return "Unsupported phone action. Allowed actions: " + ", ".join(sorted(_ACTIONS)) + "."

    adb = find_adb()
    if not adb:
        return "ADB was not found. Install Android Platform Tools and add adb to PATH."

    serial, error = _resolve_device(adb, str(params.get("target_device") or "").strip())
    if error:
        return error

    def run_phone(args: list[str], timeout: float = 10.0) -> tuple[bool, str]:
        return _run([adb, "-s", serial, *args], timeout=timeout)

    if action == "status":
        ok_model, model = run_phone(["shell", "getprop", "ro.product.model"])
        ok_android, android = run_phone(["shell", "getprop", "ro.build.version.release"])
        ok_battery, battery = run_phone(["shell", "dumpsys", "battery"])
        if not ok_model or not ok_android or not ok_battery:
            return "Could not read phone status: " + "; ".join(
                x for x in (model if not ok_model else "", android if not ok_android else "",
                            battery if not ok_battery else "") if x
            )
        level = re.search(r"(?m)^\s*level:\s*(\d+)", battery)
        status = re.search(r"(?m)^\s*status:\s*(\d+)", battery)
        charging = status is not None and status.group(1) in {"2", "5"}
        percent = f"{level.group(1)}%" if level else "unknown battery level"
        power = "charging" if charging else "not charging"
        return f"Phone: {model or 'Android device'}; Android {android or 'unknown'}; battery {percent}; {power}."

    if action == "open_app":
        app = str(params.get("app_name") or "").strip().lower()
        package = _APP_PACKAGES.get(app)
        if not package:
            return "Unsupported app. Supported apps: " + ", ".join(sorted(_APP_PACKAGES)) + "."
        ok, output = run_phone([
            "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
        ])
        if not ok:
            return f"Could not open {app}: {output}"
        if "No activities found" in output:
            return f"{app} does not appear to be installed on this phone."
        return f"Sent the open command for {app} to the phone."

    commands = {
        "home": ["shell", "input", "keyevent", "3"],
        "back": ["shell", "input", "keyevent", "4"],
        "volume_up": ["shell", "input", "keyevent", "24"],
        "volume_down": ["shell", "input", "keyevent", "25"],
        "mute_volume": ["shell", "input", "keyevent", "164"],
        "open_dialer": ["shell", "am", "start", "-a", "android.intent.action.DIAL"],
        "open_messages": [
            "shell", "am", "start", "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.APP_MESSAGING",
        ],
        "wake_screen": ["shell", "input", "keyevent", "224"],
    }
    ok, output = run_phone(commands[action])
    if not ok or re.search(r"(?m)^\s*Error:", output):
        return f"Phone action '{action}' failed: {output}"
    messages = {
        "home": "Sent the Home command to the phone.",
        "back": "Sent the Back command to the phone.",
        "volume_up": "Raised phone volume.",
        "volume_down": "Lowered phone volume.",
        "mute_volume": "Sent the phone volume-mute command.",
        "open_dialer": "Opened the phone dialer. No call was placed.",
        "open_messages": "Opened the messaging app. No message was sent.",
        "wake_screen": "Sent the wake-screen command. This does not bypass the lock screen.",
    }
    if player:
        try:
            player.write_log(f"[PHONE] {action} on Android device {serial}")
        except Exception:
            pass
    return messages[action]


TOOL = {
    "name": "phone_control",
    "description": (
        "Control a connected, already-authorized Android phone using a safe allow-list. "
        "Use for phone status/battery, opening supported apps, Home/Back, volume, "
        "waking the display, and opening the dialer or messaging app. Never claims to "
        "send a call or message; opening those apps does not perform the action. "
        "Do not use for arbitrary shell commands."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": sorted(_ACTIONS),
                "description": "The fixed phone action to perform.",
            },
            "app_name": {
                "type": "STRING",
                "description": "Required only for action=open_app; supported app name such as YouTube or WhatsApp.",
            },
            "target_device": {
                "type": "STRING",
                "description": "Optional exact serial shown by 'adb devices'; only needed when multiple authorized devices are connected.",
            },
        },
        "required": ["action"],
    },
    "handler": phone_control,
}
