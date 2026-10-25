"""
Jarvis AI Pro - Self-Healing System v2
Watches hardware peripherals, memory limits, and subprocess crashes.
Offers approval-gated auto-recovery callbacks for the PyQt HUD.
"""

import os
import psutil
import threading
import time
import logging
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger("Jarvis.SelfHealing")


class SelfHealingSentinel:
    def __init__(self, approval_callback: Optional[Callable[[str, str], bool]] = None):
        """
        :param approval_callback: GUI callback function (title, details) -> bool.
                                   If None, runs in autonomous safe mode.
        """
        self.approval_callback = approval_callback
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self.health_metrics: Dict[str, Any] = {
            "memory_usage_mb": 0,
            "audio_ok": True,
            "webengine_alive": True,
            "incident_count": 0
        }

    def start(self, interval_sec: float = 4.0):
        self.running = True
        self._thread = threading.Thread(target=self._sentinel_loop, args=(interval_sec,), daemon=True)
        self._thread.start()
        logger.info("[SELF-HEALING] Diagnostic sentinel online.")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _sentinel_loop(self, interval: float):
        while self.running:
            try:
                self._check_memory_threshold(limit_mb=1200)
                self._check_audio_subsystem()
            except Exception as e:
                logger.error(f"[SELF-HEALING] Health check error: {e}")
            time.sleep(interval)

    def _check_memory_threshold(self, limit_mb: float = 1200):
        process = psutil.Process(os.getpid())
        mem_mb = process.memory_info().rss / (1024 * 1024)
        self.health_metrics["memory_usage_mb"] = round(mem_mb, 1)

        if mem_mb > limit_mb:
            self.health_metrics["incident_count"] += 1
            title = "High Memory Alert"
            msg = f"JARVIS process memory ({mem_mb:.1f} MB) exceeded threshold ({limit_mb} MB). Run garbage collection?"
            
            if self._request_approval(title, msg):
                import gc
                gc.collect()
                logger.info("[SELF-HEALING] Garbage collection completed.")

    def _check_audio_subsystem(self):
        """Detects if microphone / speaker devices have been severed."""
        try:
            # Prefer sounddevice, which is already used by the main audio path.
            # PyAudio is an optional fallback for installations that lack it.
            import sounddevice as sd
            devices = sd.query_devices()
            if len(devices) == 0:
                self.health_metrics["audio_ok"] = False
                logger.warning("[SELF-HEALING] No audio I/O devices detected.")
            else:
                self.health_metrics["audio_ok"] = True
        except Exception:
            try:
                import pyaudio
                p = pyaudio.PyAudio()
                try:
                    count = p.get_device_count()
                finally:
                    p.terminate()
                self.health_metrics["audio_ok"] = (count > 0)
                if count == 0:
                    logger.warning("[SELF-HEALING] No audio I/O devices detected.")
            except Exception:
                # Do not mark audio healthy/unhealthy when neither backend
                # can query devices; the optional self-healing check must not
                # crash the main assistant.
                pass

    def _request_approval(self, title: str, details: str) -> bool:
        if self.approval_callback:
            return self.approval_callback(title, details)
        return True  # Autonomous default for non-destructive actions
