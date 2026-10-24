# desktop_automation.py
import os
import platform
import re
import shutil
import subprocess
import sys
from typing import Any

try:
    import pyautogui
except Exception:
    pyautogui = None

try:
    if platform.system() == "Windows":
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    else:
        IAudioEndpointVolume = None
except Exception:
    IAudioEndpointVolume = None

_UNSAFE_CMD_RE = re.compile(r"[\;&|`$\r\n]")


def launch_app(name: str) -> str:
    """Launch one installed application without invoking a command shell.

    Windows accepts only a single executable found on PATH or an explicit
    .exe/.com path. Arguments and shell metacharacters are intentionally not
    accepted; callers must use a dedicated, validated action for arguments.
    """
    if not name or not str(name).strip():
        return "Application name is required."

    app_name = str(name).strip()
    if _UNSAFE_CMD_RE.search(app_name) or any(ch in app_name for ch in ('"', "'", "\\", "/", " ", ";", "&", "|", "$")):
        if not (os.path.isfile(app_name) and os.path.splitext(app_name)[1].lower() in (".exe", ".com")):
            return "Refused to launch application: provide one executable name or an explicit .exe/.com path."

    system = platform.system()
    try:
        if system == "Windows":
            resolved = shutil.which(app_name)
            if not resolved and os.path.isfile(app_name) and os.path.splitext(app_name)[1].lower() in (".exe", ".com"):
                resolved = os.path.abspath(app_name)
            if not resolved or os.path.splitext(resolved)[1].lower() not in (".exe", ".com"):
                return "Application not found as a Windows executable. Provide a valid .exe/.com path or executable name on PATH."
            subprocess.Popen([resolved], shell=False)
        elif system == "Darwin":
            subprocess.Popen(["open", "-a", app_name], shell=False)
        else:
            resolved = shutil.which(app_name)
            if not resolved and os.path.isfile(app_name) and os.access(app_name, os.X_OK):
                resolved = os.path.abspath(app_name)
            if not resolved:
                return "Application not found as an executable. Provide an executable name on PATH."
            subprocess.Popen([resolved], shell=False)
        return f"Launched application: {app_name}"
    except Exception as exc:
        return f"Failed to launch application '{app_name}': {exc}"


def control_media(action: str) -> str:
    """Control media volume and playback via pyautogui/pycaw."""
    action = str(action or "").lower().strip()
    system = platform.system()

    if action in ("volume_up", "volup", "louder"):
        if pyautogui:
            pyautogui.press("volumeup")
            return "Volume increased."
        return "pyautogui is unavailable to adjust volume."

    elif action in ("volume_down", "voldown", "quieter"):
        if pyautogui:
            pyautogui.press("volumedown")
            return "Volume decreased."
        return "pyautogui is unavailable to adjust volume."

    elif action in ("mute", "unmute", "toggle_mute"):
        if system == "Windows" and IAudioEndpointVolume:
            try:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = interface.QueryInterface(IAudioEndpointVolume)
                current_mute = volume.GetMute()
                volume.SetMute(not current_mute, None)
                return "Mute toggled via pycaw."
            except Exception as e:
                print(f"[MediaControl] pycaw mute failed: {e}")
        if pyautogui:
            pyautogui.press("volumemute")
            return "Mute toggled."
        return "pyautogui is unavailable to toggle mute."

    elif action in ("play", "pause", "play_pause", "playpause"):
        if pyautogui:
            pyautogui.press("playpause")
            return "Media play/pause toggled."
        return "pyautogui is unavailable for media control."

    return f"Unknown or unsupported media action: '{action}'."


def window_manager(action: str) -> str:
    """Manage active window (minimize, maximize, switch, close)."""
    action = str(action or "").lower().strip()
    system = platform.system()

    if action in ("minimize", "min"):
        if pyautogui:
            if system == "Windows":
                pyautogui.hotkey("win", "down")
            elif system == "Darwin":
                pyautogui.hotkey("command", "m")
            else:
                pyautogui.hotkey("alt", "F10")
            return "Window minimized."
        return "pyautogui unavailable to minimize window."

    elif action in ("maximize", "max"):
        if pyautogui:
            if system == "Windows":
                pyautogui.hotkey("win", "up")
            else:
                pyautogui.hotkey("alt", "F10")
            return "Window maximized."
        return "pyautogui unavailable to maximize window."

    elif action in ("switch", "next"):
        if pyautogui:
            if system == "Windows":
                pyautogui.hotkey("alt", "tab")
            elif system == "Darwin":
                pyautogui.hotkey("command", "tab")
            else:
                pyautogui.hotkey("alt", "tab")
            return "Switched window."
        return "pyautogui unavailable to switch window."

    elif action in ("close", "exit"):
        if pyautogui:
            if system == "Windows":
                pyautogui.hotkey("alt", "f4")
            elif system == "Darwin":
                pyautogui.hotkey("command", "w")
            else:
                pyautogui.hotkey("alt", "f4")
            return "Window close command sent."
        return "pyautogui unavailable to close window."

    return f"Unknown window action: '{action}'."


def system_action(command: str) -> str:
    """Perform system actions like lock screen, sleep, or shutdown."""
    cmd = str(command or "").lower().strip()
    system = platform.system()

    try:
        if cmd in ("lock", "lock_screen"):
            if system == "Windows":
                subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
            elif system == "Darwin":
                subprocess.Popen(["pmset", "displaysleepnow"])
            else:
                subprocess.Popen(["loginctl", "lock-session"])
            return "Lock screen triggered."

        elif cmd in ("sleep", "standby"):
            if system == "Windows":
                subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
            elif system == "Darwin":
                subprocess.Popen(["pmset", "sleepnow"])
            else:
                subprocess.Popen(["systemctl", "suspend"])
            return "System sleep triggered."

        elif cmd in ("shutdown", "power_off"):
            if system == "Windows":
                subprocess.Popen(["shutdown", "/s", "/t", "5"])
            elif system == "Darwin":
                subprocess.Popen(["osascript", "-e", 'tell app "System Events" to shut down'])
            else:
                subprocess.Popen(["shutdown", "-h", "now"])
            return "System shutdown initiated."

        return f"Unknown system command: '{cmd}'."
    except Exception as exc:
        return f"System action '{cmd}' failed: {exc}"


def desktop_automation(parameters: dict[str, Any], response=None, player=None, session_memory=None) -> str:
    """Main action handler for desktop automation tasks."""
    params = parameters or {}
    routine = str(params.get("routine", "")).lower().strip()

    if routine == "launch_app":
        return launch_app(str(params.get("name", "")))
    elif routine == "control_media":
        return control_media(str(params.get("action", "")))
    elif routine == "window_manager":
        return window_manager(str(params.get("action", "")))
    elif routine == "system_action":
        return system_action(str(params.get("command", "")))
    else:
        return f"Unknown or missing desktop automation routine: '{routine}'"


TOOL = {
    "name": "desktop_automation",
    "description": (
        "Desktop OS automation routines for local control. "
        "Routines: 'launch_app' (launch application via subprocess), "
        "'control_media' (adjust volume or toggle play/pause via pyautogui/pycaw), "
        "'window_manager' (minimize, maximize, switch, or close active window), "
        "and 'system_action' (lock screen, sleep, or shutdown)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "routine": {
                "type": "STRING",
                "enum": ["launch_app", "control_media", "window_manager", "system_action"],
                "description": "The OS automation routine to execute.",
            },
            "name": {
                "type": "STRING",
                "description": "Application name to launch (for launch_app routine).",
            },
            "action": {
                "type": "STRING",
                "description": (
                    "Action to perform: volume_up, volume_down, mute, play_pause for control_media; "
                    "or minimize, maximize, switch, close for window_manager."
                ),
            },
            "command": {
                "type": "STRING",
                "description": "System command: lock, sleep, shutdown (for system_action routine).",
            },
        },
        "required": ["routine"],
    },
    "handler": desktop_automation,
}
