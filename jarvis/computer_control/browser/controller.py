"""The Browser Controller: navigation, tabs, page reading, forms, downloads — verified.

Rules (master prompt, Project 3 security):

* only ``http``/``https``; local, private-network and credential-bearing URLs are
  refused unless the owner approved that destination (the policy makes them HIGH);
* everything read from a page (text, element names) is untrusted content: it
  is fenced, hidden instructions stripped, and never treated as a command;
* passwords and cookies never leave the browser: password values are never
  read, fields typed into are redacted in every log, screenshots mask password
  inputs, cookies are never read at all;
* form submissions, uploads and purchase/send/account buttons are HIGH
  (owner approval through the native prompt) — decided from the real element
  the ref points at, not from what the plan says;
* every action reports what changed (URL, title, field value, file on disk).
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlparse

from jarvis.computer_control.browser.backend import BrowserBackend, BrowserError, get_backend
from jarvis.computer_control.runner import ActionContext, ActionOutcome
from jarvis.computer_control.untrusted import wrap

SEARCH_URLS = {"google": "https://www.google.com/search?q=", "bing": "https://www.bing.com/search?q=",
               "duckduckgo": "https://duckduckgo.com/?q="}
_SENSITIVE_FIELD = re.compile(r"\b(card|cvv|cvc|security code|expir|iban|account number|routing|ssn|"
                              r"social security|passport|pin|otp|one-time|password|passcode)\b", re.I)
_SIGNED_IN = re.compile(r"\b(sign out|log out|logout|signout|my account)\b", re.I)


def private_destination(url: str) -> str:
    """Why ``url`` is not a public web address ('' when it is)."""
    try:
        from jarvis.core.browser_automation import BrowserAutomationError, validate_public_url
    except Exception:
        return "the address could not be checked"
    try:
        validate_public_url(url)
        return ""
    except BrowserAutomationError as exc:
        return str(exc)


def _fail(message: str, **data) -> ActionOutcome:
    return ActionOutcome(False, message, data=data, verified=False)


class BrowserController:
    def __init__(self, backend: BrowserBackend | None = None, *, downloads: str | None = None) -> None:
        self._backend = backend
        self._downloads = downloads
        self._rows: dict[str, dict] = {}      # ref -> row of the latest snapshot
        self._snap_url = ""
        self._lock = threading.Lock()

    @property
    def backend(self) -> BrowserBackend:
        return self._backend or get_backend()

    def downloads_dir(self) -> str:
        if self._downloads:
            return self._downloads
        return str(Path.home() / "Downloads" / "JARVIS")

    def _guard(self, fn) -> ActionOutcome:
        try:
            return fn()
        except BrowserError as exc:
            return _fail(str(exc))

    # ── info used by the policy enrichment ───────────────────────────────
    def row(self, ref: str) -> Optional[dict]:
        with self._lock:
            return dict(self._rows.get(str(ref).strip().lower().strip("[]"), {})) or None

    def page_has_sensitive_fields(self) -> bool:
        with self._lock:
            return any(r.get("secret") or _SENSITIVE_FIELD.search(r.get("name", ""))
                       for r in self._rows.values() if r.get("role") in ("textbox", "searchbox", "combobox"))

    # ── navigation ───────────────────────────────────────────────────────
    def open(self, ctx: ActionContext, browser: str = "") -> ActionOutcome:
        def run():
            prefer = getattr(self.backend, "prefer", None)
            if browser and callable(prefer):
                prefer(browser)
            ok, reason = self.backend.available()
            if not ok:
                return _fail(reason)
            page = self.backend.open()
            return ActionOutcome(True, f"The browser is open ({getattr(self.backend, 'channel', '') or 'ready'}).",
                                 data={"page": page.as_dict()}, verified=True, evidence="browser responded")
        return self._guard(run)

    def navigate(self, ctx: ActionContext, url: str, *, allow_private: bool = False) -> ActionOutcome:
        def run():
            target = str(url or "").strip()
            if target and "://" not in target and re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", target, re.I):
                target = "https://" + target
            parsed = urlparse(target)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return _fail("Only http(s) web addresses can be opened.")
            why = private_destination(target)
            if why and not allow_private:
                return _fail(f"Not opened: {why}")
            ctx.check()
            allow = getattr(self.backend, "allow_private_once", None)
            if callable(allow):
                allow(bool(allow_private))
            try:
                page = self.backend.goto(target, 20.0)
            finally:
                if callable(allow):
                    allow(False)
            self._forget()
            landed = urlparse(page.url)
            same_site = landed.hostname and parsed.hostname and (
                landed.hostname == parsed.hostname or landed.hostname.endswith("." + parsed.hostname)
                or parsed.hostname.endswith("." + landed.hostname))
            if not allow_private and private_destination(page.url):
                self.backend.goto("about:blank", 5.0)
                return _fail("The page redirected to a private or local address, so it was closed.")
            return ActionOutcome(True, f"Opened '{page.title or page.url}'.", data={"page": page.as_dict()},
                                 verified=bool(same_site),
                                 evidence=f"now at {landed.hostname}" if same_site else
                                 f"redirected to {landed.hostname}")
        return self._guard(run)

    def search(self, ctx: ActionContext, query: str, engine: str = "") -> ActionOutcome:
        query = " ".join(str(query or "").split())[:500]
        if not query:
            return _fail("Say what to search for.")
        base = SEARCH_URLS.get(str(engine or "").lower(), SEARCH_URLS["google"])
        result = self.navigate(ctx, base + quote_plus(query))
        if result.ok:
            result.message = f"Searched for '{query}'. " + result.message
        return result

    def back(self, ctx: ActionContext) -> ActionOutcome:
        def run():
            before = self.backend.page().url
            page = self.backend.back()
            self._forget()
            return ActionOutcome(True, f"Went back to '{page.title or page.url}'.", data={"page": page.as_dict()},
                                 verified=page.url != before, evidence="URL changed" if page.url != before
                                 else "URL unchanged")
        return self._guard(run)

    def tabs(self, ctx: ActionContext) -> ActionOutcome:
        def run():
            page = self.backend.page()
            lines = "; ".join(f"{t['index']}: {t['title'] or t['url']}{' (active)' if t['active'] else ''}"
                              for t in page.tabs)
            return ActionOutcome(True, f"{len(page.tabs)} tab(s): {lines}", data={"page": page.as_dict()},
                                 verified=True)
        return self._guard(run)

    def new_tab(self, ctx: ActionContext, url: str = "") -> ActionOutcome:
        def run():
            if url:
                why = private_destination(url)
                if why:
                    return _fail(f"Not opened: {why}")
            page = self.backend.new_tab(url)
            self._forget()
            return ActionOutcome(True, f"Opened a new tab ({len(page.tabs)} open).", data={"page": page.as_dict()},
                                 verified=True)
        return self._guard(run)

    def switch_tab(self, ctx: ActionContext, index: int) -> ActionOutcome:
        def run():
            page = self.backend.switch_tab(int(index))
            self._forget()
            return ActionOutcome(True, f"Switched to tab {index}: '{page.title or page.url}'.",
                                 data={"page": page.as_dict()}, verified=page.tab == int(index))
        return self._guard(run)

    def close_tab(self, ctx: ActionContext, index: int) -> ActionOutcome:
        def run():
            before = len(self.backend.page().tabs)
            page = self.backend.close_tab(int(index))
            self._forget()
            return ActionOutcome(True, f"Closed tab {index}.", data={"page": page.as_dict()},
                                 verified=len(page.tabs) < before or before == 1)
        return self._guard(run)

    def close(self, ctx: ActionContext) -> ActionOutcome:
        def run():
            self.backend.close()
            self._forget()
            return ActionOutcome(True, "Closed the browser.", verified=not self.backend.is_open())
        return self._guard(run)

    # ── reading ──────────────────────────────────────────────────────────
    def _forget(self) -> None:
        with self._lock:
            self._rows, self._snap_url = {}, ""

    def snapshot(self, ctx: ActionContext) -> ActionOutcome:
        def run():
            from jarvis.core.page_snapshot import format_snapshot
            data = self.backend.snapshot()
            with self._lock:
                self._rows = {r["ref"]: r for r in data.get("rows", [])}
                self._snap_url = data.get("url", "")
            content = wrap(format_snapshot(data), "web_page")
            rows = [{k: v for k, v in r.items() if k != "value" or not r.get("secret")} for r in data.get("rows", [])]
            return ActionOutcome(True, content.for_model(4000),
                                 data={"url": data.get("url"), "title": data.get("title"), "elements": rows[:150],
                                       "injection_flags": list(content.flags)},
                                 verified=True, evidence="read from the live page")
        return self._guard(run)

    def read(self, ctx: ActionContext, limit: int = 6000) -> ActionOutcome:
        def run():
            page = self.backend.page()
            content = wrap(self.backend.text(max(200, min(int(limit), 20000))), "web_page")
            return ActionOutcome(True, content.for_model(int(limit)),
                                 data={"url": page.url, "title": page.title, "chars": len(content.text),
                                       "injection_flags": list(content.flags)},
                                 verified=True, evidence="read from the live page")
        return self._guard(run)

    def state(self, ctx: ActionContext) -> ActionOutcome:
        """Where the browser is and whether this site looks signed in (login-state awareness)."""
        def run():
            if not self.backend.is_open():
                return ActionOutcome(True, "The browser is not open.", data={"open": False}, verified=True)
            page = self.backend.page()
            data = self.backend.snapshot()
            rows = data.get("rows", [])
            login_form = any(r.get("secret") for r in rows)
            signed_in = any(_SIGNED_IN.search(r.get("name", "")) for r in rows)
            login = "login form shown" if login_form else ("signed in" if signed_in else "unknown")
            return ActionOutcome(True, f"At '{page.title or page.url}' ({len(page.tabs)} tab(s)); login: {login}.",
                                 data={"open": True, "page": page.as_dict(), "login": login}, verified=True)
        return self._guard(run)

    def wait_text(self, ctx: ActionContext, text: str, timeout: float = 10.0) -> ActionOutcome:
        def run():
            deadline = max(1.0, min(float(timeout), 60.0))
            waited = 0.0
            while waited < deadline:
                ctx.check()
                if self.backend.wait_text(str(text), min(2.0, deadline - waited)):
                    return ActionOutcome(True, f"'{text}' is on the page.", verified=True, evidence="text present")
                waited += 2.0
                ctx.wait(0.05)
            return _fail(f"'{text}' did not appear within {deadline:.0f}s.")
        return self._guard(run)

    # ── interaction ──────────────────────────────────────────────────────
    def _ref(self, ref: str) -> str:
        ref = str(ref or "").strip().lower().strip("[]")
        if not re.match(r"^e[1-9][0-9]{0,3}$", ref):
            raise BrowserError("Give a ref like e12 from the latest snapshot.")
        with self._lock:
            if not self._rows:
                raise BrowserError("Take a snapshot first (op='snapshot').")
            if ref not in self._rows:
                raise BrowserError(f"{ref} is not in the latest snapshot.")
        if self.backend.page().url != self._snap_url:
            raise BrowserError("The page changed since the snapshot. Take a new snapshot.")
        return ref

    def _expect(self, ctx: ActionContext, params: dict, before_url: str) -> tuple[Optional[bool], str]:
        want_url = str(params.get("expect_url") or "").strip()
        want_text = str(params.get("expect_text") or "").strip()
        page = self.backend.page()
        if want_url:
            ok = want_url.casefold() in page.url.casefold()
            return ok, f"URL is {page.url}"
        if want_text:
            ok = self.backend.wait_text(want_text, 5.0)
            return ok, f"'{want_text}' {'is' if ok else 'is not'} on the page"
        if page.url != before_url:
            return None, f"URL changed to {page.url}"
        return None, "no expected result was given, so the effect was not checked"

    def click(self, ctx: ActionContext, ref: str, params: dict | None = None) -> ActionOutcome:
        def run():
            r = self._ref(ref)
            state = self.backend.element(r)
            if state is None:
                return _fail(f"{r} is gone — take a new snapshot.")
            if state.get("disabled"):
                return _fail(f"'{state.get('name') or r}' is disabled.")
            before = self.backend.page().url
            ctx.check()
            self.backend.click(r)
            if self.backend.page().url != before:
                self._forget()
            verified, evidence = self._expect(ctx, params or {}, before)
            return ActionOutcome(True, f"Clicked '{state.get('name') or r}'. {evidence}.",
                                 data={"page": self.backend.page().as_dict()}, verified=verified, evidence=evidence)
        return self._guard(run)

    def fill(self, ctx: ActionContext, ref: str, text: str) -> ActionOutcome:
        def run():
            r = self._ref(ref)
            state = self.backend.element(r) or {}
            if state.get("secret") or (self.row(r) or {}).get("secret"):
                ctx.params["is_password"] = True
            if state.get("disabled"):
                return _fail(f"'{state.get('name') or r}' is disabled.")
            ctx.check()
            self.backend.fill(r, str(text))
            if ctx.params.get("is_password"):
                return ActionOutcome(True, "Entered the password (not read back).", verified=None,
                                     evidence="password fields are never read back")
            after = (self.backend.element(r) or {}).get("value")
            ok = after == str(text)
            return ActionOutcome(True, f"Typed into '{state.get('name') or r}'.", verified=ok,
                                 evidence="the field holds the typed text" if ok else "the field differs")
        return self._guard(run)

    def select(self, ctx: ActionContext, ref: str, value: str) -> ActionOutcome:
        def run():
            r = self._ref(ref)
            self.backend.select(r, str(value))
            after = (self.backend.element(r) or {}).get("value")
            return ActionOutcome(True, f"Selected '{value}'.", verified=after == str(value),
                                 evidence=f"value is {after!r}")
        return self._guard(run)

    def press(self, ctx: ActionContext, key: str, ref: str = "", params: dict | None = None) -> ActionOutcome:
        def run():
            key_s = str(key or "").strip()
            if not re.match(r"^[A-Za-z0-9+]{1,30}$", key_s):
                return _fail("Give a key like Enter, Tab or Control+A.")
            r = self._ref(ref) if ref else ""
            before = self.backend.page().url
            self.backend.press(key_s, r)
            if self.backend.page().url != before:
                self._forget()
            verified, evidence = self._expect(ctx, params or {}, before)
            return ActionOutcome(True, f"Pressed {key_s}. {evidence}.", verified=verified, evidence=evidence)
        return self._guard(run)

    def screenshot(self, ctx: ActionContext) -> ActionOutcome:
        def run():
            from jarvis.core.user_data import user_data_dir
            folder = user_data_dir() / "cc-screenshots"
            folder.mkdir(parents=True, exist_ok=True)
            import time as _t
            path = str(folder / f"browser-{int(_t.time())}.png")
            self.backend.screenshot(path)
            ok = os.path.isfile(path) and os.path.getsize(path) > 0
            return ActionOutcome(ok, f"Saved a screenshot (password fields masked) to {path}.",
                                 data={"path": path}, verified=ok, evidence="file written" if ok else "no file")
        return self._guard(run)

    def download(self, ctx: ActionContext, ref: str) -> ActionOutcome:
        def run():
            r = self._ref(ref)
            path = self.backend.download(r, self.downloads_dir(), 60.0)
            ok = os.path.isfile(path) and os.path.getsize(path) > 0
            return ActionOutcome(ok, f"Downloaded {os.path.basename(path)} to {os.path.dirname(path)}.",
                                 data={"path": path, "bytes": os.path.getsize(path) if ok else 0},
                                 verified=ok, evidence="file exists and is not empty" if ok else "no file")
        return self._guard(run)

    def upload(self, ctx: ActionContext, ref: str, path: str) -> ActionOutcome:
        def run():
            r = self._ref(ref)
            if not os.path.isfile(str(path)):
                return _fail(f"There is no file at {path}.")
            self.backend.upload(r, str(path))
            after = (self.backend.element(r) or {}).get("value") or ""
            ok = os.path.basename(str(path)) in after
            return ActionOutcome(True, f"Attached {os.path.basename(str(path))}.", verified=ok or None,
                                 evidence="the field lists the file" if ok else "could not read the field back")
        return self._guard(run)


_controller: Optional[BrowserController] = None


def get_controller() -> BrowserController:
    global _controller
    if _controller is None:
        _controller = BrowserController()
    return _controller


def set_controller(controller: Optional[BrowserController]) -> None:
    global _controller
    _controller = controller
