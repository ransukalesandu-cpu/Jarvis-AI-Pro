"""The Phase 1 voice core running inside the hub, with network audio.

`HubJarvisLive` is the Phase 1 `JarvisLive` (receive loop, barge-in and
held-audio handling, stop word, tool layer, triggers, jobs, Full Access) with
only its edges swapped:

* microphone: PCM from the active client (hub/audio_router.py) instead of
  `sounddevice`. Browsers apply echo cancellation, so the mic keeps streaming
  while JARVIS speaks and Gemini's own voice-activity detection reports
  barge-in (`server_content.interrupted`), which flushes the client at once.
* speaker: Gemini's 24 kHz PCM is sent to the output device instead of a
  sound card. The client plays it through a small jitter buffer.
* UI: logs and states are broadcast to every client (`HubUI`).
* tools: only hub-side tools load here (memory, rules, triggers, jobs, web
  search, mail...). Laptop and Android tools run in the laptop agent and are
  added by hub/remote_tools.py when it connects.
* the desktop dashboard, the clap detector and the local wake word do not run
  in the hub; the wake word runs in the agent next to the laptop's microphone.

Desktop mode (`python main.py`) is untouched.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from core.ui_coordinator import HeadlessJarvisUI
from hub.audio_router import AudioRouter

# Tools that belong to the conversation, not to a machine. Everything else in
# actions/ touches the laptop and runs in the laptop agent.
HUB_ACTION_FILES = frozenset({
    "proactive_triggers.py", "owner_memory.py", "routines.py", "jobs_tools.py",
    "show_recent_actions.py", "email_tool.py", "calendar_tool.py", "event_sources.py",
    "web_search.py", "weather_report.py", "personal_memory.py", "change_personality.py",
    "remember_intention.py", "proactive_feedback.py", "jarvis_settings.py",
})
# Inline Phase 1 tools that need this machine's screen/camera; the agent's
# see_screen / see_camera / system_info replace them.
HUB_DROPPED_INLINE = frozenset({"screen_process", "close_camera", "system_status"})
_STATE_MAP = {"LISTENING": "LISTENING", "THINKING": "THINKING", "SPEAKING": "SPEAKING",
              "SLEEPING": "SLEEPING", "LOCKED": "LOCKED"}


class HubUI(HeadlessJarvisUI):
    """Broadcast the Phase 1 UI contract to every connected client."""

    def __init__(self, hub):
        super().__init__()
        self.hub = hub

    def _broadcast(self, msg: dict) -> None:
        loop = self.hub.loop
        if loop is None or not loop.is_running():
            return
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.hub.clients.broadcast(msg)))

    def write_log(self, text: str) -> None:
        super().write_log(text)
        self._broadcast({"type": "log", "text": str(text)[:600]})

    def set_state(self, state: str) -> None:
        self.state = state
        self._broadcast({"type": "state", "state": _STATE_MAP.get(state, state)})

    def show_content(self, title: str, text: str) -> None:
        self._broadcast({"type": "log", "text": f"{title}: {str(text)[:500]}"})

    def request_say(self, text: str) -> None:
        self._broadcast({"type": "notify", "text": text})


class NetworkOutputStream:
    """Stands in for the sound card: abort() flushes the output device."""

    def __init__(self, hub, router: AudioRouter):
        self.hub, self.router = hub, router
        self.active = True
        self.latency = 0.08

    def abort(self) -> None:
        loop = self.hub.loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.router.flush()))

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


def _build_class():
    import main

    class HubJarvisLive(main.JarvisLive):
        _dashboard_enabled = False

        def __init__(self, hub, router: AudioRouter):
            self.hub = hub
            self.router = router
            super().__init__(HubUI(hub))
            self._wake_enabled = False
            self._mic_queue: asyncio.Queue | None = None
            self._turn_audio_seconds = 0.0
            self._turn_audio_started = 0.0

        # discovery / declarations ------------------------------------------
        def _include_action_file(self, path: Path) -> bool:
            return path.name in HUB_ACTION_FILES

        def _keep_declaration(self, declaration: dict) -> bool:
            return declaration.get("name") not in HUB_DROPPED_INLINE

        # no local microphone devices in the hub ----------------------------
        def _ensure_clap_detector(self) -> bool:
            return False

        def _ensure_wake_detector(self) -> bool:
            return False

        # microphone: the active client -------------------------------------
        def feed_mic(self, pcm: bytes) -> None:
            queue = self._mic_queue
            if queue is not None and not queue.full():
                queue.put_nowait(pcm)

        async def _listen_audio(self):
            self._mic_queue = asyncio.Queue(maxsize=200)
            print("[Hub] 🎤 Microphone comes from the active client.")
            while True:
                pcm = await self._mic_queue.get()
                queue = self.out_queue
                # If the sender is behind, dropping 20 ms beats growing latency.
                if queue is not None and not queue.full():
                    queue.put_nowait({"data": pcm, "mime_type": "audio/pcm;rate=16000"})

        # speaker: the output device ----------------------------------------
        async def _play_audio(self):
            self._output_stream = NetworkOutputStream(self.hub, self.router)
            print("[Hub] 🔊 Voice goes to the output device.")
            bytes_per_sec = 24000 * 2
            while not self._shutdown_requested:
                if self._playback_interrupt_requested.is_set():
                    self._playback_interrupt_requested.clear()
                    await self.router.flush()
                    self._turn_audio_seconds = 0.0
                    self.set_speaking(False)
                try:
                    chunk = await asyncio.wait_for(self.audio_in_queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    await self._maybe_finish_speaking()
                    continue
                if self._playback_interrupt_requested.is_set():
                    continue
                if self._turn_audio_seconds == 0.0:
                    self._turn_audio_started = time.monotonic()
                self._turn_audio_seconds += len(chunk) / bytes_per_sec
                self.set_speaking(True)
                await self.router.send_audio(chunk)

        async def _maybe_finish_speaking(self) -> None:
            done = self._turn_done_event
            if not (done and done.is_set() and self.audio_in_queue.empty()):
                return
            if self._turn_audio_seconds:
                # The client plays in real time behind a small jitter buffer.
                playout_end = self._turn_audio_started + self._turn_audio_seconds + 0.15
                if time.monotonic() < playout_end:
                    return
            self._turn_audio_seconds = 0.0
            done.clear()
            self.set_speaking(False)
            await self.router.end_turn()

        # client controls ----------------------------------------------------
        async def on_client_control(self, verb: str, data: dict) -> None:
            if verb == "activate":
                if not self._awake:
                    self.wake(reason=f"tap on {data.get('device')}")
                self._last_user_speech = time.monotonic()
            elif verb == "stop":
                self._handle_stop_word()
            elif verb == "text":
                text = str(data.get("text") or "").strip()
                if text:
                    self._on_text_command(text)
            elif verb in ("deactivate", "closed"):
                if self.router.active is None and not self._is_speaking:
                    self.ui.set_state("LISTENING")

    return HubJarvisLive


class LiveExtension:
    """Hub extension that owns the Gemini session task."""

    def __init__(self, hub):
        self.hub = hub
        self.router = AudioRouter(hub)
        self.live = _build_class()(hub, self.router)
        # Tools: hub-side actions, hub-native tools, then whatever agents announce.
        from core.tool_runtime import set_device_resolver
        from hub.remote_tools import CompositeRegistry, RemoteToolRegistry
        self.remote = RemoteToolRegistry(hub)
        self.remote.on_tools_changed = self._tools_changed
        hub.remote = self.remote
        self.live._action_registry = CompositeRegistry(
            [self.live._action_registry, hub.tools, self.remote])
        set_device_resolver(self._resolve_device)
        self._reconnect_handle = None
        self.router.on_mic = self.live.feed_mic
        self.router.on_control = self.live.on_client_control
        hub.live = self.live
        hub.router = self.router
        self.task: asyncio.Task | None = None

    def _resolve_device(self, device: str) -> str:
        if self.hub.registry.get(device) is not None:
            return ""
        return (f"I don't know a device called '{device}'. "
                f"I know: {', '.join(self.hub.registry.names())}.")

    def _tools_changed(self) -> None:
        """An agent came or went: rebuild the Gemini session's tool list.

        The Live API fixes tools at connect time; session resumption keeps the
        conversation across the reconnect. Debounced so a burst is one reconnect.
        """
        loop = self.hub.loop
        if loop is None or not loop.is_running() or self.live.session is None:
            return

        def fire():
            self._reconnect_handle = None
            self.live.request_reconnect()
        if self._reconnect_handle is not None:
            self._reconnect_handle.cancel()
        self._reconnect_handle = loop.call_later(1.0, fire)

    async def start(self) -> None:
        self.task = asyncio.create_task(self.live.run())

    async def stop(self) -> None:
        from core.tool_runtime import set_device_resolver
        set_device_resolver(None)
        self.live.request_shutdown()
        if self.task is not None:
            try:
                await asyncio.wait_for(self.task, 10)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self.task.cancel()


def attach_live(hub) -> LiveExtension:
    ext = LiveExtension(hub)
    hub.extensions.append(ext)
    return ext
