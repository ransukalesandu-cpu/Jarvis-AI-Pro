"""Phase 2 Module C: active device, audio routing, barge-in flush, latency.

The Phase 1 voice core (HubJarvisLive) runs against a scripted Gemini session
while real WebSocket clients connect to a real hub.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

JARVIS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for p in (JARVIS_DIR, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from aiohttp import WSMsgType  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from hub import protocol  # noqa: E402
from hub.audio_router import AudioRouter  # noqa: E402
from hub.config import load_config  # noqa: E402
from hub.server import Hub  # noqa: E402

DEVICES = [{"name": "laptop", "kind": "agent"},
           {"name": "tablet", "kind": "android", "client": True},
           {"name": "phone", "kind": "android", "client": True}]


def _hub() -> Hub:
    state = tempfile.mkdtemp()
    with patch.dict("os.environ", {"JARVIS_HUB_STATE": state, "JARVIS_HUB_LIVE": "0"}):
        cfg = load_config()
    Path(cfg.devices_path).write_text(json.dumps({"devices": DEVICES}))
    return Hub(cfg)


class _Client:
    """A paired test client that records what the hub sends."""

    def __init__(self, ws, name):
        self.ws, self.name = ws, name
        self.json: list[dict] = []
        self.audio: list[tuple[float, bytes]] = []
        self.task = asyncio.create_task(self._pump())

    async def _pump(self):
        async for msg in self.ws:
            if msg.type == WSMsgType.TEXT:
                self.json.append({**json.loads(msg.data), "_t": time.monotonic()})
            elif msg.type == WSMsgType.BINARY:
                self.audio.append((time.monotonic(), msg.data[1:]))

    def got(self, kind):
        return [m for m in self.json if m["type"] == kind]

    async def send(self, msg):
        await self.ws.send_str(json.dumps(msg))

    async def mic(self, n=1, size=640):
        for _ in range(n):
            await self.ws.send_bytes(protocol.audio_frame(b"\x01\x00" * (size // 2)))


async def _connect(hub, http, name) -> _Client:
    token, _ = hub.tokens.redeem(hub.tokens.create_code(name).code)
    ws = await http.ws_connect("/ws/client")
    await ws.send_str(json.dumps({"type": "hello", "token": token}))
    client = _Client(ws, name)
    for _ in range(100):
        if client.got("welcome"):
            break
        await asyncio.sleep(0.01)
    return client


async def _until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hub = _hub()
        self.hub.loop = asyncio.get_running_loop()
        self.mic: list[bytes] = []
        self.router = AudioRouter(self.hub, on_mic=self.mic.append)
        self.http = TestClient(TestServer(self.hub.app))
        await self.http.start_server()

    async def asyncTearDown(self):
        await self.http.close()

    async def test_only_the_active_device_streams_and_tapping_moves_it(self):
        tablet = await _connect(self.hub, self.http, "tablet")
        phone = await _connect(self.hub, self.http, "phone")
        await phone.send({"type": "activate"})
        await _until(lambda: self.router.active == "phone")
        await phone.mic(3)
        await tablet.mic(3)                      # passive: ignored
        await _until(lambda: len(self.mic) >= 3)
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.mic), 3)
        await tablet.send({"type": "activate"})
        self.assertTrue(await _until(lambda: phone.got("flush")))
        self.assertEqual(phone.got("listen")[-1]["on"], False)
        self.assertEqual(self.router.output_target(), "tablet")
        self.assertEqual(tablet.got("active")[-1]["device"], "tablet")

    async def test_proactive_output_goes_to_last_active_then_tablet(self):
        tablet = await _connect(self.hub, self.http, "tablet")
        phone = await _connect(self.hub, self.http, "phone")
        self.assertEqual(self.router.output_target(), "tablet")       # nobody active yet
        await phone.send({"type": "activate"})
        await _until(lambda: self.router.active == "phone")
        await phone.send({"type": "deactivate"})
        await _until(lambda: self.router.active is None)
        self.assertEqual(self.router.output_target(), "phone")        # most recently active
        await self.router.send_audio(b"\x00\x00" * 480)
        self.assertTrue(await _until(lambda: phone.audio))
        self.assertEqual(tablet.audio, [])

    async def test_closing_the_active_client_returns_to_idle(self):
        phone = await _connect(self.hub, self.http, "phone")
        await phone.send({"type": "activate"})
        await _until(lambda: self.router.active == "phone")
        await phone.ws.close()
        self.assertTrue(await _until(lambda: self.router.active is None))

    async def test_tap_to_talk_stops_listening_after_the_answer(self):
        phone = await _connect(self.hub, self.http, "phone")
        await phone.send({"type": "activate"})
        await _until(lambda: self.router.active == "phone")
        await self.router.end_turn()
        self.assertTrue(await _until(lambda: phone.got("listen")))
        await phone.send({"type": "conversation_mode", "on": True})
        await phone.send({"type": "activate"})
        await asyncio.sleep(0.05)
        before = len(phone.got("listen"))
        await self.router.end_turn()
        await asyncio.sleep(0.05)
        self.assertEqual(len(phone.got("listen")), before)            # keeps listening


class _ControlledSession:
    """A Gemini Live session the test feeds event by event."""

    def __init__(self):
        self.events: asyncio.Queue = asyncio.Queue()
        self.sent: list = []

    async def receive(self):
        while True:
            yield await self.events.get()

    async def send_realtime_input(self, **kwargs):
        self.sent.append(kwargs)

    async def send_client_content(self, **kwargs):
        self.sent.append(kwargs)

    async def send_tool_response(self, **kwargs):
        self.sent.append(kwargs)


class HubVoiceCoreTests(unittest.IsolatedAsyncioTestCase):
    """HubJarvisLive end to end, with a scripted session instead of Gemini."""

    async def asyncSetUp(self):
        from hub.live import LiveExtension
        from live_replay import Step, _event
        self.Step, self.event = Step, _event
        self.hub = _hub()
        self.hub.loop = asyncio.get_running_loop()
        self.ext = LiveExtension(self.hub)
        live = self.ext.live
        live._loop = asyncio.get_running_loop()
        live.session = _ControlledSession()
        live.audio_in_queue = asyncio.Queue()
        live.out_queue = asyncio.Queue(maxsize=200)
        live._turn_done_event = asyncio.Event()
        live._awake = True
        self.live = live
        self.http = TestClient(TestServer(self.hub.app))
        await self.http.start_server()
        self.tasks = [asyncio.create_task(c) for c in
                      (live._receive_audio(), live._play_audio(), live._listen_audio())]

    async def asyncTearDown(self):
        self.live._shutdown_requested = True
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.http.close()

    def _push(self, **kwargs):
        self.live.session.events.put_nowait(self.event(self.Step(**kwargs), kwargs.pop("marker", 2)))

    async def test_phone_question_answered_on_phone_then_moves_to_tablet(self):
        tablet = await _connect(self.hub, self.http, "tablet")
        phone = await _connect(self.hub, self.http, "phone")
        await phone.send({"type": "activate"})
        await _until(lambda: self.ext.router.active == "phone")
        sent_at = time.monotonic()
        await phone.mic(1)
        item = await asyncio.wait_for(self.live.out_queue.get(), 2)
        mic_latency = time.monotonic() - sent_at
        self.assertEqual(item["mime_type"], "audio/pcm;rate=16000")

        self._push(input_text="what time is it")
        pushed = time.monotonic()
        for _ in range(5):
            self._push(audio_ms=40)
        self._push(turn_complete=True)
        self.assertTrue(await _until(lambda: len(phone.audio) >= 4))
        speaker_latency = phone.audio[0][0] - pushed
        self.assertEqual(tablet.audio, [])

        await tablet.send({"type": "activate"})
        await _until(lambda: self.ext.router.active == "tablet")
        self._push(input_text="and the weather?")
        self._push(audio_ms=100)           # >= one 50 ms playback slice
        self.assertTrue(await _until(lambda: tablet.audio))
        print(f"\n[latency] hub adds: mic client->Gemini queue {mic_latency * 1000:.1f} ms, "
              f"Gemini->client speaker {speaker_latency * 1000:.1f} ms (loopback)")
        self.assertLess(mic_latency, 0.05)
        self.assertLess(speaker_latency, 0.1)

    async def test_interruption_flushes_the_client_within_300_ms(self):
        phone = await _connect(self.hub, self.http, "phone")
        await phone.send({"type": "activate"})
        await _until(lambda: self.ext.router.active == "phone")
        self._push(input_text="tell me a long story")
        for _ in range(20):
            self._push(audio_ms=100)
        await _until(lambda: len(phone.audio) >= 5)
        before = len(phone.got("flush"))
        self._push(interrupted=True)
        at = time.monotonic()
        self.assertTrue(await _until(lambda: len(phone.got("flush")) > before, 1.0))
        flush_ms = (phone.got("flush")[-1]["_t"] - at) * 1000
        print(f"\n[latency] barge-in flush reached the client in {flush_ms:.1f} ms")
        self.assertLess(flush_ms, 300)

    async def test_stop_button_uses_the_stop_word_path(self):
        phone = await _connect(self.hub, self.http, "phone")
        await phone.send({"type": "activate"})
        await _until(lambda: self.ext.router.active == "phone")
        with patch.object(self.live, "_handle_stop_word") as stop:
            await phone.send({"type": "stop"})
            self.assertTrue(await _until(lambda: stop.called))

    async def test_typed_text_goes_to_the_session(self):
        phone = await _connect(self.hub, self.http, "phone")
        with patch("core.security.get_auth_manager", return_value=SimpleNamespace(
                is_privacy_lock_active=lambda: False, needs_pin=lambda: False, is_silent=lambda: False)):
            await phone.send({"type": "text", "text": "hello jarvis"})
            ok = await _until(lambda: any("turns" in s for s in self.live.session.sent))
        self.assertTrue(ok)
        self.assertEqual(self.ext.router.active, "phone")


if __name__ == "__main__":
    unittest.main()
