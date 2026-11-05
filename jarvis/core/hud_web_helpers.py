"""Pure URL and publisher-page helpers used by the HUD workspace (no Qt)."""
from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler

_NEWS_PUBLISHER_HOSTS = {
    "english.newsfirst.lk", "sinhala.newsfirst.lk", "newsfirst.lk", "www.newsfirst.lk",
    "adaderana.lk", "www.adaderana.lk", "sinhala.adaderana.lk",
}


class _OpenGraphImageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.image_url = ""
        self.fallback_images: list[tuple[int, str]] = []

    def handle_starttag(self, tag, attrs):
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag.lower() == "meta" and not self.image_url:
            field = (values.get("property") or values.get("name") or "").lower()
            if field in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
                self.image_url = values.get("content", "").strip()
        elif tag.lower() == "img":
            # Publisher pages often lazy-load their lead photo, while their
            # social metadata is absent or points to a generic site logo.
            alt = (values.get("alt") or values.get("title") or "").lower()
            classes = (values.get("class") or "").lower()
            try:
                width = int(values.get("width") or 0)
            except ValueError:
                width = 0
            score = 2 * bool(any(word in f"{alt} {classes}" for word in ("news", "story", "article", "headline", "lead")))
            score += 2 if width >= 300 else 0
            for key in ("data-src", "data-lazy-src", "data-original", "src"):
                candidate = values.get(key, "").strip()
                if candidate:
                    if any(word in candidate.lower() for word in ("logo", "icon", "avatar", "banner")):
                        score -= 5
                    self.fallback_images.append((score, candidate))
                    break
            srcset = values.get("data-srcset") or values.get("srcset") or ""
            if srcset:
                candidate = srcset.split(",", 1)[0].strip().split(" ", 1)[0]
                if candidate:
                    self.fallback_images.append((score, candidate))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def _is_public_https_url(url: str) -> bool:
    """Reject credentials, non-HTTPS URLs, and hosts resolving to private IPs."""
    try:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443)):
            return False
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(record[4][0]).is_global for record in addresses
        )
    except (OSError, ValueError):
        return False


class _PublicHttpsRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_public_https_url(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _valid_http_url(value: str) -> bool:
    try:
        return urlparse(value).scheme.lower() in {"http", "https"}
    except Exception:
        return False


def _youtube_id(value: str) -> str | None:
    try:
        u = urlparse(value)
        if u.hostname and u.hostname.lower().endswith("youtu.be"):
            candidate = u.path.strip("/").split("/")[0]
        elif u.hostname and "youtube.com" in u.hostname.lower():
            candidate = parse_qs(u.query).get("v", [""])[0]
            if not candidate:
                bits = [b for b in u.path.split("/") if b]
                candidate = bits[1] if len(bits) > 1 and bits[0] in {"embed", "shorts", "live"} else ""
        else:
            return None
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else None
    except Exception:
        return None
