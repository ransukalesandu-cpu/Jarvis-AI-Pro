"""
services/adb_bridge.py — ADB Reverse Port Forwarding Helper for JARVIS

Discovers `adb.exe`, parses device status, verifies active reverse rules,
and manages port forwarding for USB Android Tablet connections.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_adb() -> str | None:
    """Find the path to the adb executable on Windows or Linux/macOS."""
    # 1. System PATH
    found = shutil.which("adb")
    if found:
        return found

    # 2. Candidate paths for Windows and standard Android SDK locations
    candidates = [
        os.path.expandvars(r"%ANDROID_HOME%\platform-tools\adb.exe"),
        os.path.expandvars(r"%ANDROID_SDK_ROOT%\platform-tools\adb.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
        os.path.expanduser(r"~\AppData\Local\Android\Sdk\platform-tools\adb.exe"),
        os.path.expanduser(r"~\scoop\shims\adb.exe"),
        r"C:\ProgramData\chocolatey\bin\adb.exe",
        r"C:\platform-tools\adb.exe",
        r"C:\Program Files\Android\android-sdk\platform-tools\adb.exe",
        r"C:\Program Files (x86)\Android\android-sdk\platform-tools\adb.exe",
    ]

    for cand in candidates:
        if cand and os.path.isfile(cand):
            return cand
    return None


def parse_adb_devices(output: str) -> list[dict[str, str]]:
    """
    Parse output from `adb devices`.
    Returns list of dicts: [{"serial": "...", "status": "device"|"unauthorized"|"offline"}]
    """
    devices = []
    lines = output.strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            serial, status = parts[0], parts[1]
            devices.append({"serial": serial, "status": status})
    return devices


def select_authorized_device(devices: list[dict[str, str]]) -> dict[str, str] | None:
    """Select the first authorized 'device' from parsed adb devices."""
    for dev in devices:
        if dev.get("status") == "device":
            return dev
    return None


def is_reverse_rule_active(reverse_list_output: str, port: int) -> bool:
    """
    Check whether `adb reverse --list` output contains a reverse rule for target tcp:<port>.
    Example reverse list line: "tcp:8000 tcp:8000" or "(remote) tcp:8000 (local) tcp:8000"
    """
    rule_str = f"tcp:{port}"
    for line in reverse_list_output.splitlines():
        if rule_str in line:
            return True
    return False


def apply_reverse_forwarding(adb_path: str, serial: str, local_port: int = 8000, remote_port: int = 8000) -> tuple[bool, str]:
    """Execute `adb -s <serial> reverse tcp:<remote_port> tcp:<local_port>`."""
    try:
        cmd = [adb_path, "-s", serial, "reverse", f"tcp:{remote_port}", f"tcp:{local_port}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return True, res.stdout.strip()
        return False, res.stderr.strip() or res.stdout.strip()
    except Exception as exc:
        return False, str(exc)


def remove_reverse_forwarding(adb_path: str, port: int = 8000) -> tuple[bool, str]:
    """Execute `adb reverse --remove tcp:<port>`."""
    try:
        cmd = [adb_path, "reverse", "--remove", f"tcp:{port}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return True, res.stdout.strip()
        return False, res.stderr.strip() or res.stdout.strip()
    except Exception as exc:
        return False, str(exc)
