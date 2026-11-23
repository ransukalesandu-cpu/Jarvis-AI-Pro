"""Live phone/tablet screen on the laptop with scrcpy (mirror + mouse/keyboard control).

scrcpy (github.com/Genymobile/scrcpy) streams an Android screen over ADB and
lets the laptop's mouse and keyboard drive it. JARVIS only starts and stops the
window; scrcpy itself does the streaming. Works over USB, home Wi-Fi and
Tailscale (whatever serial ADB already uses).

Install on Windows: download the scrcpy zip from the GitHub releases, unzip to
``%LOCALAPPDATA%\\scrcpy`` (or anywhere on PATH), or set ``JARVIS_SCRCPY`` to
scrcpy.exe.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional


class ScrcpyError(RuntimeError):
    pass


def find_scrcpy() -> Optional[str]:
    override = os.environ.get("JARVIS_SCRCPY")
    if override:
        return override if Path(override).exists() else None
    found = shutil.which("scrcpy")
    if found:
        return found
    candidates = []
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"), str(Path.home())):
        if base:
            candidates += [Path(base) / "scrcpy" / "scrcpy.exe"]
            candidates += sorted(Path(base).glob("scrcpy*/scrcpy.exe"), reverse=True)
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def build_args(exe: str, serial: str, *, title: str, control: bool = True, max_size: int = 1280,
               max_fps: int = 30, stay_awake: bool = True, audio: bool = False) -> list[str]:
    args = [exe, "--serial", serial, "--window-title", title, "--max-size", str(int(max_size)),
            "--max-fps", str(int(max_fps))]
    if not control:
        args.append("--no-control")
    if stay_awake and control:
        args.append("--stay-awake")       # needs control; keeps the phone awake while mirrored
    if not audio:
        args.append("--no-audio")
    return args


class ScrcpyManager:
    """One scrcpy window per device name."""

    def __init__(self, *, popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 finder: Callable[[], Optional[str]] = find_scrcpy):
        self._popen = popen
        self._finder = finder
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def is_open(self, name: str) -> bool:
        proc = self._procs.get(name)
        return proc is not None and proc.poll() is None

    def show(self, name: str, serial: str, *, adb_path: str = "", control: bool = True,
             max_size: int = 1280) -> str:
        exe = self._finder()
        if not exe:
            raise ScrcpyError("scrcpy is not installed on the laptop. Download it from "
                              "github.com/Genymobile/scrcpy/releases and unzip it to %LOCALAPPDATA%\\scrcpy.")
        with self._lock:
            if self.is_open(name):
                return f"The {name} screen is already open on the laptop."
            env = dict(os.environ)
            if adb_path:
                env["ADB"] = adb_path     # scrcpy uses the same adb (and its authorised keys)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                proc = self._popen(build_args(exe, serial, title=f"JARVIS - {name}", control=control,
                                              max_size=max_size),
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                   creationflags=flags)
            except OSError as exc:
                raise ScrcpyError(f"scrcpy could not start: {exc}") from exc
            try:
                proc.wait(timeout=2.5)
            except subprocess.TimeoutExpired:
                self._procs[name] = proc
                mode = "you can use the mouse and keyboard on it" if control else "view only"
                return f"Showing the {name} screen on the laptop ({mode})."
            err = b""
            try:
                err = proc.stderr.read() if proc.stderr else b""
            except Exception:
                err = b""
            last = (err.decode("utf-8", "replace").strip().splitlines() or ["it closed immediately"])[-1]
            raise ScrcpyError(f"scrcpy could not show the {name}: {last}")

    def hide(self, name: str) -> str:
        with self._lock:
            proc = self._procs.pop(name, None)
        if proc is None or proc.poll() is not None:
            return f"The {name} screen is not open."
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        return f"Closed the {name} screen."

    def hide_all(self) -> None:
        for name in list(self._procs):
            self.hide(name)


_manager: Optional[ScrcpyManager] = None


def get_manager() -> ScrcpyManager:
    global _manager
    if _manager is None:
        _manager = ScrcpyManager()
    return _manager
