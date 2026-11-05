"""The real browser backend: Playwright (Apache-2.0) on the installed Edge/Chrome.

* **Installed browser only.** ``launch_persistent_context(channel="msedge")``,
  then ``"chrome"``. No ``playwright install`` download, no bundled Chromium.
  ``JARVIS_BROWSER_CHANNEL`` picks one explicitly.
* **Own profile.** A dedicated JARVIS profile under the user-data folder, so
  sign-ins the owner makes there persist, while the owner's personal browser
  profile, its cookies and saved passwords are never opened.
* **One thread.** Playwright's sync API is bound to the thread that started it,
  so every call is marshalled onto one ``cc-browser`` thread; callers wait with
  a timeout and the runner can still abandon a hung call.
* **Element refs** come from ``core/page_snapshot.SNAPSHOT_JS`` (the same refs
  the existing ``browser_control`` snapshot uses); password values are never read.
* **Screenshots** mask every ``input[type=password]``.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

from jarvis.computer_control.browser.backend import BrowserError, PageInfo
from jarvis.core import failsoft

CHANNELS = ("msedge", "chrome")
_STATE_JS = """
(ref) => {
  const el = document.querySelector('[data-jarvis-ref="' + ref + '"]');
  if (!el) return null;
  const tag = el.tagName.toLowerCase();
  const type = tag === 'input' ? (el.type || 'text').toLowerCase() : '';
  const name = (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('placeholder') || '')
    .replace(/\\s+/g, ' ').trim().slice(0, 80);
  const out = {tag, type, name, disabled: !!el.disabled, secret: type === 'password',
               kind: type === 'file' ? 'file' : (type === 'submit' ? 'submit' : '')};
  if (!out.secret) {
    if (tag === 'select') out.value = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : '';
    else if (tag === 'input' || tag === 'textarea') out.value = el.value;
  }
  return out;
}
"""


def _profile_dir() -> Path:
    from jarvis.core.user_data import user_data_dir
    path = user_data_dir() / "cc-browser-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


class PlaywrightBackend:
    name = "playwright"

    def __init__(self, *, timeout_s: float = 20.0) -> None:
        self.timeout_s = timeout_s
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cc-browser")
        self._pw = None
        self._ctx = None
        self._pages: list = []
        self._active = 0
        self._lock = threading.Lock()
        self.channel = ""

    # ── thread marshalling ───────────────────────────────────────────────
    def _call(self, fn: Callable[[], Any], timeout: Optional[float] = None) -> Any:
        future: Future = self._exec.submit(fn)
        try:
            return future.result(timeout=timeout or self.timeout_s + 10)
        except TimeoutError as exc:
            if future.done():
                raise BrowserError(f"browser call timed out: {exc}") from exc
            raise BrowserError("The browser did not respond in time.") from exc
        except BrowserError:
            raise
        except Exception as exc:
            text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            raise BrowserError(text[:200]) from exc

    def available(self) -> tuple[bool, str]:
        try:
            import playwright.sync_api  # noqa: F401
        except Exception as exc:
            return False, f"Browser control needs the 'playwright' package ({type(exc).__name__})."
        return True, ""

    def is_open(self) -> bool:
        return self._ctx is not None

    def prefer(self, channel: str) -> None:
        """Use this channel ("chrome" / "msedge") the next time the browser starts."""
        channel = str(channel or "").strip().lower()
        if channel in CHANNELS:
            self._preferred = channel

    # ── lifecycle (on the browser thread) ────────────────────────────────
    def _start(self) -> None:
        if self._ctx is not None:
            return
        ok, reason = self.available()
        if not ok:
            raise BrowserError(reason)
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        wanted = getattr(self, "_preferred", "") or os.environ.get("JARVIS_BROWSER_CHANNEL", "").strip().lower()
        channels = (wanted,) if wanted else CHANNELS
        errors = []
        for channel in channels:
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(
                    str(_profile_dir()), channel=channel, headless=False, accept_downloads=True,
                    service_workers="block", viewport=None)
                self.channel = channel
                break
            except Exception as exc:
                errors.append(f"{channel}: {str(exc).splitlines()[0][:120]}")
        if self._ctx is None:
            self._pw.stop()
            self._pw = None
            raise BrowserError("Microsoft Edge or Google Chrome must be installed for browser control "
                               f"({'; '.join(errors)}).")
        self._ctx.set_default_timeout(self.timeout_s * 1000)
        # Every top-level navigation (incl. redirects and link clicks) is checked before
        # it is sent: local / private / credential-bearing destinations are aborted
        # unless the owner approved that navigation (allow_private_once).
        self._ctx.route("**/*", self._guard_route)
        self._pages = list(self._ctx.pages) or [self._ctx.new_page()]
        self._active = 0

    def allow_private_once(self, allowed: bool) -> None:
        self._allow_private = bool(allowed)

    def _guard_route(self, route) -> None:
        try:
            request = route.request
            if request.is_navigation_request() and not getattr(self, "_allow_private", False):
                from jarvis.computer_control.browser.controller import private_destination
                if private_destination(request.url):
                    route.abort("blockedbyclient")
                    return
            route.continue_()
        except Exception:
            failsoft.suppress("computer_control.browser.playwright:guard_route")
            try:
                route.abort("blockedbyclient")
            except Exception:
                failsoft.suppress("computer_control.browser.playwright:guard_route_abort")

    def _page_obj(self):
        self._start()
        self._pages = [p for p in self._pages if not p.is_closed()] or [self._ctx.new_page()]
        self._active = min(self._active, len(self._pages) - 1)
        return self._pages[self._active]

    def _info(self) -> PageInfo:
        page = self._page_obj()
        tabs = []
        for i, p in enumerate(self._pages):
            try:
                title = p.title()
            except Exception:
                title = ""
            tabs.append({"index": i, "url": p.url, "title": title[:120], "active": i == self._active})
        return PageInfo(page.url, page.title()[:300], self._active, tabs)

    def open(self) -> PageInfo:
        return self._call(self._info, timeout=60)

    def close(self) -> None:
        def stop():
            try:
                if self._ctx is not None:
                    self._ctx.close()
            except Exception:
                failsoft.suppress("computer_control.browser.playwright:close-context")
            try:
                if self._pw is not None:
                    self._pw.stop()
            except Exception:
                failsoft.suppress("computer_control.browser.playwright:stop")
            self._ctx = self._pw = None
            self._pages = []
        if self._ctx is not None:
            self._call(stop, timeout=20)

    def page(self) -> PageInfo:
        return self._call(self._info)

    # ── navigation ───────────────────────────────────────────────────────
    def goto(self, url: str, timeout_s: float = 20.0) -> PageInfo:
        def run():
            self._page_obj().goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            return self._info()
        return self._call(run, timeout=timeout_s + 10)

    def back(self) -> PageInfo:
        def run():
            self._page_obj().go_back(wait_until="domcontentloaded")
            return self._info()
        return self._call(run)

    def new_tab(self, url: str = "") -> PageInfo:
        def run():
            self._start()
            page = self._ctx.new_page()
            self._pages.append(page)
            self._active = len(self._pages) - 1
            if url:
                page.goto(url, wait_until="domcontentloaded")
            return self._info()
        return self._call(run)

    def switch_tab(self, index: int) -> PageInfo:
        def run():
            self._page_obj()
            if not 0 <= index < len(self._pages):
                raise BrowserError(f"There is no tab {index}.")
            self._active = index
            self._pages[index].bring_to_front()
            return self._info()
        return self._call(run)

    def close_tab(self, index: int) -> PageInfo:
        def run():
            self._page_obj()
            if not 0 <= index < len(self._pages):
                raise BrowserError(f"There is no tab {index}.")
            self._pages.pop(index).close()
            self._active = max(0, min(self._active, len(self._pages) - 1))
            return self._info()
        return self._call(run)

    # ── content and interaction ──────────────────────────────────────────
    def snapshot(self) -> dict:
        from jarvis.core.page_snapshot import MAX_ELEMENTS, MAX_HREF, MAX_NAME, SNAPSHOT_JS

        def run():
            return self._page_obj().evaluate(SNAPSHOT_JS, [MAX_ELEMENTS, MAX_NAME, MAX_HREF])
        return self._call(run)

    def _locator(self, ref: str):
        page = self._page_obj()
        loc = page.locator(f'[data-jarvis-ref="{ref}"]')
        if loc.count() != 1:
            raise BrowserError(f"{ref} is gone — the page changed. Take a new snapshot.")
        return loc

    def element(self, ref: str) -> Optional[dict]:
        return self._call(lambda: self._page_obj().evaluate(_STATE_JS, ref))

    def click(self, ref: str) -> None:
        self._call(lambda: self._locator(ref).click(timeout=8000))

    def fill(self, ref: str, text: str) -> None:
        self._call(lambda: self._locator(ref).fill(str(text), timeout=8000))

    def select(self, ref: str, value: str) -> None:
        self._call(lambda: self._locator(ref).select_option(label=str(value), timeout=8000))

    def press(self, key: str, ref: str = "") -> None:
        def run():
            if ref:
                self._locator(ref).press(key, timeout=8000)
            else:
                self._page_obj().keyboard.press(key)
        self._call(run)

    def text(self, limit: int = 12000) -> str:
        return self._call(lambda: self._page_obj().locator("body").inner_text()[: int(limit)])

    def wait_text(self, text: str, timeout_s: float = 5.0) -> bool:
        def run():
            try:
                self._page_obj().get_by_text(text, exact=False).first.wait_for(timeout=timeout_s * 1000)
                return True
            except Exception:
                return False
        return bool(self._call(run, timeout=timeout_s + 10))

    def screenshot(self, path: str) -> str:
        def run():
            page = self._page_obj()
            page.screenshot(path=path, mask=[page.locator("input[type=password]")], full_page=False)
            return path
        return self._call(run)

    def download(self, ref: str, folder: str, timeout_s: float = 60.0) -> str:
        def run():
            page = self._page_obj()
            with page.expect_download(timeout=timeout_s * 1000) as info:
                self._locator(ref).click(timeout=8000)
            download = info.value
            Path(folder).mkdir(parents=True, exist_ok=True)
            name = Path(download.suggested_filename).name or "download"
            target = Path(folder) / name
            stem, suffix, n = target.stem, target.suffix, 1
            while target.exists():                 # never overwrite an earlier download
                target = Path(folder) / f"{stem} ({n}){suffix}"
                n += 1
            download.save_as(str(target))
            return str(target)
        return self._call(run, timeout=timeout_s + 15)

    def upload(self, ref: str, path: str) -> None:
        self._call(lambda: self._locator(ref).set_input_files(str(path), timeout=8000))
