"""Plain data the Windows controller passes around (no pywinauto objects leak out)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def as_ltwh(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


@dataclass(frozen=True)
class AppInfo:
    name: str                 # display name ("Notepad")
    target: str               # what launch() takes: an exe path, a command or a shortcut
    source: str = ""          # "start_menu" | "app_paths" | "alias" | "path" | "fake"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    exe: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    pid: int
    process_name: str = ""
    class_name: str = ""
    rect: Optional[Rect] = None
    visible: bool = True
    enabled: bool = True
    minimized: bool = False
    maximized: bool = False
    active: bool = False

    def as_dict(self) -> dict:
        data = asdict(self)
        data["rect"] = self.rect.as_ltwh() if self.rect else None
        return data


@dataclass(frozen=True)
class ElementInfo:
    ref: str                       # stable within one window snapshot: "<handle>:<path>"
    name: str
    control_type: str              # UIA control type ("Button", "Edit", "MenuItem", ...)
    automation_id: str = ""
    class_name: str = ""
    rect: Optional[Rect] = None
    enabled: bool = True
    visible: bool = True
    is_password: bool = False
    value: Optional[str] = None    # never filled for password fields
    focusable: bool = False
    children: int = 0
    window_handle: int = 0

    def as_dict(self) -> dict:
        data = asdict(self)
        data["rect"] = self.rect.as_ltwh() if self.rect else None
        if self.is_password:
            data["value"] = None
        return data

    def short(self) -> str:
        label = self.name or self.automation_id or self.class_name or "(unnamed)"
        flags = "" if self.enabled else " [disabled]"
        return f"{self.control_type} '{label}'{flags} ref={self.ref}"


@dataclass
class ElementQuery:
    """How to find a control. All given fields must match (case-insensitive)."""

    name: str = ""
    name_contains: str = ""
    automation_id: str = ""
    control_type: str = ""
    class_name: str = ""
    ref: str = ""
    index: Optional[int] = None       # pick the n-th match when several match
    include_disabled: bool = False

    @classmethod
    def from_params(cls, params: dict) -> "ElementQuery":
        q = cls(
            name=str(params.get("name") or params.get("target") or "").strip(),
            name_contains=str(params.get("name_contains") or "").strip(),
            automation_id=str(params.get("automation_id") or "").strip(),
            control_type=str(params.get("control_type") or "").strip(),
            class_name=str(params.get("class_name") or "").strip(),
            ref=str(params.get("ref") or "").strip(),
            include_disabled=bool(params.get("include_disabled", False)),
        )
        if params.get("index") not in (None, ""):
            try:
                q.index = int(params["index"])
            except (TypeError, ValueError):
                q.index = None
        return q

    def empty(self) -> bool:
        return not any((self.name, self.name_contains, self.automation_id, self.control_type,
                        self.class_name, self.ref))

    def matches(self, el: ElementInfo) -> bool:
        if self.ref:
            return el.ref == self.ref
        if not self.include_disabled and not el.enabled:
            return False
        if self.name and el.name.casefold() != self.name.casefold():
            return False
        if self.name_contains and self.name_contains.casefold() not in el.name.casefold():
            return False
        if self.automation_id and el.automation_id.casefold() != self.automation_id.casefold():
            return False
        if self.control_type and el.control_type.casefold() != self.control_type.casefold():
            return False
        if self.class_name and el.class_name.casefold() != self.class_name.casefold():
            return False
        return True

    def describe(self) -> str:
        parts = [f"{k}={v!r}" for k, v in (("name", self.name), ("name_contains", self.name_contains),
                                          ("automation_id", self.automation_id),
                                          ("control_type", self.control_type),
                                          ("class_name", self.class_name), ("ref", self.ref)) if v]
        return ", ".join(parts) or "(any control)"


@dataclass
class WindowQuery:
    title: str = ""
    title_contains: str = ""
    process_name: str = ""
    pid: Optional[int] = None
    handle: Optional[int] = None
    active: bool = False

    @classmethod
    def from_params(cls, params: dict) -> "WindowQuery":
        def as_int(value):
            try:
                return int(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                return None
        return cls(title=str(params.get("window_title") or params.get("title") or "").strip(),
                   title_contains=str(params.get("window") or params.get("title_contains") or "").strip(),
                   process_name=str(params.get("process") or params.get("process_name") or "").strip(),
                   pid=as_int(params.get("pid")), handle=as_int(params.get("handle")),
                   active=bool(params.get("active", False)))

    def empty(self) -> bool:
        return not any((self.title, self.title_contains, self.process_name, self.pid, self.handle,
                        self.active))

    def matches(self, w: WindowInfo) -> bool:
        if self.handle is not None and w.handle != self.handle:
            return False
        if self.pid is not None and w.pid != self.pid:
            return False
        if self.title and w.title.casefold() != self.title.casefold():
            return False
        if self.title_contains and self.title_contains.casefold() not in w.title.casefold():
            return False
        if self.process_name:
            want = self.process_name.casefold().removesuffix(".exe")
            if w.process_name.casefold().removesuffix(".exe") != want:
                return False
        if self.active and not w.active:
            return False
        return True

    def describe(self) -> str:
        parts = [f"{k}={v!r}" for k, v in (("title", self.title), ("window", self.title_contains),
                                          ("process", self.process_name), ("pid", self.pid),
                                          ("handle", self.handle)) if v not in ("", None)]
        if self.active:
            parts.append("active")
        return ", ".join(parts) or "(any window)"


@dataclass
class Snapshot:
    windows: list[WindowInfo] = field(default_factory=list)
