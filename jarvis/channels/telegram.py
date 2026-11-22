"""Minimal Telegram Bot API client (long polling, no inbound port, stdlib only).

Only the calls JARVIS needs: getMe, getUpdates, sendMessage, sendDocument and
sendChatAction. ``http`` is injectable so tests never touch the network.
"""
from __future__ import annotations

import json
import mimetypes
import re
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, Optional

API = "https://api.telegram.org"
MAX_MESSAGE = 4000                 # Telegram hard limit is 4096
MAX_DOCUMENT_BYTES = 49 * 1024 * 1024
TOKEN_RE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,64}$")

Http = Callable[[str, Optional[bytes], dict, float], dict]


class TelegramError(RuntimeError):
    pass


def _default_http(url: str, body: Optional[bytes], headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https host
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            raise TelegramError(f"HTTP {e.code}") from None


def split_message(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


class TelegramBot:
    def __init__(self, token: str, *, http: Optional[Http] = None) -> None:
        token = str(token or "").strip()
        if not TOKEN_RE.match(token):
            raise ValueError("that does not look like a Telegram bot token (get one from @BotFather)")
        self._token = token
        self._http = http or _default_http

    def _call(self, method: str, params: Optional[dict] = None, *, timeout: float = 20.0) -> object:
        url = f"{API}/bot{self._token}/{method}"
        body = urllib.parse.urlencode(params or {}).encode("utf-8") if params is not None else None
        headers = {"Content-Type": "application/x-www-form-urlencoded"} if body is not None else {}
        data = self._http(url, body, headers, timeout)
        if not isinstance(data, dict) or not data.get("ok"):
            desc = data.get("description", "unknown error") if isinstance(data, dict) else "bad response"
            raise TelegramError(str(desc))
        return data.get("result")

    def get_me(self) -> dict:
        result = self._call("getMe")
        return result if isinstance(result, dict) else {}

    def get_updates(self, offset: int = 0, timeout: int = 25) -> list[dict]:
        result = self._call("getUpdates", {"offset": offset, "timeout": timeout,
                                           "allowed_updates": json.dumps(["message"])}, timeout=timeout + 10)
        return result if isinstance(result, list) else []

    def send_message(self, chat_id: int, text: str) -> None:
        for part in split_message(text):
            self._call("sendMessage", {"chat_id": chat_id, "text": part, "disable_web_page_preview": "true"})

    def send_typing(self, chat_id: int) -> None:
        self._call("sendChatAction", {"chat_id": chat_id, "action": "typing"})

    def send_document(self, chat_id: int, path: Path, caption: str = "") -> None:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise TelegramError("file is larger than Telegram's 50 MB bot limit")
        boundary = uuid.uuid4().hex
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        fields = [("chat_id", str(chat_id))] + ([("caption", caption[:1000])] if caption else [])
        body = b""
        for k, v in fields:
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
        safe_name = re.sub(r'["\r\n]', "_", path.name)
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{safe_name}\"\r\n"
                 f"Content-Type: {ctype}\r\n\r\n").encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        url = f"{API}/bot{self._token}/sendDocument"
        data = self._http(url, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}, 120.0)
        if not isinstance(data, dict) or not data.get("ok"):
            raise TelegramError(str(data.get("description", "upload failed") if isinstance(data, dict) else "bad response"))
