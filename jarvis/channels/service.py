"""Telegram channel: control JARVIS from your phone when you are away from the PC.

Flow
----
1. The owner creates a bot with @BotFather and puts the token in
   ``config/api_keys.json`` as ``telegram_bot_token`` (or ``JARVIS_TELEGRAM_BOT_TOKEN``).
2. "Pair Telegram" (voice) -> JARVIS shows a 6-digit code, valid 10 minutes.
3. The owner sends ``/pair 123456`` to the bot. That chat id is now trusted.
4. Text from a paired chat goes through the same ``CommandGate`` as the web UI
   (refused while locked / PIN pending / silent / guest, credential-shaped text
   refused, rate limited) and then into the normal assistant turn. JARVIS's
   written replies ("JARVIS: ..." log lines) are collected and sent back.
5. A pending confirmation can be answered from Telegram with YES / NO, and
   ``/stop`` fires the emergency stop.

Every other chat is ignored (audited, never answered beyond the /start hint).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .telegram import TelegramBot, TelegramError

PAIR_CODE_SECONDS = 600
PAIR_MAX_TRIES = 5
REPLY_QUIET_SECONDS = 3.0
REPLY_MAX_SECONDS = 60.0
MAX_PAIRED = 5

YES = {"yes", "y", "confirm", "confirm action", "ok", "ow", "ඔව්"}
NO = {"no", "n", "cancel", "cancel action", "naha", "නැහැ"}
_REASON_TEXT = {
    "locked": "JARVIS is locked. Unlock it on the PC first.",
    "auth_required": "JARVIS is waiting for the owner PIN on the PC.",
    "silent": "JARVIS is in silent mode.",
    "guest": "JARVIS is in Guest Mode, so remote commands are off.",
    "credential": "PINs and passwords are never accepted over Telegram.",
    "rate_limited": "Too fast, give me a second.",
    "too_long": "That message is too long (max 500 characters).",
    "unavailable": "JARVIS is not ready to take commands right now.",
}


def _state_path() -> Path:
    from jarvis.core.user_data import user_data_dir
    folder = user_data_dir() / "channels"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "telegram.json"


def configured_token() -> str:
    env = os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN", "").strip()
    if env:
        return env
    try:
        from jarvis.memory.config_manager import load_api_keys
        return str(load_api_keys().get("telegram_bot_token", "") or "").strip()
    except Exception:
        return ""


def _audit(decision: str, detail: str) -> None:
    try:
        from jarvis.core import security
        security.audit("channel", "telegram", "SENSITIVE", decision, detail[:200])
    except Exception:
        return


class TelegramChannel:
    def __init__(self, bot: TelegramBot, *, submit: Callable[[str], str],
                 state_path: Optional[Path] = None, clock: Callable[[], float] = time.time,
                 subscribe: Optional[Callable[[Callable[[str], None]], Callable[[], None]]] = None,
                 confirm_api=None, stopper: Optional[Callable[[str], None]] = None) -> None:
        self.bot = bot
        self._submit = submit
        self._path = state_path or _state_path()
        self._clock = clock
        self._lock = threading.RLock()
        self._state = self._load()
        self._code: Optional[tuple[str, float]] = None
        self._tries = 0
        self._waiting: Optional[dict] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._confirm = confirm_api
        self._stopper = stopper
        self.last_error = ""
        self._unsub = subscribe(self.on_log_line) if subscribe else None

    # ── persistence ─────────────────────────────────────────────────────────
    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("paired"), dict):
                return {"paired": data["paired"], "offset": int(data.get("offset", 0) or 0)}
        except (OSError, ValueError):
            pass
        return {"paired": {}, "offset": 0}

    def _save(self) -> None:
        text = json.dumps(self._state, indent=2)
        try:
            from jarvis.core.secure_file import write_private_text
            write_private_text(self._path, text)
        except ImportError:
            self._path.write_text(text, encoding="utf-8")

    # ── pairing ─────────────────────────────────────────────────────────────
    def new_pair_code(self) -> str:
        with self._lock:
            code = f"{secrets.randbelow(1_000_000):06d}"
            self._code = (code, self._clock() + PAIR_CODE_SECONDS)
            self._tries = 0
            return code

    def paired(self) -> dict:
        with self._lock:
            return dict(self._state["paired"])

    def unpair(self, chat_id: Optional[int] = None) -> int:
        with self._lock:
            if chat_id is None:
                n = len(self._state["paired"])
                self._state["paired"] = {}
            else:
                n = 1 if self._state["paired"].pop(str(chat_id), None) is not None else 0
            self._save()
            return n

    def _try_pair(self, chat_id: int, name: str, code: str) -> str:
        with self._lock:
            if self._code is None or self._clock() > self._code[1]:
                self._code = None
                return "No pairing code is active. Ask JARVIS on the PC to 'pair Telegram'."
            if len(self._state["paired"]) >= MAX_PAIRED:
                return "Too many paired chats. Unpair one first."
            if not secrets.compare_digest(code.strip(), self._code[0]):
                self._tries += 1
                if self._tries >= PAIR_MAX_TRIES:
                    self._code = None
                _audit("denied", f"wrong pairing code from chat {chat_id}")
                return "Wrong code."
            self._code = None
            self._state["paired"][str(chat_id)] = {"name": name[:60], "paired_at": int(self._clock())}
            self._save()
        _audit("allowed", f"paired chat {chat_id}")
        return "Paired. You can now talk to JARVIS here. Send /help for commands."

    # ── inbound ─────────────────────────────────────────────────────────────
    def handle_update(self, update: dict) -> None:
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = str(msg.get("text") or "").strip()
        if not isinstance(chat_id, int) or not text or chat.get("type") != "private":
            return
        name = str((msg.get("from") or {}).get("first_name") or chat.get("username") or "")
        lower = text.lower()
        if str(chat_id) not in self.paired():
            if lower.startswith("/pair"):
                self.bot.send_message(chat_id, self._try_pair(chat_id, name, text[5:]))
            elif lower.startswith("/start"):
                self.bot.send_message(chat_id, "This is a private JARVIS. Send /pair <code> with the code shown on the PC.")
            else:
                _audit("ignored", f"message from unpaired chat {chat_id}")
            return
        self._handle_owner(chat_id, text, lower)

    def _handle_owner(self, chat_id: int, text: str, lower: str) -> None:
        if lower in ("/help", "help"):
            self.bot.send_message(chat_id, "Just type what you want JARVIS to do.\n/stop - emergency stop\n"
                                           "/status - is JARVIS ready\nYES / NO - answer a pending confirmation\n"
                                           "/unpair - remove this chat")
            return
        if lower in ("/stop", "stop"):
            if self._stopper:
                self._stopper("telegram /stop")
            self.bot.send_message(chat_id, "Stopped.")
            return
        if lower == "/unpair":
            self.unpair(chat_id)
            self.bot.send_message(chat_id, "This chat is no longer paired.")
            return
        if lower == "/status":
            pending = self._pending_title()
            self.bot.send_message(chat_id, "JARVIS is online." + (f" Waiting for approval: {pending}" if pending else ""))
            return
        pending = self._pending_title()
        if pending and (lower in YES or lower in NO):
            accepted = lower in YES
            self._confirm.resolve(accepted, source="Telegram")
            self.bot.send_message(chat_id, f"{'Approved' if accepted else 'Cancelled'}: {pending}")
            self._expect_reply(chat_id)
            return
        reason = self._submit(text)
        if reason == "sent":
            self._expect_reply(chat_id)
            try:
                self.bot.send_typing(chat_id)
            except TelegramError:
                pass
        else:
            self.bot.send_message(chat_id, _REASON_TEXT.get(reason, f"Not sent ({reason})."))

    def _pending_title(self) -> str:
        if self._confirm is None:
            return ""
        try:
            return str(self._confirm.pending_title() or "")
        except Exception:
            return ""

    # ── replies ─────────────────────────────────────────────────────────────
    def _expect_reply(self, chat_id: int) -> None:
        with self._lock:
            now = self._clock()
            self._waiting = {"chat": chat_id, "lines": [], "since": now, "last": now,
                             "confirm": self._pending_title()}

    def on_log_line(self, line: str) -> None:
        from jarvis.webui import redact
        c = redact.classify(line)
        if not c or c[0] != "ai":
            return
        with self._lock:
            if self._waiting is not None:
                self._waiting["lines"].append(redact.scrub(c[1]))
                self._waiting["last"] = self._clock()

    def flush_replies(self) -> None:
        """Send collected assistant lines once JARVIS goes quiet; called from the poll loop."""
        pending = self._pending_title()
        ask = text = ""
        with self._lock:
            w = self._waiting
            if w is None:
                return
            now = self._clock()
            chat = w["chat"]
            if pending and pending != w["confirm"]:
                w["confirm"] = pending
                ask = f"JARVIS needs your approval: {pending}\nReply YES or NO."
            quiet = bool(w["lines"]) and now - w["last"] >= REPLY_QUIET_SECONDS
            expired = now - w["since"] >= REPLY_MAX_SECONDS
            if quiet or expired:
                self._waiting = None
                text = "\n".join(w["lines"]).strip()
        if text:
            self.bot.send_message(chat, text)
        if ask:
            self.bot.send_message(chat, ask)

    # ── outbound ────────────────────────────────────────────────────────────
    def notify(self, text: str) -> int:
        sent = 0
        for cid in self.paired():
            try:
                self.bot.send_message(int(cid), text)
                sent += 1
            except TelegramError as e:
                self.last_error = str(e)
        return sent

    def send_file(self, path: Path, caption: str = "") -> int:
        sent = 0
        for cid in self.paired():
            self.bot.send_document(int(cid), path, caption)
            sent += 1
        return sent

    # ── loop ────────────────────────────────────────────────────────────────
    def poll_once(self, timeout: int = 25) -> int:
        updates = self.bot.get_updates(self._state["offset"], timeout=timeout)
        for u in updates:
            uid = u.get("update_id")
            if isinstance(uid, int):
                with self._lock:
                    self._state["offset"] = max(self._state["offset"], uid + 1)
            try:
                self.handle_update(u)
            except TelegramError as e:
                self.last_error = str(e)
        if updates:
            with self._lock:
                self._save()
        self.flush_replies()
        return len(updates)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def run():
            backoff = 2.0
            while not self._stop.is_set():
                try:
                    # Short polls while a reply is being collected so it goes out promptly.
                    self.poll_once(timeout=2 if self._waiting else 25)
                    backoff = 2.0
                    self.last_error = ""
                except Exception as e:      # network down, bad token...: back off and keep going
                    self.last_error = f"{type(e).__name__}: {e}"[:200]
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 120.0)

        self._thread = threading.Thread(target=run, name="telegram-channel", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._unsub:
            self._unsub()
            self._unsub = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())


_channel: Optional[TelegramChannel] = None
_channel_lock = threading.Lock()


def get_channel() -> Optional[TelegramChannel]:
    return _channel


def start_if_configured(sink: Callable[[str], None]) -> Optional[TelegramChannel]:
    """Called once from JarvisLive: start the Telegram channel when a bot token is configured."""
    global _channel
    token = configured_token()
    if not token:
        return None
    with _channel_lock:
        if _channel is not None:
            return _channel
        try:
            bot = TelegramBot(token)
        except ValueError as e:
            print(f"[Telegram] {e}")
            return None
        from jarvis.core import confirm, identity, log_tap, security
        from jarvis.computer_control import estop
        from jarvis.webui.command_gate import CommandGate

        gate = CommandGate(sink, security.get_auth_manager,
                           lambda: identity.get_identity_manager().guest_mode_active())
        _channel = TelegramChannel(bot, submit=gate.submit, subscribe=log_tap.subscribe, confirm_api=confirm,
                                   stopper=lambda reason: estop.trigger(reason, source="telegram"))
        _channel.start()
        print("[Telegram] channel started")
        return _channel
