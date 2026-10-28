"""Visible, bounded Playwright browser tools for JARVIS.

Only explicit, allow-listed operations are exposed. This module never submits
forms or performs purchases, sends messages, downloads files, or runs page code.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import quote_plus, urlparse, urljoin


class BrowserAutomationError(RuntimeError):
    pass


def validate_public_url(url: str) -> str:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrowserAutomationError("Only absolute http/https URLs are allowed.")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise BrowserAutomationError("Local or internal destinations are blocked.")
    if parsed.username or parsed.password:
        raise BrowserAutomationError("URLs containing embedded credentials are blocked.")
    try:
        addresses = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError) as exc:
        raise BrowserAutomationError("Destination host could not be resolved.") from exc
    if not addresses:
        raise BrowserAutomationError("Destination host resolved to no addresses.")
    for info in addresses:
        try:
            address = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        except (ValueError, IndexError, TypeError) as exc:
            raise BrowserAutomationError("Destination host resolved to an invalid address.") from exc
        if not address.is_global:
            raise BrowserAutomationError("Private or non-public IP destinations are blocked.")
    return raw


class BrowserAutomation:
    """Manage one visible Chromium session. Requires Playwright and its browser binary."""

    def __init__(self, *, timeout_ms: int = 15000):
        self.timeout_ms = max(1000, min(int(timeout_ms), 30000))
        self._playwright = None
        self._browser = None
        self._page = None

    def open(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserAutomationError(
                "Playwright is not installed. Install project requirements and run "
                "'python -m playwright install chromium'."
            ) from exc
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=False)
            context = self._browser.new_context(accept_downloads=False)
            context.set_default_timeout(self.timeout_ms)
            context.route("**/*", self._guard_request)
            self._page = context.new_page()
        except Exception:
            self.close()
            raise

    @staticmethod
    def _guard_request(route) -> None:
        try:
            validate_public_url(route.request.url)
        except BrowserAutomationError:
            route.abort()
        else:
            route.continue_()

    def navigate(self, url: str) -> dict[str, str]:
        target = validate_public_url(url)
        self.open()
        self._page.goto(target, wait_until="domcontentloaded", timeout=self.timeout_ms)
        return self.read_page()

    def search_web(self, query: str) -> dict[str, str]:
        query = str(query or "").strip()
        if not query:
            raise ValueError("Search query cannot be empty.")
        return self.navigate("https://www.google.com/search?q=" + quote_plus(query[:500]))

    def click_link(self, visible_text: str) -> dict[str, str]:
        self.open()
        label = str(visible_text or "").strip()
        if not label or len(label) > 200:
            raise ValueError("Provide link text between 1 and 200 characters.")
        # Resolve links only, rather than arbitrary buttons or form controls.
        # Navigate the validated href directly so onclick handlers cannot turn a
        # request to follow a link into a form submission or another side effect.
        href = self._page.get_by_role("link", name=label, exact=False).first.get_attribute("href")
        if not href:
            raise BrowserAutomationError("The selected link has no navigation target.")
        return self.navigate(urljoin(self._page.url, href))

    def read_page(self) -> dict[str, str]:
        self.open()
        title = self._page.title()[:300]
        url = self._page.url[:2000]
        text = re.sub(r"\n{3,}", "\n\n", self._page.locator("body").inner_text()[:12000])
        return {"title": title, "url": url, "text": text}

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._page = self._browser = self._playwright = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_exc):
        self.close()
