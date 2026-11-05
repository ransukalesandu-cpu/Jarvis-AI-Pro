"""Android control over the `adb` command line.

* The tablet is on USB (stable, and it charges). ``adb reverse`` maps the
  tablet's localhost:8765 to the laptop, so the tablet's browser reaches the
  hub with no Wi-Fi at all.
* The phone uses wireless debugging (Android 11+) while it is on the same
  network: ``adb pair`` once, then ``adb connect ip:port``. Away from home this
  does not work; the Phase 3 companion app removes that limit.

Every function shells out to ``adb`` with a timeout and raises AdbError with a
sentence JARVIS can speak. ``AndroidManager`` keeps connections alive: it
re-runs ``adb connect`` for wireless devices and re-applies ``adb reverse`` for
the tablet whenever they reappear.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

USB = "usb"
KEYCODES = {
    "home": "KEYCODE_HOME", "back": "KEYCODE_BACK", "enter": "KEYCODE_ENTER",
    "recent": "KEYCODE_APP_SWITCH", "recents": "KEYCODE_APP_SWITCH", "menu": "KEYCODE_MENU",
    "power": "KEYCODE_POWER", "volume_up": "KEYCODE_VOLUME_UP", "volume up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN", "volume down": "KEYCODE_VOLUME_DOWN",
    "mute": "KEYCODE_VOLUME_MUTE", "play_pause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "delete": "KEYCODE_DEL", "tab": "KEYCODE_TAB", "search": "KEYCODE_SEARCH",
}


class AdbError(RuntimeError):
    pass


def find_adb() -> str | None:
    override = os.environ.get("JARVIS_ADB")
    if override:
        return override
    try:
        from jarvis.services.adb_bridge import find_adb as legacy_find
        return legacy_find()
    except Exception:
        return shutil.which("adb")


def parse_devices(output: str) -> list[dict]:
    """`adb devices -l` -> [{serial, state, usb, model}]."""
    rows = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        extra = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        rows.append({"serial": serial, "state": state, "model": extra.get("model", ""),
                     "usb": ":" not in serial or "usb" in extra})
    return rows


@dataclass
class AndroidTarget:
    name: str
    serial: str = ""          # explicit serial, or "usb" for the first USB device
    address: str = ""         # ip:port for wireless debugging
    reverse_ports: list[int] = field(default_factory=list)


class Adb:
    def __init__(self, path: str | None = None, timeout: float = 20.0):
        self.path = path or find_adb()
        self.timeout = timeout

    def run(self, *args: str, serial: str | None = None, timeout: float | None = None,
            binary: bool = False, check: bool = True):
        if not self.path:
            raise AdbError("adb is not installed on the laptop (install Android platform-tools).")
        argv = [self.path] + (["-s", serial] if serial else []) + list(args)
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb timed out running {args[0] if args else 'a command'}.") from exc
        except OSError as exc:
            raise AdbError(f"adb could not start: {exc}") from exc
        if check and proc.returncode != 0:
            err = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip().splitlines()
            raise AdbError(err[-1] if err else f"adb failed ({proc.returncode}).")
        return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")

    def devices(self) -> list[dict]:
        return parse_devices(self.run("devices", "-l"))


class AndroidDevice:
    """One phone or tablet, resolved to a live adb serial on each call."""

    def __init__(self, target: AndroidTarget, adb: Adb):
        self.target, self.adb = target, adb

    @property
    def name(self) -> str:
        return self.target.name

    def serial(self) -> str:
        devices = [d for d in self.adb.devices() if d["state"] == "device"]
        t = self.target
        if t.address:
            for d in devices:
                if d["serial"] == t.address:
                    return d["serial"]
        if t.serial and t.serial != USB:
            for d in devices:
                if d["serial"] == t.serial:
                    return d["serial"]
        if t.serial == USB or (not t.serial and not t.address):
            usb = [d for d in devices if d["usb"]]
            if usb:
                return usb[0]["serial"]
        raise AdbError(f"The {t.name} is not connected over ADB right now.")

    def shell(self, command: str, timeout: float | None = None) -> str:
        return self.adb.run("shell", command, serial=self.serial(), timeout=timeout)

    # ── actions ──────────────────────────────────────────────────────────────
    def screenshot_png(self) -> bytes:
        data = self.adb.run("exec-out", "screencap", "-p", serial=self.serial(), binary=True)
        if not data.startswith(b"\x89PNG"):
            raise AdbError(f"The {self.name} did not return a screenshot.")
        return data

    def screen_size(self) -> tuple[int, int]:
        out = self.shell("wm size")
        m = re.findall(r"(\d+)x(\d+)", out)
        if not m:
            raise AdbError("Could not read the screen size.")
        w, h = m[-1]
        return int(w), int(h)

    def tap(self, x: int, y: int) -> str:
        self.shell(f"input tap {int(x)} {int(y)}")
        return f"Tapped ({int(x)}, {int(y)}) on the {self.name}."

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> str:
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}")
        return f"Swiped on the {self.name}."

    def type_text(self, text: str) -> str:
        # `input text` needs spaces as %s and shell metacharacters escaped.
        escaped = "".join(("%s" if c == " " else ("\\" + c if c in "&|;<>()$`\\\"'*?![]{}~#" else c))
                          for c in str(text))
        self.shell(f"input text {escaped}")
        return f"Typed {len(text)} characters on the {self.name}."

    def press_key(self, key: str) -> str:
        code = KEYCODES.get(str(key).strip().lower(), str(key).strip().upper())
        if not code.startswith("KEYCODE_") and not code.isdigit():
            code = "KEYCODE_" + code
        self.shell(f"input keyevent {code}")
        return f"Pressed {key} on the {self.name}."

    def list_packages(self, third_party: bool = False) -> list[str]:
        out = self.shell("pm list packages" + (" -3" if third_party else ""))
        return sorted(line.split(":", 1)[1].strip() for line in out.splitlines() if line.startswith("package:"))

    def resolve_package(self, app: str) -> str:
        """A package name, or the best installed match for an app name."""
        query = str(app or "").strip()
        packages = self.list_packages()
        if query in packages:
            return query
        words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if w]
        if not words:
            raise AdbError("Which app?")
        scored = []
        for pkg in packages:
            parts = pkg.lower().split(".")
            score = sum(3 if w in parts else (1 if w in pkg.lower() else 0) for w in words)
            if score:
                scored.append((score, -len(pkg), pkg))
        if not scored:
            raise AdbError(f"No app matching '{query}' is installed on the {self.name}.")
        return max(scored)[2]

    def open_app(self, app: str) -> str:
        pkg = self.resolve_package(app)
        self.shell(f"monkey -p {shlex.quote(pkg)} -c android.intent.category.LAUNCHER 1")
        return f"Opened {pkg} on the {self.name}."

    def open_url(self, url: str) -> str:
        self.shell(f"am start -a android.intent.action.VIEW -d {shlex.quote(str(url))}")
        return f"Opened {url} on the {self.name}."

    def info(self) -> dict:
        battery = self.shell("dumpsys battery")
        level = re.search(r"level:\s*(\d+)", battery)
        powered = re.search(r"(AC|USB|Wireless) powered:\s*true", battery)
        mem = re.search(r"MemTotal:\s*(\d+)", self.shell("cat /proc/meminfo"))
        df = self.shell("df -k /data").splitlines()
        free_gb = None
        if len(df) >= 2:
            cols = df[-1].split()
            if len(cols) >= 4 and cols[3].isdigit():
                free_gb = round(int(cols[3]) / 1e6, 1)
        return {
            "device": self.name,
            "model": self.shell("getprop ro.product.model").strip(),
            "android": self.shell("getprop ro.build.version.release").strip(),
            "sdk": self.shell("getprop ro.build.version.sdk").strip(),
            "battery_percent": int(level.group(1)) if level else None,
            "charging": bool(powered),
            "ram_gb": round(int(mem.group(1)) / 1e6, 1) if mem else None,
            "storage_free_gb": free_gb,
        }

    def push(self, local: str, remote: str) -> str:
        self.adb.run("push", local, remote, serial=self.serial(), timeout=600)
        return f"Copied {os.path.basename(local)} to {remote} on the {self.name}."

    def pull(self, remote: str, local: str) -> str:
        self.adb.run("pull", remote, local, serial=self.serial(), timeout=600)
        return f"Copied {remote} from the {self.name} to {local}."

    def reverse(self, port: int) -> None:
        self.adb.run("reverse", f"tcp:{port}", f"tcp:{port}", serial=self.serial())


class AndroidManager:
    """Keeps the configured devices connected and reports their state."""

    def __init__(self, targets: list[AndroidTarget], adb: Adb | None = None):
        self.adb = adb or Adb()
        self.devices = {t.name: AndroidDevice(t, self.adb) for t in targets}
        self.state: dict[str, dict] = {}
        self._lock = threading.Lock()

    def configure(self, rows: list[dict]) -> None:
        """Replace the device list (the hub sends it from devices.json)."""
        with self._lock:
            self.devices = {}
            for row in rows:
                name = str(row.get("name") or "").lower()
                if name:
                    target = AndroidTarget(name=name, serial=str(row.get("serial") or ""),
                                           address=str(row.get("address") or ""),
                                           reverse_ports=[int(p) for p in row.get("reverse_ports") or []])
                    self.devices[name] = AndroidDevice(target, self.adb)
            self.state = {}

    def poll_status(self) -> list[dict]:
        return [{"name": name, **row} for name, row in self.poll().items()]

    def get(self, name: str) -> AndroidDevice:
        dev = self.devices.get(str(name or "").lower())
        if dev is None:
            raise AdbError(f"I don't have an Android device called '{name}'.")
        return dev

    def poll(self) -> dict[str, dict]:
        """Reconnect wireless devices, re-apply reverse ports, return status."""
        with self._lock:
            status: dict[str, dict] = {}
            try:
                listed = {d["serial"]: d for d in self.adb.devices()}
            except AdbError as exc:
                return {name: {"online": False, "error": str(exc)} for name in self.devices}
            for name, dev in self.devices.items():
                t = dev.target
                if t.address and listed.get(t.address, {}).get("state") != "device":
                    try:
                        self.adb.run("connect", t.address, timeout=5, check=False)
                        listed = {d["serial"]: d for d in self.adb.devices()}
                    except AdbError:
                        pass
                try:
                    serial = dev.serial()
                except AdbError as exc:
                    status[name] = {"online": False, "error": str(exc)}
                    continue
                was_online = self.state.get(name, {}).get("online")
                for port in t.reverse_ports:
                    if not was_online:
                        try:
                            dev.reverse(port)
                        except AdbError as exc:
                            status.setdefault(name, {})["reverse_error"] = str(exc)
                status[name] = {**status.get(name, {}), "online": True, "serial": serial,
                                "transport": "wifi" if ":" in serial else "usb"}
            self.state = status
            return status

    def run_forever(self, interval: float, stop: threading.Event, on_status) -> None:
        while not stop.is_set():
            on_status(self.poll())
            stop.wait(interval)


def wait_for(predicate, timeout: float, step: float = 0.2) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return False
