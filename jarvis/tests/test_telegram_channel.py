"""Telegram channel (P2 of the Cherry Studio parity plan). No network: the HTTP layer is faked."""
from __future__ import annotations

import json
import urllib.parse

import pytest

from jarvis.channels import TelegramBot, TelegramChannel, split_message

TOKEN = "123456789:" + "A" * 35


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.updates = []

    def __call__(self, url, body, headers, timeout):
        method = url.rsplit("/", 1)[-1]
        params = dict(urllib.parse.parse_qsl(body.decode())) if body and "multipart" not in headers.get("Content-Type", "") else {}
        self.calls.append((method, params, body))
        if method == "getUpdates":
            ups, self.updates = self.updates, []
            return {"ok": True, "result": ups}
        if method == "getMe":
            return {"ok": True, "result": {"username": "jarvis_bot"}}
        return {"ok": True, "result": True}

    def sent(self):
        return [(p.get("chat_id"), p.get("text")) for m, p, _ in self.calls if m == "sendMessage"]


class FakeConfirm:
    def __init__(self):
        self.title = ""
        self.resolved = []

    def pending_title(self):
        return self.title

    def resolve(self, accepted, source="HUD"):
        self.resolved.append((accepted, source))
        self.title = ""


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _msg(chat_id, text, uid=1, kind="private"):
    return {"update_id": uid, "message": {"chat": {"id": chat_id, "type": kind}, "from": {"first_name": "Lesandu"},
                                          "text": text}}


@pytest.fixture()
def env(tmp_path):
    http = FakeHttp()
    bot = TelegramBot(TOKEN, http=http)
    submitted = []
    confirm = FakeConfirm()
    stops = []
    clock = Clock()

    def submit(text):
        submitted.append(text)
        return "sent"

    ch = TelegramChannel(bot, submit=submit, state_path=tmp_path / "tg.json", clock=clock,
                         confirm_api=confirm, stopper=stops.append)
    return ch, http, submitted, confirm, stops, clock, tmp_path


def test_token_validation():
    with pytest.raises(ValueError):
        TelegramBot("not-a-token")


def test_split_message_limits():
    parts = split_message("word " * 2000, limit=500)
    assert all(len(p) <= 500 for p in parts) and len(parts) > 10
    assert split_message("") == []


def test_unpaired_chats_are_ignored(env):
    ch, http, submitted, *_ = env
    http.updates = [_msg(42, "delete everything", 1), _msg(42, "/start", 2), _msg(43, "hi", 3, kind="group")]
    ch.poll_once(timeout=0)
    assert submitted == []
    assert http.sent() == [("42", "This is a private JARVIS. Send /pair <code> with the code shown on the PC.")]
    assert ch._state["offset"] == 4


def test_pairing_code_flow_and_limits(env):
    ch, http, submitted, confirm, stops, clock, tmp_path = env
    http.updates = [_msg(7, "/pair 000000", 1)]
    ch.poll_once(timeout=0)
    assert "No pairing code" in http.sent()[-1][1]

    code = ch.new_pair_code()
    wrong = "111111" if code != "111111" else "222222"
    for i in range(5):
        http.updates = [_msg(7, f"/pair {wrong}", 10 + i)]
        ch.poll_once(timeout=0)
    http.updates = [_msg(7, f"/pair {code}", 20)]          # code burned after 5 wrong tries
    ch.poll_once(timeout=0)
    assert "7" not in ch.paired()

    code = ch.new_pair_code()
    clock.t += 601                                         # expired
    http.updates = [_msg(7, f"/pair {code}", 30)]
    ch.poll_once(timeout=0)
    assert "7" not in ch.paired()

    code = ch.new_pair_code()
    http.updates = [_msg(7, f"/pair {code}", 40)]
    ch.poll_once(timeout=0)
    assert "7" in ch.paired() and http.sent()[-1][1].startswith("Paired.")
    saved = json.loads((tmp_path / "tg.json").read_text())
    assert "7" in saved["paired"] and saved["offset"] == 41


def _paired(env):
    ch, http, *_ = env
    code = ch.new_pair_code()
    http.updates = [_msg(7, f"/pair {code}", 1)]
    ch.poll_once(timeout=0)
    return ch


def test_owner_commands_flow_and_reply_collection(env):
    ch, http, submitted, confirm, stops, clock, _ = env
    _paired(env)
    http.updates = [_msg(7, "what is on my calendar today", 2)]
    ch.poll_once(timeout=0)
    assert submitted == ["what is on my calendar today"]
    ch.on_log_line("You: what is on my calendar today")      # ignored: not an assistant line
    ch.on_log_line("JARVIS: You have a client call at 3 pm.")
    ch.on_log_line("SYS: tool ran")
    ch.flush_replies()                                        # not quiet yet
    assert http.sent()[-1][1].startswith("Paired.")
    clock.t += 4
    ch.flush_replies()
    assert http.sent()[-1] == ("7", "You have a client call at 3 pm.")


def test_confirmation_over_telegram(env):
    ch, http, submitted, confirm, stops, clock, _ = env
    _paired(env)
    http.updates = [_msg(7, "send me the invoice pdf", 2)]
    ch.poll_once(timeout=0)
    confirm.title = "Send file invoice.pdf"
    ch.flush_replies()
    assert "needs your approval: Send file invoice.pdf" in http.sent()[-1][1]
    http.updates = [_msg(7, "yes", 3)]
    ch.poll_once(timeout=0)
    assert confirm.resolved == [(True, "Telegram")]
    assert submitted == ["send me the invoice pdf"]           # "yes" was not forwarded as a new command


def test_stop_status_help_unpair_and_refusals(tmp_path):
    http = FakeHttp()
    stops = []
    ch = TelegramChannel(TelegramBot(TOKEN, http=http), submit=lambda t: "locked",
                         state_path=tmp_path / "tg.json", stopper=stops.append)
    code = ch.new_pair_code()
    http.updates = [_msg(9, f"/pair {code}", 1), _msg(9, "/stop", 2), _msg(9, "/status", 3),
                    _msg(9, "open chrome", 4), _msg(9, "/unpair", 5)]
    ch.poll_once(timeout=0)
    texts = [t for _, t in http.sent()]
    assert stops == ["telegram /stop"]
    assert "Stopped." in texts and any(t.startswith("JARVIS is online") for t in texts)
    assert "JARVIS is locked. Unlock it on the PC first." in texts
    assert ch.paired() == {}


def test_notify_and_send_file(env, tmp_path):
    ch, http, *_ = env
    _paired(env)
    assert ch.notify("Backup finished") == 1
    f = tmp_path / "report.txt"
    f.write_text("hello")
    assert ch.send_file(f, "here") == 1
    method, _, body = http.calls[-1]
    assert method == "sendDocument" and b'filename="report.txt"' in body and b"hello" in body


def test_voice_tool_without_token(monkeypatch):
    from jarvis.actions import telegram_channel as tool
    from jarvis.channels import service

    monkeypatch.setattr(service, "_channel", None)
    monkeypatch.setattr(service, "configured_token", lambda: "")
    assert "not set up" in tool.telegram({"action": "status"})
    assert service.start_if_configured(lambda t: None) is None


def test_voice_tool_pair_and_send(monkeypatch, env):
    from jarvis.actions import telegram_channel as tool
    from jarvis.channels import service

    ch, http, *_ = env
    monkeypatch.setattr(service, "_channel", ch)
    out = tool.telegram({"action": "pair"})
    assert "/pair " in out and ch._code is not None
    assert "No Telegram chat is paired" in tool.telegram({"action": "send", "text": "hi"})


def test_security_tiers_for_telegram():
    from jarvis.core import security

    assert security.tier_for("telegram", {"action": "status"}) == security.TIER_SAFE
    assert security.tier_for("telegram", {"action": "send"}) == security.TIER_SENSITIVE
    assert security.tier_for("telegram", {"action": "pair"}) == security.TIER_DANGEROUS
    assert security.tier_for("telegram", {"action": "send_file"}) == security.TIER_DANGEROUS
