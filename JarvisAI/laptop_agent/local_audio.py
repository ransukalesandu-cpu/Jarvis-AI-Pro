"""Opt-in: the laptop's own microphone and speakers, with the "Hey Jarvis" wake word.

Enabled with ``"local_audio": true`` in agent.json. The wake word keeps working
when the hub runs elsewhere, because it listens here, next to the laptop's
microphone, and only sends audio after it hears the wake phrase:

1. the microphone feeds the local wake-word detector (core/wake_word.py,
   openwakeword) and nothing leaves the laptop;
2. on "Hey Jarvis" the agent tells the hub the laptop is now the active
   device and streams 16 kHz frames until the hub says stop listening;
3. JARVIS's voice for the laptop arrives as 24 kHz frames and plays here.

Cost: openwakeword + onnxruntime add roughly 40-60 MB to the agent, which can
take it past the ~100 MB target; that is why it is off by default.
"""
from __future__ import annotations

import collections
import threading

from hub import protocol


class LocalAudio:
    def __init__(self):
        self.client = None
        self.streaming = False
        self._out = collections.deque()
        self._lock = threading.Lock()
        self.detector = None

    def start(self, client) -> bool:
        self.client = client
        try:
            import numpy as np
            import sounddevice as sd

            from core.wake_word import WakeWordDetector
        except Exception as exc:
            print(f"[Agent] Local audio unavailable: {exc}")
            return False
        self.detector = WakeWordDetector(on_detect=self._wake, logger=lambda m: print(f"[Wake] {m}"))
        if not self.detector.start():
            print("[Agent] Wake word model not installed; local audio needs it (see Wake Word settings).")
        self.np = np

        def mic(indata, _frames, _time, _status):
            frame = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
            if self.detector is not None:
                self.detector.feed(frame)
            if self.streaming:
                self.client.send_bytes_threadsafe(protocol.audio_frame(frame.astype(np.int16).tobytes()))

        def speaker(outdata, frames, _time, _status):
            need = frames * 2
            buf = bytearray()
            with self._lock:
                while self._out and len(buf) < need:
                    chunk = self._out.popleft()
                    take = need - len(buf)
                    buf += chunk[:take]
                    if len(chunk) > take:
                        self._out.appendleft(chunk[take:])
            buf += b"\x00" * (need - len(buf))
            outdata[:] = np.frombuffer(bytes(buf), dtype=np.int16).reshape(-1, 1)

        self.inp = sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=320, callback=mic)
        self.outp = sd.OutputStream(samplerate=24000, channels=1, dtype="int16", blocksize=480,
                                    callback=speaker)
        self.inp.start()
        self.outp.start()
        return True

    def _wake(self) -> None:
        self.streaming = True
        self.client.send_threadsafe({"type": "audio_activate"})

    def control(self, msg: dict) -> None:
        if msg.get("type") == "listen" and not msg.get("on"):
            self.streaming = False
        elif msg.get("type") == "flush":
            with self._lock:
                self._out.clear()

    def play(self, pcm: bytes) -> None:
        with self._lock:
            self._out.append(bytes(pcm))
