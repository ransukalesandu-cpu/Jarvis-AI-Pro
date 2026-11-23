"""Android UI tree: find and act on screen elements by their text, not pixels.

The ADB tools could only tap coordinates, so every phone task needed a
screenshot and a vision call. Android already knows what is on screen: the
UI Automator hierarchy lists every view with its text, content description,
resource id and bounds. This module reads that tree and lets JARVIS say
"tap Send" or "wait for Downloaded" directly.

Backends (first that works):
  * ``uiautomator2`` (pip install uiautomator2) when installed — faster and
    more reliable while apps animate;
  * plain ``adb shell uiautomator dump`` — needs nothing extra.

Set ``JARVIS_ANDROID_U2=0`` to force the plain backend.

Texts from the screen are untrusted content: callers wrap them before they
reach a model. Password fields are never echoed.
"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Optional

from jarvis.core import failsoft

DUMP_PATH = "/sdcard/jarvis_ui.xml"
_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


class UiError(RuntimeError):
    pass


@dataclass
class Element:
    index: int
    text: str
    desc: str
    rid: str
    cls: str
    package: str
    bounds: tuple[int, int, int, int]
    clickable: bool
    scrollable: bool
    focused: bool
    password: bool
    enabled: bool
    parent: Optional[int]

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def visible(self) -> bool:
        x1, y1, x2, y2 = self.bounds
        return x2 > x1 and y2 > y1

    @property
    def short_id(self) -> str:
        return self.rid.split("/", 1)[-1] if self.rid else ""

    @property
    def label(self) -> str:
        if self.password:
            return "[password field]"
        return self.text or self.desc or self.short_id

    @property
    def kind(self) -> str:
        return self.cls.rsplit(".", 1)[-1] if self.cls else "View"


def parse_hierarchy(xml_text: str) -> list[Element]:
    """UI Automator XML → flat list with parent links (document order)."""
    text = str(xml_text or "")
    start = text.find("<")
    if start < 0:
        raise UiError("The phone did not return its screen layout.")
    # `uiautomator dump /dev/tty` appends a status line after the XML.
    end = text.rfind(">")
    try:
        root = ET.fromstring(text[start:end + 1])
    except ET.ParseError as exc:
        raise UiError(f"Could not read the phone's screen layout ({exc}).") from exc
    out: list[Element] = []

    def walk(node, parent: Optional[int]) -> None:
        for child in node:
            if child.tag != "node":
                walk(child, parent)
                continue
            a = child.attrib
            m = _BOUNDS.match(a.get("bounds", ""))
            bounds = tuple(int(v) for v in m.groups()) if m else (0, 0, 0, 0)
            el = Element(
                index=len(out), text=a.get("text", "").strip(), desc=a.get("content-desc", "").strip(),
                rid=a.get("resource-id", ""), cls=a.get("class", ""), package=a.get("package", ""),
                bounds=bounds,  # type: ignore[arg-type]
                clickable=a.get("clickable") == "true" or a.get("long-clickable") == "true",
                scrollable=a.get("scrollable") == "true", focused=a.get("focused") == "true",
                password=a.get("password") == "true", enabled=a.get("enabled", "true") == "true",
                parent=parent,
            )
            if el.password:
                el.text = ""
            out.append(el)
            walk(child, el.index)

    walk(root, None)
    return out


def meaningful(elements: list[Element]) -> list[Element]:
    """Elements worth telling the model about: visible and labelled or clickable."""
    return [e for e in elements if e.visible and (e.text or e.desc or e.password
                                                  or (e.clickable and e.short_id) or e.scrollable)]


def summarize(elements: list[Element], limit: int = 60) -> str:
    rows = []
    for e in meaningful(elements)[:limit]:
        flags = "".join(f for f, on in (("C", e.clickable), ("S", e.scrollable), ("F", e.focused)) if on)
        label = e.label.replace("\n", " ")[:80]
        rows.append(f"#{e.index} {e.kind} \"{label}\"" + (f" id={e.short_id}" if e.short_id else "")
                    + (f" [{flags}]" if flags else "") + f" @{e.center[0]},{e.center[1]}")
    more = len(meaningful(elements)) - len(rows)
    if more > 0:
        rows.append(f"... {more} more")
    return "\n".join(rows) if rows else "(no readable elements on screen)"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def find(elements: list[Element], query: str, *, prefer_clickable: bool = True) -> Optional[Element]:
    """Best element for ``query``: '#12' index, 'id:send_btn', or visible text/description."""
    q = str(query or "").strip()
    if not q:
        return None
    if q.startswith("#") and q[1:].isdigit():
        i = int(q[1:])
        return elements[i] if 0 <= i < len(elements) else None
    want_id = q[3:].strip().lower() if q.lower().startswith("id:") else ""
    nq = _norm(q)
    best, best_score = None, 0
    for e in elements:
        if not e.visible or e.password and not want_id:
            continue
        score = 0
        if want_id:
            if e.short_id.lower() == want_id or e.rid.lower() == want_id:
                score = 100
        else:
            for value, weight in ((e.text, 0), (e.desc, -2)):
                v = _norm(value)
                if not v:
                    continue
                if v == nq:
                    score = max(score, 90 + weight)
                elif v.startswith(nq) or nq.startswith(v) and len(v) >= 3:
                    score = max(score, 60 + weight)
                elif nq in v:
                    score = max(score, 40 + weight)
            if not score and e.short_id and _norm(e.short_id.replace("_", " ")) == nq:
                score = 50
        if not score:
            continue
        if prefer_clickable and (e.clickable or clickable_ancestor(elements, e) is not None):
            score += 5
        if e.enabled:
            score += 1
        if score > best_score:
            best, best_score = e, score
    return best


def clickable_ancestor(elements: list[Element], el: Element) -> Optional[Element]:
    cur = el
    for _ in range(12):
        if cur.clickable:
            return cur
        if cur.parent is None:
            return None
        cur = elements[cur.parent]
    return None


def tap_point(elements: list[Element], el: Element) -> tuple[int, int]:
    """Tap the element itself if clickable, else its clickable container (a label inside a row)."""
    target = clickable_ancestor(elements, el) or el
    # A container far larger than the label (a whole list) would tap the wrong
    # spot; use the label's own centre then.
    tx1, ty1, tx2, ty2 = target.bounds
    ex1, ey1, ex2, ey2 = el.bounds
    if (tx2 - tx1) * (ty2 - ty1) > 12 * max(1, (ex2 - ex1) * (ey2 - ey1)):
        return el.center
    return target.center


# ── backends ─────────────────────────────────────────────────────────────────
def _u2_enabled() -> bool:
    if str(os.environ.get("JARVIS_ANDROID_U2", "1")).strip().lower() in {"0", "off", "false", "no"}:
        return False
    import importlib.util
    return importlib.util.find_spec("uiautomator2") is not None


def dump_xml(shell: Callable[[str], str], serial: str = "") -> str:
    """Return the current UI hierarchy XML (uiautomator2 when installed, else plain adb)."""
    if serial and _u2_enabled():
        try:
            import uiautomator2 as u2
            return u2.connect(serial).dump_hierarchy()
        except Exception:
            failsoft.suppress("laptop_agent.devices.android_ui:u2_dump")  # fall back to the plain dump
    out = shell(f"uiautomator dump {DUMP_PATH}")
    if "dumped" not in out.lower() and "<" not in out:
        # Some ROMs refuse while an animation runs; one retry is usually enough.
        time.sleep(0.6)
        out = shell(f"uiautomator dump {DUMP_PATH}")
    xml_text = shell(f"cat {DUMP_PATH}")
    if "<hierarchy" not in xml_text:
        raise UiError("The phone's screen layout could not be read (the screen may be locked or secure).")
    return xml_text


class AndroidUi:
    """Element-level actions for one AndroidDevice (anything with shell/serial/tap/swipe/screen_size)."""

    def __init__(self, device, *, sleep: Callable[[float], None] = time.sleep):
        self.dev = device
        self._sleep = sleep

    def elements(self) -> list[Element]:
        try:
            serial = self.dev.serial()
        except Exception:
            serial = ""
        return parse_hierarchy(dump_xml(self.dev.shell, serial))

    def tree(self, limit: int = 60) -> str:
        return summarize(self.elements(), limit)

    def tap(self, query: str) -> str:
        elements = self.elements()
        el = find(elements, query)
        if el is None:
            raise UiError(f"I can't see '{query}' on the {self.dev.name} screen.")
        x, y = tap_point(elements, el)
        self.dev.tap(x, y)
        return f"Tapped \"{el.label}\" on the {self.dev.name}."

    def set_text(self, query: str, text: str) -> str:
        if query:
            self.tap(query)
            self._sleep(0.3)
        self.dev.type_text(text)
        return f"Typed {len(text)} characters into {query or 'the focused field'} on the {self.dev.name}."

    def wait_for(self, query: str, timeout: float = 10.0, *, gone: bool = False) -> str:
        end = time.monotonic() + max(0.5, float(timeout))
        while True:
            try:
                present = find(self.elements(), query, prefer_clickable=False) is not None
            except UiError:
                present = False
            if present != gone:
                state = "gone from" if gone else "showing on"
                return f"'{query}' is {state} the {self.dev.name} screen."
            if time.monotonic() >= end:
                state = "still on" if gone else "did not appear on"
                raise UiError(f"'{query}' {state} the {self.dev.name} screen within {timeout:g}s.")
            self._sleep(0.8)

    def scroll_to(self, query: str, max_swipes: int = 8, direction: str = "down") -> str:
        w, h = self.dev.screen_size()
        down = str(direction or "down").lower() != "up"
        last = None
        for _ in range(max(1, int(max_swipes)) + 1):
            elements = self.elements()
            if find(elements, query, prefer_clickable=False) is not None:
                return f"'{query}' is now on the {self.dev.name} screen."
            signature = tuple(e.label for e in meaningful(elements))
            if signature == last:
                break   # the list stopped moving: end reached
            last = signature
            y1, y2 = (int(h * 0.75), int(h * 0.3)) if down else (int(h * 0.3), int(h * 0.75))
            self.dev.swipe(w // 2, y1, w // 2, y2, 350)
            self._sleep(0.5)
        raise UiError(f"Scrolled but couldn't find '{query}' on the {self.dev.name}.")
