"""
Jarvis AI Pro - Autonomous Phone Controller
Direct programmatic control over connected Android devices via Wireless ADB.
"""

import base64
import logging
import re
import subprocess
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("Jarvis.PhoneController")


class AndroidPhoneController:
    def __init__(self, device_ip: Optional[str] = None, port: int = 5555):
        """
        :param device_ip: e.g. '192.168.1.15'. If None, auto-detects connected USB/ADB device.
        """
        self.device_ip = device_ip
        self.port = port
        self.device_id = f"{device_ip}:{port}" if device_ip else None
        self._ensure_connection()

    def _run_adb(self, cmd: list) -> str:
        """Executes an ADB shell command."""
        base_cmd = ["adb"]
        if self.device_id:
            base_cmd.extend(["-s", self.device_id])
        
        full_cmd = base_cmd + cmd
        try:
            res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=12)
            return res.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error(f"[PHONE] ADB command timed out: {cmd}")
            return ""
        except FileNotFoundError:
            logger.error("[PHONE] 'adb' is not installed on Windows or not in PATH.")
            return ""

    def _ensure_connection(self) -> bool:
        """Connects over Wi-Fi if IP is provided."""
        if self.device_ip:
            output = self._run_adb(["connect", f"{self.device_ip}:{self.port}"])
            logger.info(f"[PHONE] ADB Connect: {output}")
            return "connected" in output.lower()
        
        # Verify if any device is attached
        devices = self._run_adb(["devices"])
        return len(devices.splitlines()) > 1

    # ================= PHONE ACTIONS =================

    def make_call(self, phone_number: str) -> Dict[str, Any]:
        """Dials and initiates a real cellular call via your phone's SIM."""
        cleaned_num = re.sub(r"[^\d+]", "", phone_number)
        cmd = ["shell", "am", "start", "-a", "android.intent.action.CALL", "-d", f"tel:{cleaned_num}"]
        out = self._run_adb(cmd)
        return {"status": "success", "message": f"Dialing {cleaned_num} on your phone.", "raw": out}

    def end_call(self) -> Dict[str, Any]:
        """Hangs up an active phone call."""
        out = self._run_adb(["shell", "input", "keyevent", "KEYCODE_ENDCALL"])
        return {"status": "success", "message": "Call terminated."}

    def send_sms(self, phone_number: str, message: str) -> Dict[str, Any]:
        """Composes and dispatches a direct SMS."""
        cleaned_num = re.sub(r"[^\d+]", "", phone_number)
        escaped_msg = message.replace(" ", "%s").replace("'", "")
        cmd = [
            "shell", "service", "call", "isms", "7", 
            "i32", "0", "s16", "com.android.mms", 
            "s16", cleaned_num, "s16", "null", 
            "s16", f"'{escaped_msg}'", "s16", "null", "s16", "null"
        ]
        out = self._run_adb(cmd)
        return {"status": "dispatched", "target": cleaned_num}

    def open_app(self, app_name: str) -> Dict[str, Any]:
        """Launches common apps by name."""
        app_map = {
            "whatsapp": "com.whatsapp/.HomeActivity",
            "youtube": "com.google.android.youtube/com.google.android.apps.youtube.app.WatchWhileActivity",
            "spotify": "com.spotify.music/.MainActivity",
            "camera": "android.intent.action.MAIN -c android.intent.category.LAUNCHER",
            "settings": "com.android.settings/.Settings",
            "chrome": "com.android.chrome/com.google.android.apps.chrome.Main"
        }
        
        target = app_map.get(app_name.lower())
        if not target:
            # Fallback monkey launch
            out = self._run_adb(["shell", "monkey", "-p", app_name, "-c", "android.intent.category.LAUNCHER", "1"])
            return {"status": "executed", "app": app_name, "raw": out}

        out = self._run_adb(["shell", "am", "start", "-n", target])
        return {"status": "launched", "app": app_name}

    def get_battery(self) -> Dict[str, Any]:
        """Retrieves real-time phone battery level and charging state."""
        dump = self._run_adb(["shell", "dumpsys", "battery"])
        level = re.search(r"level:\s*(\d+)", dump)
        charging = "USB" in dump or "AC" in dump or "Wireless" in dump
        
        return {
            "level": int(level.group(1)) if level else "Unknown",
            "is_charging": charging
        }

    def tap(self, x: int, y: int):
        """Simulates a screen touch at pixel coordinates (x, y)."""
        return self._run_adb(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
        """Swipes from point A to point B (useful for unlocking or scrolling)."""
        return self._run_adb(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])

    def type_text(self, text: str):
        """Types raw text into the focused Android text box."""
        escaped = text.replace(" ", "%s")
        return self._run_adb(["shell", "input", "text", escaped])

    def take_screenshot_b64(self) -> str:
        """Captures the phone screen and returns base64 JPEG for Gemini Vision inspection."""
        proc = subprocess.run(["adb", "exec-out", "screencap", "-p"], capture_output=True)
        return base64.b64encode(proc.stdout).decode("utf-8")
