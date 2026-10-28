"""Optional OS accessibility bridge for stable element lookup.

Blind coordinate clicks are the least reliable way to drive a desktop: a theme
change, a notification, or a DPI shift moves the target. Where the operating
system exposes an accessibility tree, JARVIS asks for the control *by name* and
gets an exact rectangle back.

Support is intentionally best-effort and read-only:

* Windows — UI Automation through ``pywinauto`` (already a declared dependency).
* Linux   — AT-SPI through ``pyatspi``/``gi`` when the desktop exposes it.
* macOS   — the AX API through ``pyobjc`` when installed.

Every method returns an empty list rather than raising when the platform or the
library is unavailable, so the caller falls back to OCR/vision without special
casing. Nothing here grants privileges: it only *finds*, and the caller still
has to pass the policy engine before acting.
"""

from __future__ import annotations

import platform
import re
from typing import Any, Iterable

from agent.screen_vision import ElementTarget


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


class AccessibilityBridge:
    """Cross-platform, failure-tolerant lookup of named controls."""

    def __init__(self, *, limit: int = 400):
        self.limit = max(20, int(limit))
        self.platform = platform.system()
        self._failure_reason = ""

    # -- availability ------------------------------------------------------
    def available(self) -> bool:
        if self.platform == "Windows":
            try:
                import pywinauto  # noqa: F401
            except Exception as exc:
                self._failure_reason = f"pywinauto unavailable: {exc}"
                return False
            return True
        if self.platform == "Linux":
            try:
                import pyatspi  # noqa: F401
            except Exception as exc:
                self._failure_reason = f"AT-SPI unavailable: {exc}"
                return False
            return True
        if self.platform == "Darwin":
            try:
                import ApplicationServices  # noqa: F401
            except Exception as exc:
                self._failure_reason = f"AX API unavailable: {exc}"
                return False
            return True
        self._failure_reason = f"unsupported platform: {self.platform}"
        return False

    @property
    def failure_reason(self) -> str:
        return self._failure_reason

    # -- public API ---------------------------------------------------------
    def find(self, label: str) -> list[ElementTarget]:
        wanted = _normalise(label)
        if not wanted or not self.available():
            return []
        matches: list[ElementTarget] = []
        for element in self._iter_elements():
            name = _normalise(element.get("name", ""))
            if not name:
                continue
            if wanted in name or name in wanted:
                bounds = element.get("bounds")
                if not bounds:
                    continue
                left, top, width, height = bounds
                matches.append(ElementTarget(
                    label=str(element.get("name") or label)[:120],
                    x=int(left + width / 2),
                    y=int(top + height / 2),
                    confidence=0.95,
                    source="accessibility",
                    bounds=(int(left), int(top), int(width), int(height)),
                    uncertain=False,
                ))
                if len(matches) >= 8:
                    break
        return matches

    def list_elements(self, limit: int = 40) -> list[dict[str, Any]]:
        if not self.available():
            return []
        described: list[dict[str, Any]] = []
        for element in self._iter_elements():
            if len(described) >= limit:
                break
            if not element.get("name"):
                continue
            described.append(element)
        return described

    def active_window(self) -> str:
        try:
            if self.platform == "Windows":
                from pywinauto import Desktop

                window = Desktop(backend="uia").window(active_only=True)
                return str(window.window_text() or "")
            if self.platform == "Linux":
                import pyatspi

                desktop = pyatspi.Registry.getDesktop(0)
                for application in desktop:
                    for window in application:
                        try:
                            if window.getState().contains(pyatspi.STATE_ACTIVE):
                                return str(window.name or "")
                        except Exception:
                            continue
            if self.platform == "Darwin":
                from AppKit import NSWorkspace

                return str(NSWorkspace.sharedWorkspace().activeApplication().get(
                    "NSApplicationName", ""
                ))
        except Exception:
            return ""
        return ""

    # -- platform iterators -------------------------------------------------
    def _iter_elements(self) -> Iterable[dict[str, Any]]:
        try:
            if self.platform == "Windows":
                yield from self._windows_elements()
            elif self.platform == "Linux":
                yield from self._linux_elements()
            elif self.platform == "Darwin":
                yield from self._mac_elements()
        except Exception:
            return

    def _windows_elements(self) -> Iterable[dict[str, Any]]:
        from pywinauto import Desktop

        count = 0
        for window in Desktop(backend="uia").windows():
            try:
                rect = window.rectangle()
                yield {
                    "name": str(window.window_text() or ""),
                    "role": "window",
                    "bounds": (rect.left, rect.top, rect.width(), rect.height()),
                }
                count += 1
                for control in window.descendants():
                    if count >= self.limit:
                        return
                    name = ""
                    try:
                        name = str(control.window_text() or control.element_info.name or "")
                    except Exception:
                        name = ""
                    if not name:
                        continue
                    try:
                        box = control.rectangle()
                    except Exception:
                        continue
                    if box.width() <= 0 or box.height() <= 0:
                        continue
                    yield {
                        "name": name,
                        "role": str(getattr(control.element_info, "control_type", "") or ""),
                        "bounds": (box.left, box.top, box.width(), box.height()),
                    }
                    count += 1
            except Exception:
                continue

    def _linux_elements(self) -> Iterable[dict[str, Any]]:
        import pyatspi

        count = 0
        desktop = pyatspi.Registry.getDesktop(0)
        for application in desktop:
            for window in application:
                stack = [window]
                while stack and count < self.limit:
                    node = stack.pop()
                    try:
                        name = str(node.name or "")
                        role = str(node.getRoleName() or "")
                        if name:
                            extents = node.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
                            if extents.width > 0 and extents.height > 0:
                                yield {
                                    "name": name,
                                    "role": role,
                                    "bounds": (extents.x, extents.y,
                                               extents.width, extents.height),
                                }
                                count += 1
                        for index in range(node.childCount):
                            stack.append(node.getChildAtIndex(index))
                    except Exception:
                        continue

    def _mac_elements(self) -> Iterable[dict[str, Any]]:
        """Walk the frontmost app's AX tree.

        Requires the caller (JARVIS) to hold the macOS Accessibility permission;
        without it every attribute read fails and this yields nothing, which the
        caller treats as "no accessibility support" rather than an error. Sizes
        and positions come from real AXValue structs — nothing is fabricated.
        """
        from AppKit import NSWorkspace
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            kAXChildrenAttribute,
            kAXPositionAttribute,
            kAXSizeAttribute,
            kAXTitleAttribute,
        )
        from Quartz import (  # type: ignore
            AXValueGetValue,
            kAXValueCGPointType,
            kAXValueCGSizeType,
        )

        application = NSWorkspace.sharedWorkspace().frontmostApplication()
        if application is None:
            return
        root = AXUIElementCreateApplication(application.processIdentifier())

        def attribute(element, name):
            try:
                value, error = AXUIElementCopyAttributeValue(element, name, None)
                return value if error == 0 else None
            except Exception:
                return None

        stack = [root]
        count = 0
        while stack and count < self.limit:
            node = stack.pop()
            try:
                title = attribute(node, kAXTitleAttribute)
                position_value = attribute(node, kAXPositionAttribute)
                size_value = attribute(node, kAXSizeAttribute)
                if title and position_value is not None and size_value is not None:
                    ok_point, point = AXValueGetValue(position_value, kAXValueCGPointType, None)
                    ok_size, size = AXValueGetValue(size_value, kAXValueCGSizeType, None)
                    if ok_point and ok_size and size.width > 0 and size.height > 0:
                        yield {
                            "name": str(title),
                            "role": "ax",
                            "bounds": (int(point.x), int(point.y),
                                       int(size.width), int(size.height)),
                        }
                        count += 1
            except Exception:
                pass
            children = attribute(node, kAXChildrenAttribute)
            if children:
                stack.extend(list(children))
