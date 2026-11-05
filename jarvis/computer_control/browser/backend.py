"""Browser backend protocol and selection."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional, Protocol


class BrowserError(RuntimeError):
    """A browser operation failed or was refused (message is speakable)."""


@dataclass
class PageInfo:
    url: str
    title: str
    tab: int = 0
    tabs: list = field(default_factory=list)       # [{"index", "url", "title", "active"}]

    def as_dict(self) -> dict:
        return {"url": self.url, "title": self.title, "tab": self.tab, "tabs": list(self.tabs)}


class BrowserBackend(Protocol):  # pragma: no cover - structural
    name: str

    def available(self) -> tuple[bool, str]: ...
    def is_open(self) -> bool: ...
    def open(self) -> PageInfo: ...
    def close(self) -> None: ...
    def page(self) -> PageInfo: ...
    def goto(self, url: str, timeout_s: float) -> PageInfo: ...
    def back(self) -> PageInfo: ...
    def new_tab(self, url: str) -> PageInfo: ...
    def switch_tab(self, index: int) -> PageInfo: ...
    def close_tab(self, index: int) -> PageInfo: ...
    def snapshot(self) -> dict: ...                 # page_snapshot format: {title, url, total, rows}
    def element(self, ref: str) -> Optional[dict]: ...   # live state of a ref, None when gone
    def click(self, ref: str) -> None: ...
    def fill(self, ref: str, text: str) -> None: ...
    def select(self, ref: str, value: str) -> None: ...
    def press(self, key: str, ref: str = "") -> None: ...
    def text(self, limit: int) -> str: ...
    def wait_text(self, text: str, timeout_s: float) -> bool: ...
    def screenshot(self, path: str) -> str: ...      # password fields masked
    def download(self, ref: str, folder: str, timeout_s: float) -> str: ...
    def upload(self, ref: str, path: str) -> None: ...


_lock = threading.Lock()
_backend: Optional[BrowserBackend] = None


def get_backend() -> BrowserBackend:
    global _backend
    with _lock:
        if _backend is None:
            from jarvis.computer_control.browser.playwright_backend import PlaywrightBackend
            _backend = PlaywrightBackend()
        return _backend


def set_backend(backend: Optional[BrowserBackend]) -> None:
    global _backend
    with _lock:
        old, _backend = _backend, backend
    if old is not None and old is not backend:
        try:
            old.close()
        except Exception:
            from jarvis.core import failsoft
            failsoft.suppress("computer_control.browser.backend:set_backend")
