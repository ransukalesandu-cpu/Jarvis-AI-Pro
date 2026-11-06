"""The backend protocol behind the Windows controller, and backend selection.

The controller never touches pywinauto directly; it talks to a backend:

* :class:`uia.PywinautoBackend` on Windows (UI Automation, Win32 for geometry);
* :class:`fake.FakeDesktop` in tests;
* :class:`UnavailableBackend` everywhere else — every call raises
  :class:`BackendUnavailable` with a sentence JARVIS can say.
"""
from __future__ import annotations

import platform
import threading
from typing import Optional, Protocol

from jarvis.computer_control.windows.model import AppInfo, ElementInfo, ProcessInfo, WindowInfo


class BackendError(RuntimeError):
    """A backend refused or failed an operation (message is speakable)."""


class BackendUnavailable(BackendError):
    pass


class ElementGone(BackendError):
    """The control referenced no longer exists (window closed or UI changed)."""


class WindowsBackend(Protocol):  # pragma: no cover - structural
    name: str

    def available(self) -> tuple[bool, str]: ...
    def installed_apps(self) -> list[AppInfo]: ...
    def processes(self) -> list[ProcessInfo]: ...
    def launch(self, target: str, args: list[str]) -> int: ...
    def terminate(self, pid: int, force: bool = False) -> bool: ...
    def windows(self) -> list[WindowInfo]: ...
    def activate(self, handle: int) -> None: ...
    def set_window_state(self, handle: int, state: str) -> None: ...
    def move_resize(self, handle: int, left: int, top: int, width: int, height: int) -> None: ...
    def close_window(self, handle: int) -> None: ...
    def elements(self, handle: int, depth: Optional[int] = 6, limit: int = 400,
                 strict: bool = False) -> list[ElementInfo]: ...
    # depth=None walks the whole tree; strict=True raises BackendError instead of
    # silently dropping an unreadable control or truncating at ``limit`` (used by
    # the password-mask scan, which must not mistake an incomplete scan for 'none').
    def click(self, ref: str) -> None: ...
    def invoke(self, ref: str) -> None: ...
    def set_text(self, ref: str, text: str) -> None: ...
    def get_value(self, ref: str) -> Optional[str]: ...
    def select(self, ref: str, item: str) -> None: ...
    def toggle(self, ref: str) -> str: ...
    def menu_select(self, handle: int, path: str) -> None: ...
    def send_text(self, handle: int, text: str) -> None: ...
    def send_hotkey(self, handle: int, keys: list[str]) -> None: ...
    def screen_size(self) -> tuple[int, int]: ...


class UnavailableBackend:
    name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def available(self) -> tuple[bool, str]:
        return False, self.reason

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)

        def refuse(*_a, **_k):
            raise BackendUnavailable(self.reason)
        return refuse


_lock = threading.Lock()
_backend: Optional[WindowsBackend] = None


def _default_backend() -> WindowsBackend:
    if platform.system() != "Windows":
        return UnavailableBackend("Windows native control only works on Windows; this computer runs "
                                  f"{platform.system() or 'an unknown OS'}.")
    try:
        from jarvis.computer_control.windows.uia import PywinautoBackend
        backend = PywinautoBackend()
    except Exception as exc:
        return UnavailableBackend(f"Windows UI Automation is unavailable: {type(exc).__name__}: {exc}")
    ok, reason = backend.available()
    return backend if ok else UnavailableBackend(reason)


def get_backend() -> WindowsBackend:
    global _backend
    with _lock:
        if _backend is None:
            _backend = _default_backend()
        return _backend


def set_backend(backend: Optional[WindowsBackend]) -> None:
    """Inject a backend (tests use :class:`fake.FakeDesktop`); ``None`` re-detects."""
    global _backend
    with _lock:
        _backend = backend
