"""Phase 2 Module B: the web client is served, installable, and runs in a browser.

The browser test drives headless Chromium (if available) against a real hub on
localhost: it pairs, checks the states/feed/status strip, forces the minimal
tier and checks every control still works, and records the frame rate.
"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

JARVIS_DIR = Path(__file__).resolve().parents[1]
if str(JARVIS_DIR) not in sys.path:
    sys.path.insert(0, str(JARVIS_DIR))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from jarvis.hub.config import load_config  # noqa: E402
from jarvis.hub.server import CLIENT_DIR, COOKIE, Hub  # noqa: E402

DEVICES = [{"name": "laptop", "kind": "agent"},
           {"name": "tablet", "kind": "android", "client": True},
           {"name": "phone", "kind": "android", "client": True}]


def _make_hub(**overrides) -> Hub:
    state = tempfile.mkdtemp()
    with patch.dict("os.environ", {"JARVIS_HUB_STATE": state, "JARVIS_HUB_LIVE": "0"}):
        cfg = load_config(**overrides)
    Path(cfg.devices_path).write_text(json.dumps({"devices": DEVICES}))
    return Hub(cfg)


class StaticClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hub = _make_hub()
        self.client = TestClient(TestServer(self.hub.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_unpaired_browser_is_sent_to_pairing(self):
        resp = await self.client.get("/", allow_redirects=False)
        self.assertEqual((resp.status, resp.headers["Location"]), (302, "/pair"))

    async def test_paired_browser_gets_the_app_and_pwa_files(self):
        token, _ = self.hub.tokens.redeem(self.hub.tokens.create_code("tablet").code)
        self.client.session.cookie_jar.update_cookies({COOKIE: token})
        self.assertIn("app.js", await (await self.client.get("/")).text())
        manifest = await (await self.client.get("/manifest.webmanifest")).json()
        self.assertEqual(manifest["display"], "fullscreen")
        sizes = {i["sizes"] for i in manifest["icons"]}
        self.assertTrue({"192x192", "512x512"} <= sizes)
        for icon in manifest["icons"]:
            self.assertEqual((await self.client.get(icon["src"])).status, 200)
        sw = await self.client.get("/sw.js")
        self.assertIn("javascript", sw.headers["Content-Type"])
        for name in ("app.js", "orb.js", "governor.js", "theme.js", "theme.css", "app.css"):
            self.assertEqual((await self.client.get(f"/static/{name}")).status, 200, name)

    def test_theme_holds_all_colors(self):
        css = (CLIENT_DIR / "theme.css").read_text(encoding="utf-8")
        app_css = (CLIENT_DIR / "app.css").read_text(encoding="utf-8")
        self.assertIn("--accent", css)
        # Component styles use theme variables, not literal colors.
        self.assertNotRegex(app_css.replace("rgba(", "").replace("#fff", ""), r"#[0-9a-fA-F]{6}\b")
        self.assertNotIn("filter:", app_css)        # no blur/filter effects
        self.assertNotIn("backdrop-filter", app_css)


@unittest.skipUnless(shutil.which("node"), "node not installed (dev-only test runner)")
class GovernorNodeTests(unittest.TestCase):
    def test_governor_logic(self):
        out = subprocess.run(["node", "--test", str(JARVIS_DIR / "tests" / "js" / "governor.test.mjs")],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


def _chromium() -> str | None:
    found = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")
    return found[0] if found else None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(_chromium() and os.environ.get("JARVIS_BROWSER_TESTS", "1") != "0",
                     "headless Chromium not available")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.hub = _make_hub(port=cls.port, bind=["127.0.0.1"], heartbeat_seconds=1.0)
        cls.messages: list[dict] = []
        cls.hub.clients.on_message.append(lambda conn, msg: cls.messages.append(msg))
        from jarvis.hub.audio_router import AudioRouter
        cls.mic_frames: list[bytes] = []
        cls.router = AudioRouter(cls.hub, on_mic=cls.mic_frames.append)
        cls.loop = asyncio.new_event_loop()
        cls.thread = threading.Thread(target=cls.loop.run_forever, daemon=True)
        cls.thread.start()
        asyncio.run_coroutine_threadsafe(cls.hub.start(), cls.loop).result(10)
        cls.token, _ = cls.hub.tokens.redeem(cls.hub.tokens.create_code("tablet").code)

    @classmethod
    def tearDownClass(cls):
        asyncio.run_coroutine_threadsafe(cls.hub.stop(), cls.loop).result(10)
        cls.loop.call_soon_threadsafe(cls.loop.stop)

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(10)

    def test_client_runs_and_every_control_works_in_minimal_tier(self):
        from playwright.sync_api import sync_playwright
        url = f"http://localhost:{self.port}/"
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=_chromium(), args=["--no-sandbox"])
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            ctx.add_cookies([{"name": COOKIE, "value": self.token, "url": url}])
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("document.getElementById('state-label').textContent === 'Tap to talk'",
                                   timeout=10000)
            self.assertIn("tablet", page.inner_text("#devices"))
            page.wait_for_timeout(2500)
            fps_default = page.evaluate("window.jarvis.governor.lastFps || 0")
            tier_default = page.evaluate("window.jarvis.governor.tier")

            # Hub -> client: activity feed and toasts.
            self._run(self.hub.clients.broadcast({"type": "log", "text": "SYS: hello from the hub"}))
            self._run(self.hub.clients.broadcast({"type": "notify", "text": "Stretch now"}))
            page.wait_for_selector("text=hello from the hub", timeout=5000)
            page.wait_for_selector("text=Stretch now", timeout=5000)

            # Force the minimal tier: everything must keep working.
            page.click("#settings-btn")
            page.select_option("#quality", "minimal")
            page.click("text=Close")
            self.assertEqual(page.evaluate("window.jarvis.governor.tier"), "minimal")
            page.click("#stop")
            page.check("#conversation")
            page.fill("#text", "what time is it")
            page.press("#text", "Enter")
            page.wait_for_timeout(500)
            types = [m.get("type") for m in self.messages]
            for expected in ("stop", "conversation_mode", "activate", "text"):
                self.assertIn(expected, types)
            self._run(self.hub.clients.broadcast({"type": "state", "state": "THINKING"}))
            page.wait_for_function("document.body.classList.contains('state-thinking')", timeout=5000)
            page.wait_for_timeout(2500)
            fps_minimal = page.evaluate("window.jarvis.governor.lastFps || 0")
            browser.close()
        self.assertEqual(errors, [])
        print(f"\n[browser] headless Chromium: default tier {tier_default} {fps_default:.0f} fps; "
              f"minimal {fps_minimal:.0f} fps")
        self.assertGreater(fps_minimal, 10)


class BrowserAudioTests(BrowserTests):
    """The real AudioWorklets with Chromium's fake microphone."""

    def test_client_runs_and_every_control_works_in_minimal_tier(self):
        self.skipTest("covered by BrowserTests")

    def test_mic_frames_reach_the_hub_and_playback_flushes(self):
        from playwright.sync_api import sync_playwright
        url = f"http://localhost:{self.port}/"
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=_chromium(), args=[
                "--no-sandbox", "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
            ctx = browser.new_context()
            ctx.add_cookies([{"name": COOKIE, "value": self.token, "url": url}])
            ctx.grant_permissions(["microphone"], origin=url.rstrip("/"))
            page = ctx.new_page()
            page.goto(url)
            page.wait_for_function("document.getElementById('state-label').textContent === 'Tap to talk'",
                                   timeout=10000)
            page.wait_for_function("window.jarvis.audio !== null", timeout=5000)
            page.click("#orb")                                  # tap to talk
            page.wait_for_timeout(1500)
            frames = list(self.mic_frames)
            self.assertEqual(self.router.active, "tablet")
            self.assertGreater(len(frames), 30)                  # ~50 per second
            self.assertTrue(all(len(f) == 640 for f in frames))  # 20 ms of 16 kHz PCM16
            # Hub -> client speech, then an instant flush.
            for _ in range(40):
                self._run(self.router.send_audio(b"\x10\x00" * 2400))     # 100 ms each
            page.wait_for_function("window.jarvis.audio.bufferedMs > 500", timeout=5000)
            self._run(self.router.flush())
            page.wait_for_function("window.jarvis.audio.bufferedMs < 50", timeout=2000)
            browser.close()


if __name__ == "__main__":
    unittest.main()
