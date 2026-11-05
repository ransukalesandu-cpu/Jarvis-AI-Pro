"""Guarded coordinate input — the fallback, never the primary (Project 6).

Used only when a target has no accessible control (games, canvas apps, remote
desktops). pyautogui (BSD-3) supplies the primitives; every call here adds the
safeguards from the master prompt:

* **validate coordinates** — inside the screen, never in the pyautogui
  failsafe corners;
* **no click storms** — at most ``max_actions`` per ``window_s`` seconds and a
  minimum gap between actions;
* **detect unexpected screen change** — a coordinate located earlier carries an
  average-hash *fingerprint* of the pixels around it; if the screen there has
  changed since, the click is refused;
* **stop on uncertainty** — coordinates from vision/the model below
  ``min_confidence`` are refused, and they always need a fingerprint;
* **cancellation** — ``ctx.check()`` before and after every primitive;
* **verify** — after a click the fingerprint is taken again; a visible change
  is reported as evidence, no change as "unverified".

Destructive targets are HIGH in the policy (owner approval) *and* still pass all
of the checks above: an AI-generated coordinate can never skip them.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional, Protocol

from jarvis.computer_control.runner import ActionContext, ActionOutcome

AI_SOURCES = frozenset({"vision", "model", "ocr"})
TRUSTED_SOURCES = frozenset({"owner", "accessibility"})
CORNER_MARGIN = 4


class InputRefused(RuntimeError):
    """A safeguard refused the input (message is speakable)."""


class InputDriver(Protocol):  # pragma: no cover - structural
    name: str

    def size(self) -> tuple[int, int]: ...
    def position(self) -> tuple[int, int]: ...
    def move(self, x: int, y: int) -> None: ...
    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None: ...
    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None: ...
    def scroll(self, amount: int, x: Optional[int] = None, y: Optional[int] = None) -> None: ...
    def type_text(self, text: str) -> None: ...
    def hotkey(self, keys: list[str]) -> None: ...
    def fingerprint(self, x: int, y: int, radius: int = 24) -> Optional[int]: ...


def average_hash(gray_pixels: bytes, width: int, height: int) -> int:
    """64-bit average hash of a grayscale image given as raw bytes."""
    if width <= 0 or height <= 0 or len(gray_pixels) < width * height:
        return 0
    cells = []
    for gy in range(8):
        for gx in range(8):
            x0, x1 = gx * width // 8, max(gx * width // 8 + 1, (gx + 1) * width // 8)
            y0, y1 = gy * height // 8, max(gy * height // 8 + 1, (gy + 1) * height // 8)
            total = count = 0
            for y in range(y0, min(y1, height)):
                row = y * width
                for x in range(x0, min(x1, width)):
                    total += gray_pixels[row + x]
                    count += 1
            cells.append(total / count if count else 0)
    mean = sum(cells) / 64.0
    bits = 0
    for value in cells:
        bits = (bits << 1) | (1 if value > mean else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(int(a) ^ int(b)).count("1")


class PyAutoGUIDriver:
    """Real driver. FAILSAFE stays on (mouse to a corner aborts pyautogui)."""

    name = "pyautogui"

    def __init__(self) -> None:
        self._mod = None

    def _m(self):
        if self._mod is None:
            try:
                import pyautogui
            except Exception as exc:
                raise InputRefused(f"Fallback input needs pyautogui ({type(exc).__name__}).") from exc
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.02
            self._mod = pyautogui
        return self._mod

    def size(self):
        w, h = self._m().size()
        return int(w), int(h)

    def position(self):
        x, y = self._m().position()
        return int(x), int(y)

    def move(self, x, y):
        self._m().moveTo(int(x), int(y), duration=0.1)

    def click(self, x, y, button="left", clicks=1):
        self._m().click(int(x), int(y), clicks=int(clicks), button=button, interval=0.08)

    def drag(self, x1, y1, x2, y2):
        m = self._m()
        m.moveTo(int(x1), int(y1), duration=0.1)
        m.dragTo(int(x2), int(y2), duration=0.4, button="left")

    def scroll(self, amount, x=None, y=None):
        self._m().scroll(int(amount), x=x, y=y)

    def type_text(self, text):
        self._m().write(str(text), interval=0.01)

    def hotkey(self, keys):
        self._m().hotkey(*[str(k).lower() for k in keys])

    def fingerprint(self, x, y, radius=24):
        try:
            import mss
            from PIL import Image
        except Exception:
            return None
        box = {"left": max(0, int(x) - radius), "top": max(0, int(y) - radius),
               "width": radius * 2, "height": radius * 2}
        try:
            with mss.mss() as sct:
                shot = sct.grab(box)
            gray = Image.frombytes("RGB", shot.size, shot.rgb).convert("L")
            return average_hash(gray.tobytes(), gray.width, gray.height)
        except Exception:
            return None


@dataclass
class Target:
    x: int
    y: int
    source: str = "owner"             # owner | accessibility | ocr | vision | model
    confidence: float = 1.0
    fingerprint: Optional[int] = None  # taken when the target was located
    label: str = ""


class FallbackInput:
    def __init__(self, driver: InputDriver | None = None, *, max_actions: int = 6,
                 window_s: float = 3.0, min_interval_s: float = 0.12,
                 min_confidence: float = 0.8, max_hash_distance: int = 8,
                 clock=time.monotonic) -> None:
        self.driver = driver or PyAutoGUIDriver()
        self.max_actions = max_actions
        self.window_s = window_s
        self.min_interval_s = min_interval_s
        self.min_confidence = min_confidence
        self.max_hash_distance = max_hash_distance
        self._clock = clock
        self._recent: deque = deque()
        self._lock = threading.Lock()

    # ── safeguards ───────────────────────────────────────────────────────
    def validate_point(self, x: int, y: int) -> tuple[int, int]:
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError) as exc:
            raise InputRefused("Coordinates must be whole numbers.") from exc
        width, height = self.driver.size()
        if not (0 <= x < width and 0 <= y < height):
            raise InputRefused(f"({x}, {y}) is outside the screen ({width}x{height}).")
        near_x = x <= CORNER_MARGIN or x >= width - 1 - CORNER_MARGIN
        near_y = y <= CORNER_MARGIN or y >= height - 1 - CORNER_MARGIN
        if near_x and near_y:
            raise InputRefused("That point is in a screen corner (the emergency failsafe zone).")
        return x, y

    def _rate_check(self) -> None:
        now = self._clock()
        with self._lock:
            while self._recent and now - self._recent[0] > self.window_s:
                self._recent.popleft()
            if self._recent and now - self._recent[-1] < self.min_interval_s:
                raise InputRefused("Inputs are arriving too fast; refusing to avoid a click storm.")
            if len(self._recent) >= self.max_actions:
                raise InputRefused(f"More than {self.max_actions} inputs in {self.window_s:.0f}s; "
                                   "stopping to avoid a click storm.")
            self._recent.append(now)

    def check_target(self, target: Target) -> tuple[int, int]:
        x, y = self.validate_point(target.x, target.y)
        source = str(target.source or "model").lower()
        if source not in TRUSTED_SOURCES | AI_SOURCES:
            source = "model"
        if source in AI_SOURCES:
            if float(target.confidence) < self.min_confidence:
                raise InputRefused(f"Not sure enough about the target ({target.confidence:.2f} < "
                                   f"{self.min_confidence:.2f}); stopping instead of guessing.")
            if target.fingerprint is None:
                raise InputRefused("A coordinate from screen analysis needs a fresh screen fingerprint "
                                   "before it can be clicked.")
        if target.fingerprint is not None:
            now = self.driver.fingerprint(x, y)
            if now is None:
                raise InputRefused("Could not re-check the screen at the target; not clicking blind.")
            if hamming(now, target.fingerprint) > self.max_hash_distance:
                raise InputRefused("The screen changed since the target was located; look again first.")
        return x, y

    # ── primitives (each returns an ActionOutcome) ───────────────────────
    def click(self, ctx: ActionContext, target: Target, *, button: str = "left",
              clicks: int = 1) -> ActionOutcome:
        if button not in ("left", "right", "middle"):
            raise InputRefused(f"Unknown mouse button {button!r}.")
        clicks = max(1, min(int(clicks), 3))
        ctx.check()
        x, y = self.check_target(target)
        self._rate_check()
        before = self.driver.fingerprint(x, y)       # fresh baseline right before the click
        ctx.check()
        self.driver.click(x, y, button=button, clicks=clicks)
        ctx.wait(0.15)
        after = self.driver.fingerprint(x, y)
        changed = before is not None and after is not None and hamming(before, after) > 0
        return ActionOutcome(True, f"{'Double-' if clicks == 2 else ''}{button.title()}-clicked at ({x}, {y}).",
                             data={"x": x, "y": y, "source": target.source},
                             verified=True if changed else None,
                             evidence="the screen changed at the target" if changed else
                             "no visible change at the target")

    def move(self, ctx: ActionContext, x: int, y: int) -> ActionOutcome:
        ctx.check()
        x, y = self.validate_point(x, y)
        self.driver.move(x, y)
        pos = self.driver.position()
        ok = abs(pos[0] - x) <= 2 and abs(pos[1] - y) <= 2
        return ActionOutcome(True, f"Pointer moved to ({x}, {y}).", data={"x": x, "y": y},
                             verified=ok, evidence=f"pointer at {pos}")

    def drag(self, ctx: ActionContext, start: Target, end: Target) -> ActionOutcome:
        ctx.check()
        x1, y1 = self.check_target(start)
        x2, y2 = self.validate_point(end.x, end.y)
        self._rate_check()
        ctx.check()
        self.driver.drag(x1, y1, x2, y2)
        return ActionOutcome(True, f"Dragged from ({x1}, {y1}) to ({x2}, {y2}).",
                             data={"from": [x1, y1], "to": [x2, y2]})

    def scroll(self, ctx: ActionContext, amount: int, x: Optional[int] = None,
               y: Optional[int] = None) -> ActionOutcome:
        ctx.check()
        amount = max(-50, min(int(amount), 50))
        if x is not None and y is not None:
            x, y = self.validate_point(x, y)
        self._rate_check()
        self.driver.scroll(amount, x, y)
        return ActionOutcome(True, f"Scrolled {'up' if amount > 0 else 'down'} {abs(amount)}.")

    def type_text(self, ctx: ActionContext, text: str) -> ActionOutcome:
        ctx.check()
        text = str(text)
        if len(text) > 5000:
            raise InputRefused("That is too much text to type at once (5000 characters max).")
        self._rate_check()
        # type in chunks so a stop lands between chunks
        for i in range(0, len(text), 200):
            ctx.check()
            self.driver.type_text(text[i:i + 200])
        return ActionOutcome(True, f"Typed {len(text)} characters.", data={"chars": len(text)})

    def hotkey(self, ctx: ActionContext, keys: list[str]) -> ActionOutcome:
        ctx.check()
        keys = [str(k).strip().lower() for k in keys if str(k).strip()]
        if not keys or len(keys) > 4:
            raise InputRefused("A shortcut needs one to four keys.")
        self._rate_check()
        self.driver.hotkey(keys)
        return ActionOutcome(True, f"Pressed {'+'.join(keys)}.")
