"""Android tools, each taking ``device`` (tablet, phone...). Generic: no per-app code.

device_screenshot, open_app, open_url, tap, swipe, type_text, press_key,
device_shell, list_apps, device_info, push_file, pull_file, and ui_automate
(the Phase 1 screenshot -> Gemini vision -> act loop, with ADB as backend).

Where a name also exists for the laptop (open_app, ui_automate) the agent
announces one merged declaration and routes by ``device``. For device=laptop
the Android-only tools map to their laptop equivalents.
"""
from __future__ import annotations

import io
import json
import os

from jarvis.laptop_agent.devices.android import AdbError, AndroidManager


def _png_to_jpeg(png: bytes, max_side: int = 1600) -> tuple[bytes, float, int, int]:
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("RGB")
    scale = 1.0
    if max(img.size) > max_side:
        scale = max(img.size) / max_side
        img = img.resize((int(img.width / scale), int(img.height / scale)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue(), scale, img.width, img.height


class AdbDriver:
    """core.ui_automation driver that acts through `adb shell input`."""

    def __init__(self, dev):
        self.dev = dev

    def perform(self, step: dict, frame) -> str:
        action = step["action"]
        if action in ("click", "double_click", "right_click"):
            x, y = frame.to_screen(float(step["x"]), float(step["y"]))
            self.dev.tap(x, y)
            if action == "double_click":
                self.dev.tap(x, y)
            return f"at ({x},{y})"
        if action == "type":
            self.dev.type_text(str(step.get("text", "")))
            return repr(str(step.get("text", ""))[:60])
        if action in ("press", "hotkey"):
            key = (step.get("keys") or ["enter"])[-1]
            self.dev.press_key(str(key))
            return str(key)
        if action == "scroll":
            w, h = self.dev.screen_size()
            amount = int(step.get("amount", -5))
            y1, y2 = (int(h * 0.7), int(h * 0.3)) if amount < 0 else (int(h * 0.3), int(h * 0.7))
            self.dev.swipe(w // 2, y1, w // 2, y2, 350)
            return str(amount)
        if action == "wait":
            import time
            time.sleep(1.5)
            return "1.5s"
        return ""


class AndroidTools:
    def __init__(self, manager: AndroidManager):
        self.manager = manager

    def names(self) -> set[str]:
        return {d["name"] for d in DECLARATIONS}

    def is_android(self, device: str) -> bool:
        return str(device or "").lower() in self.manager.devices

    def run(self, name: str, args: dict, device: str, ctx: dict) -> str:
        dev = self.manager.get(device)
        try:
            return getattr(self, f"_{name}")(dev, args, ctx)
        except AdbError as exc:
            return str(exc)

    # ── handlers ─────────────────────────────────────────────────────────────
    def _device_screenshot(self, dev, args, ctx):
        jpeg, _scale, _w, _h = _png_to_jpeg(dev.screenshot_png())
        show = ctx.get("show_image")
        if show is not None:
            show(jpeg, "image/jpeg", str(args.get("question") or f"What is on the {dev.name} screen?"),
                 f"{dev.name} screen")
            return f"Captured the {dev.name} screen; it follows this message. Describe it from the image."
        return f"Captured the {dev.name} screen ({len(jpeg)} bytes)."

    def _open_app(self, dev, args, ctx):
        return dev.open_app(str(args.get("package") or args.get("app_name") or args.get("app") or ""))

    def _open_url(self, dev, args, ctx):
        return dev.open_url(str(args.get("url") or ""))

    def _tap(self, dev, args, ctx):
        return dev.tap(int(args.get("x", 0)), int(args.get("y", 0)))

    def _swipe(self, dev, args, ctx):
        return dev.swipe(int(args.get("x1", 0)), int(args.get("y1", 0)), int(args.get("x2", 0)),
                         int(args.get("y2", 0)), int(args.get("duration_ms") or 300))

    def _type_text(self, dev, args, ctx):
        return dev.type_text(str(args.get("text") or ""))

    def _press_key(self, dev, args, ctx):
        return dev.press_key(str(args.get("key") or "home"))

    def _device_shell(self, dev, args, ctx):
        from jarvis.core import injection_guard
        out = dev.shell(str(args.get("command") or ""), timeout=float(args.get("timeout_seconds") or 30))
        return injection_guard.wrap_untrusted(out[-6000:] or "(no output)", f"{dev.name} shell")

    def _list_apps(self, dev, args, ctx):
        pkgs = dev.list_packages(third_party=not args.get("include_system"))
        query = str(args.get("query") or "").lower()
        if query:
            pkgs = [p for p in pkgs if query in p.lower()]
        return f"{len(pkgs)} app(s): " + ", ".join(pkgs[:80])

    def _device_info(self, dev, args, ctx):
        return json.dumps(dev.info())

    def _push_file(self, dev, args, ctx):
        src = os.path.expandvars(os.path.expanduser(str(args.get("path") or "")))
        if not os.path.exists(src):
            return f"There is no file {src} on the laptop."
        dest = str(args.get("destination") or "/sdcard/Download/")
        if dest.endswith("/"):
            dest += os.path.basename(src)
        return dev.push(src, dest)

    def _pull_file(self, dev, args, ctx):
        remote = str(args.get("path") or "")
        dest = os.path.expandvars(os.path.expanduser(str(args.get("destination") or "~/Downloads")))
        if os.path.isdir(dest):
            dest = os.path.join(dest, os.path.basename(remote.rstrip("/")))
        return dev.pull(remote, dest)

    def _ui_automate(self, dev, args, ctx):
        from jarvis.core.capture import Frame
        from jarvis.core.ui_automation import automate

        def capture(_window):
            jpeg, scale, w, h = _png_to_jpeg(dev.screenshot_png())
            return Frame(jpeg=jpeg, width=w, height=h, scale=scale)
        result = automate(str(args.get("goal") or ""), max_steps=int(args.get("max_steps") or 15),
                          cancel_event=ctx.get("cancel_event"), capture=capture, driver=AdbDriver(dev))
        return result.summary()


# What each Android-only tool means for device=laptop (tool, argument mapping).
LAPTOP_EQUIVALENTS = {
    "device_screenshot": ("see_screen", lambda a: {"question": a.get("question", "")}),
    "open_url": ("open", lambda a: {"target": a.get("url", "")}),
    "device_shell": ("run_command", lambda a: {"command": a.get("command", ""),
                                               "timeout_seconds": a.get("timeout_seconds", 60)}),
    "device_info": ("system_info", lambda a: {"what": "all"}),
    "list_apps": ("software", lambda a: {"action": "list", "query": a.get("query", "")}),
}

_DEV = {"type": "STRING", "description": "tablet, phone (Android), or laptop"}
DECLARATIONS = [
    {"name": "device_screenshot", "description": "Take a screenshot of a device's screen and look at it "
     "('what is on my phone screen?').", "parameters": {"type": "OBJECT", "properties": {
         "device": _DEV, "question": {"type": "STRING"}}}},
    {"name": "open_url", "description": "Open a web address on a device.",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV, "url": {"type": "STRING"}},
                    "required": ["url"]}},
    {"name": "tap", "description": "Tap a point (pixels) on an Android device's screen.",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV, "x": {"type": "INTEGER"},
                                                     "y": {"type": "INTEGER"}}, "required": ["x", "y"]}},
    {"name": "swipe", "description": "Swipe on an Android device's screen from (x1,y1) to (x2,y2).",
     "parameters": {"type": "OBJECT", "properties": {
         "device": _DEV, "x1": {"type": "INTEGER"}, "y1": {"type": "INTEGER"},
         "x2": {"type": "INTEGER"}, "y2": {"type": "INTEGER"}, "duration_ms": {"type": "INTEGER"}},
         "required": ["x1", "y1", "x2", "y2"]}},
    {"name": "type_text", "description": "Type text into the focused field on an Android device.",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV, "text": {"type": "STRING"}},
                    "required": ["text"]}},
    {"name": "press_key", "description": "Press a key on an Android device: home, back, enter, recents, "
     "volume_up, volume_down, mute, power, play_pause.",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV, "key": {"type": "STRING"}},
                    "required": ["key"]}},
    {"name": "device_shell", "description": "Run a shell command on a device (adb shell on Android).",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV, "command": {"type": "STRING"},
                                                     "timeout_seconds": {"type": "NUMBER"}},
                    "required": ["command"]}},
    {"name": "list_apps", "description": "List the apps installed on a device (optionally filtered).",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV, "query": {"type": "STRING"},
                                                     "include_system": {"type": "BOOLEAN"}}}},
    {"name": "device_info", "description": "Battery, storage, RAM and Android version of a device.",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV}}},
    {"name": "push_file", "description": "Send a file from the laptop to an Android device "
     "(default folder /sdcard/Download/).",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV, "path": {"type": "STRING"},
                                                     "destination": {"type": "STRING"}},
                    "required": ["path"]}},
    {"name": "pull_file", "description": "Copy a file from an Android device to the laptop "
     "(default ~/Downloads).",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV, "path": {"type": "STRING"},
                                                     "destination": {"type": "STRING"}},
                    "required": ["path"]}},
    # Shared with laptop tools of the same name; merged by the tool host.
    {"name": "open_app", "description": "With device=tablet or phone: open an Android app by package "
     "name or app name (searches installed packages).",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV, "package": {"type": "STRING"},
                                                     "app_name": {"type": "STRING"}}}},
    {"name": "ui_automate", "description": "With device=tablet or phone: operate any Android app by "
     "looking at the screen and tapping/typing until the goal is done.",
     "parameters": {"type": "OBJECT", "properties": {"device": _DEV, "goal": {"type": "STRING"},
                                                     "max_steps": {"type": "INTEGER"}},
                    "required": ["goal"]}},
]
META = {"device_shell": {"risk": "destructive", "timeout": 120},
        "push_file": {"risk": "write", "timeout": 900}, "pull_file": {"risk": "write", "timeout": 900},
        "ui_automate": {"risk": "destructive", "long_running": True},
        "device_screenshot": {"risk": "read", "timeout": 30}, "device_info": {"risk": "read", "timeout": 30},
        "list_apps": {"risk": "read", "timeout": 30}}
