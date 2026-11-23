"""Offline voice loop: keeps JARVIS talking when Gemini Live is not available.

Gemini Live is the primary realtime voice path. When it is down (no network,
quota, ``OFFLINE=1``) JARVIS used to go silent: typed commands still reached the
Brain Engine text fallback, but nothing listened to the microphone or spoke the
answer. This loop fills that gap with local parts that already exist:

    microphone → "Hey Jarvis" wake word (if enabled) → energy VAD utterance cut
    → faster-whisper (``voice.local_stt``) → ``submit(text)`` → local TTS

``submit`` is ``JarvisLive._on_text_command``, so every spoken request goes
through the same privacy-lock / PIN / wake / agent / security gates as a typed
one and then to the Brain Engine fallback (cloud brain if reachable, otherwise
local Ollama). Nothing here executes tools itself.

Control with ``JARVIS_OFFLINE_VOICE``:
    ``auto`` (default) — start when Live has been down for ``grace_s`` seconds,
                         immediately when OFFLINE mode is on; stop when Live is back
    ``off``            — never start
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

from jarvis.core import failsoft

SAMPLE_RATE = 16_000
BLOCK = 1280                 # 80 ms; also the wake model's native frame size
SPEECH_LEVEL = 0.015         # RMS (float32) that counts as speech; same as local_stt.record
SILENCE_END_S = 1.2          # quiet after speech that ends the utterance
MAX_UTTERANCE_S = 20.0
MIN_UTTERANCE_S = 0.35       # shorter bursts are clicks/coughs, not requests
PREROLL_BLOCKS = 4           # keep ~320 ms before speech onset so first syllables survive
DEFAULT_GRACE_S = 8.0


def mode() -> str:
    value = str(os.environ.get("JARVIS_OFFLINE_VOICE", "auto")).strip().lower()
    return "off" if value in {"off", "0", "false", "no", "disabled"} else "auto"


def should_run(*, live_up: bool, down_for_s: float, offline: bool, stt_ready: bool,
               grace_s: float = DEFAULT_GRACE_S) -> bool:
    """Pure decision used by the watcher (unit-tested)."""
    if mode() == "off" or live_up or not stt_ready:
        return False
    return offline or down_for_s >= grace_s


class UtteranceCutter:
    """Energy VAD that turns a stream of float32 blocks into utterances."""

    def __init__(self, *, sample_rate: int = SAMPLE_RATE, level: float = SPEECH_LEVEL,
                 silence_end_s: float = SILENCE_END_S, max_s: float = MAX_UTTERANCE_S,
                 min_s: float = MIN_UTTERANCE_S, preroll_blocks: int = PREROLL_BLOCKS):
        self.sample_rate = sample_rate
        self.level = level
        self.silence_end_s = silence_end_s
        self.max_s = max_s
        self.min_s = min_s
        self.preroll_blocks = preroll_blocks
        self.reset()

    def reset(self) -> None:
        self._pre: list = []
        self._chunks: list = []
        self._speaking = False
        self._samples = 0
        self._voiced = 0
        self._quiet = 0

    @property
    def active(self) -> bool:
        return self._speaking

    def push(self, block):
        """Feed one float32 block; returns a finished utterance array or None."""
        import numpy as np
        block = np.asarray(block, dtype="float32").reshape(-1)
        if not block.size:
            return None
        rms = float(np.sqrt(np.mean(block ** 2)))
        loud = rms > self.level
        if not self._speaking:
            self._pre.append(block)
            if len(self._pre) > self.preroll_blocks:
                self._pre.pop(0)
            if not loud:
                return None
            self._speaking = True
            self._chunks = list(self._pre)
            self._samples = sum(c.size for c in self._chunks)
            self._pre = []
            self._voiced = block.size
            self._quiet = 0
            return None
        self._chunks.append(block)
        self._samples += block.size
        if loud:
            self._voiced += block.size
            self._quiet = 0
        else:
            self._quiet += block.size
        done = (self._quiet >= self.silence_end_s * self.sample_rate
                or self._samples >= self.max_s * self.sample_rate)
        if not done:
            return None
        audio = np.concatenate(self._chunks)
        voiced_s = self._voiced / self.sample_rate
        self.reset()
        return audio if voiced_s >= self.min_s else None


class OfflineVoiceLoop:
    """Background thread: listen → transcribe → submit, while JARVIS is not speaking."""

    def __init__(self, *, submit: Callable[[str], None],
                 is_awake: Callable[[], bool] = lambda: True,
                 is_speaking: Callable[[], bool] = lambda: False,
                 wake_feed: Optional[Callable[[object], None]] = None,
                 transcribe: Optional[Callable[[object], dict]] = None,
                 stream_factory: Optional[Callable[[], object]] = None,
                 logger: Callable[[str], None] = print):
        self._submit = submit
        self._is_awake = is_awake
        self._is_speaking = is_speaking
        self._wake_feed = wake_feed
        self._transcribe = transcribe
        self._stream_factory = stream_factory
        self._log = logger
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.cutter = UtteranceCutter()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> bool:
        if self.running:
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-offline-voice", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout)
        self._thread = None

    # ── internals ─────────────────────────────────────────────────────────
    def _open_stream(self):
        if self._stream_factory is not None:
            return self._stream_factory()
        import sounddevice as sd
        return sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=BLOCK)

    def _do_transcribe(self, audio) -> str:
        fn = self._transcribe
        if fn is None:
            from jarvis.voice import local_stt
            fn = local_stt.transcribe
        result = fn(audio) or {}
        return str(result.get("text") or "").strip()

    def _run(self) -> None:
        import numpy as np
        self._log("SYS: Offline voice active — listening locally (Gemini Live is unavailable).")
        try:
            with self._open_stream() as stream:
                while not self._stop.is_set():
                    block, _ = stream.read(BLOCK)
                    block = np.asarray(block, dtype="float32").reshape(-1)
                    if self._is_speaking():
                        # Never transcribe JARVIS's own voice from the speakers.
                        self.cutter.reset()
                        continue
                    if not self._is_awake():
                        self.cutter.reset()
                        if self._wake_feed is not None:
                            try:
                                self._wake_feed((block * 32767).clip(-32768, 32767).astype("int16"))
                            except Exception:
                                failsoft.suppress("voice.offline_loop:wake_feed")
                        continue
                    audio = self.cutter.push(block)
                    if audio is None:
                        continue
                    self._handle_utterance(audio)
        except Exception as exc:
            if not self._stop.is_set():
                self._log(f"ERR: Offline voice stopped ({type(exc).__name__}: {exc}).")
        finally:
            self._log("SYS: Offline voice stopped.")

    def _handle_utterance(self, audio) -> None:
        started = time.monotonic()
        try:
            text = self._do_transcribe(audio)
        except Exception as exc:
            self._log(f"ERR: Offline speech-to-text failed ({type(exc).__name__}).")
            return
        if not text or self._stop.is_set():
            return
        self._log(f"YOU (offline): {text}  [{time.monotonic() - started:.1f}s STT]")
        try:
            self._submit(text)
        except Exception:
            failsoft.suppress("voice.offline_loop:submit")


# ── local TTS for spoken fallback answers ──────────────────────────────────
def _piper_ready(cfg: dict) -> bool:
    import importlib.util
    if importlib.util.find_spec("piper") is None:
        return False
    try:
        from jarvis.core.tts import PiperTTSEngine
        voice = cfg.get("tts_voice") if cfg.get("tts_engine") == "piper" else ""
        voice = voice or os.environ.get("JARVIS_PIPER_VOICE", "") or PiperTTSEngine.DEFAULT_VOICE
        return PiperTTSEngine(voice=voice).model_path().exists()
    except Exception:
        return False


def pick_local_tts(config: Optional[dict] = None):
    """Return a TTSPlayer that works without Gemini, or None.

    Order: ``JARVIS_OFFLINE_TTS`` if set, then Piper (if a voice is downloaded),
    Kokoro (fully local), then edge-tts when the network is allowed. ``config`` may carry tts_voice/tts_speed.
    """
    import importlib.util

    from jarvis.core import privacy
    from jarvis.core.tts import create_tts_player

    cfg = dict(config or {})
    wanted = str(os.environ.get("JARVIS_OFFLINE_TTS", "")).strip().lower()
    order = [wanted] if wanted else []
    order += ["piper", "kokoro", "edgetts"]
    for name in order:
        if name == "kokoro" and importlib.util.find_spec("kokoro") is None:
            continue
        if name == "piper" and not _piper_ready(cfg):
            continue
        if name == "edgetts" and (privacy.offline_enabled() or importlib.util.find_spec("edge_tts") is None):
            continue
        if name not in {"piper", "kokoro", "edgetts"}:
            continue
        engine_cfg = {"tts_engine": name}
        if name == "piper" and os.environ.get("JARVIS_PIPER_VOICE"):
            engine_cfg["tts_voice"] = os.environ["JARVIS_PIPER_VOICE"]
        if name == cfg.get("tts_engine"):
            engine_cfg.update({k: v for k, v in cfg.items() if k.startswith("tts_")})
        try:
            return create_tts_player(engine_cfg)
        except Exception:
            failsoft.suppress("voice.offline_loop:pick_local_tts")
    return None
