"""On-demand, resource-safe desktop capture.

Design notes that matter in practice:

* **One frame per request.** A monitoring loop is opt-in (``set_continuous`` on
  the vision bridge), and even then the minimum interval is enforced here, so a
  voice command cannot turn into a 30 fps upload.
* **Small uploads.** Frames are downscaled to a configurable maximum and encoded
  as JPEG before they reach a cloud provider. 1280×720 at quality 78 is roughly
  120 KB for a typical desktop — the same order as the existing
  ``actions/screen_processor._compress`` helper, which stays untouched for the
  Live-session path.
* **Coordinates survive scaling.** :class:`Screenshot` knows the source monitor
  bounds and the scale factor, so a normalised element position returned by a
  vision model can be converted back to real screen pixels.
* **No leaking handles.** ``mss`` instances are created per capture inside a
  context manager (the library is not thread-safe when shared), and
  :meth:`ScreenCapture.close` drops the cached frame.
* **Owner control.** ``set_paused(True)`` makes every capture raise, which is
  what the "stop looking at my screen" switch and the privacy lock use.
"""

from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from core import failsoft


class ScreenCaptureError(RuntimeError):
    """Capture is unavailable, paused, or failed. Message is user-safe."""


@dataclass(frozen=True)
class Monitor:
    index: int
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def from_mss(cls, position: int, data: dict[str, Any]) -> "Monitor":
        return cls(
            index=position,
            left=int(data.get("left", 0)),
            top=int(data.get("top", 0)),
            width=max(1, int(data.get("width", 1))),
            height=max(1, int(data.get("height", 1))),
        )


@dataclass
class Screenshot:
    """One captured frame plus everything needed to act on its coordinates."""

    data: bytes
    mime: str
    width: int
    height: int
    monitor: Monitor
    source_width: int
    source_height: int
    captured_at: float = field(default_factory=time.time)

    @property
    def scale_x(self) -> float:
        return self.width / float(self.source_width or 1)

    @property
    def scale_y(self) -> float:
        return self.height / float(self.source_height or 1)

    def percent_to_screen(self, x_pct: float, y_pct: float) -> tuple[int, int]:
        """Map a 0..1 position inside this frame to absolute screen pixels."""
        x = int(round(float(x_pct) * self.width))
        y = int(round(float(y_pct) * self.height))
        return self.image_to_screen(x, y)

    def image_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """Map a pixel inside this (possibly scaled) frame to screen pixels."""
        unscaled_x = int(round(int(x) / (self.scale_x or 1)))
        unscaled_y = int(round(int(y) / (self.scale_y or 1)))
        return (
            self.monitor.left + max(0, min(unscaled_x, self.monitor.width - 1)),
            self.monitor.top + max(0, min(unscaled_y, self.monitor.height - 1)),
        )

    def release(self) -> None:
        """Drop the encoded buffer so a large frame is not kept alive."""
        self.data = b""


class CaptureBackend(Protocol):  # pragma: no cover - structural typing only
    def monitors(self) -> list[Monitor]: ...

    def grab(self, monitor: Monitor) -> tuple[bytes, int, int]:
        """Return raw RGB bytes, width, height for the requested monitor."""
        ...

    def close(self) -> None: ...


class MssBackend:
    """Default backend: mss on Windows/macOS/Linux (X11 and Wayland portals)."""

    name = "mss"

    def monitors(self) -> list[Monitor]:
        mss = _import_mss()
        try:
            with mss.mss() as capture:
                return [
                    Monitor.from_mss(index, data)
                    for index, data in enumerate(capture.monitors)
                ]
        except Exception as exc:  # pragma: no cover - depends on host display
            raise ScreenCaptureError(_friendly(exc)) from exc

    def grab(self, monitor: Monitor) -> tuple[bytes, int, int]:
        mss = _import_mss()
        try:
            with mss.mss() as capture:
                shot = capture.grab({
                    "left": monitor.left, "top": monitor.top,
                    "width": monitor.width, "height": monitor.height,
                })
                return bytes(shot.rgb), int(shot.width), int(shot.height)
        except Exception as exc:  # pragma: no cover - depends on host display
            raise ScreenCaptureError(_friendly(exc)) from exc

    def close(self) -> None:  # nothing is retained between captures
        return


class PillowBackend:
    """Fallback: Pillow's ImageGrab (no mss dependency, slower, primary only)."""

    name = "pillow"

    def monitors(self) -> list[Monitor]:
        try:
            from PIL import ImageGrab
        except ImportError as exc:
            raise ScreenCaptureError(
                "Pillow is not installed, so screen capture is unavailable."
            ) from exc
        try:
            left, top, right, bottom = ImageGrab.grab(all_screens=True).getbbox() or (0, 0, 1, 1)
        except Exception:
            try:
                size = ImageGrab.grab().size
            except Exception as exc:  # pragma: no cover - depends on host display
                raise ScreenCaptureError(_friendly(exc)) from exc
            left, top, right, bottom = 0, 0, size[0], size[1]
        return [Monitor(0, 0, 0, max(1, right - left), max(1, bottom - top))]

    def grab(self, monitor: Monitor) -> tuple[bytes, int, int]:
        try:
            from PIL import ImageGrab
        except ImportError as exc:
            raise ScreenCaptureError(
                "Pillow is not installed, so screen capture is unavailable."
            ) from exc
        try:
            image = ImageGrab.grab(bbox=(
                monitor.left, monitor.top,
                monitor.left + monitor.width, monitor.top + monitor.height,
            ))
        except Exception as exc:  # pragma: no cover - depends on host display
            raise ScreenCaptureError(_friendly(exc)) from exc
        if image.mode != "RGB":
            image = image.convert("RGB")
        return image.tobytes(), int(image.width), int(image.height)

    def close(self) -> None:
        return


class ScreenCapture:
    """Capture the selected monitor, scaled and JPEG-encoded, on demand."""

    def __init__(
        self,
        backend: Any | None = None,
        *,
        monitor: int = 1,
        region: tuple[int, int, int, int] | None = None,
        max_width: int = 1280,
        max_height: int = 720,
        jpeg_quality: int = 78,
        min_interval_s: float = 1.0,
        encoder: Callable[[bytes, int, int, int, int], "EncodedImage"] | None = None,
    ):
        self._backend = backend
        self.monitor_index = int(monitor)
        self.region = region
        self.max_width = max(320, int(max_width))
        self.max_height = max(200, int(max_height))
        self.jpeg_quality = max(40, min(95, int(jpeg_quality)))
        self.min_interval_s = max(0.0, float(min_interval_s))
        self._encoder = encoder
        self._cached: Screenshot | None = None
        self._paused = False
        self._lock = threading.RLock()
        self.last_error = ""
        self.capture_count = 0

    # -- configuration -----------------------------------------------------
    def backend(self) -> Any:
        if self._backend is None:
            self._backend = self._resolve_backend()
        return self._backend

    @staticmethod
    def _resolve_backend() -> Any:
        try:
            import mss  # noqa: F401

            return MssBackend()
        except ImportError:
            pass
        try:
            from PIL import ImageGrab  # noqa: F401

            return PillowBackend()
        except ImportError as exc:
            raise ScreenCaptureError(
                "Screen capture needs the 'mss' (or Pillow) package. "
                "Install JARVIS's requirements, then retry."
            ) from exc

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = bool(paused)
            if self._paused:
                self._release_cache()

    @property
    def paused(self) -> bool:
        return self._paused

    def set_encoder(self, encoder: Callable[[bytes, int, int, int, int], "EncodedImage"]) -> None:
        """Inject an encoder (tests use this to avoid needing Pillow)."""
        self._encoder = encoder
        self._release_cache()

    # -- monitors ----------------------------------------------------------
    def monitors(self) -> list[Monitor]:
        try:
            return list(self.backend().monitors())
        except ScreenCaptureError:
            raise
        except Exception as exc:
            raise ScreenCaptureError(_friendly(exc)) from exc

    def select_monitor(self, index: int) -> None:
        self.monitor_index = max(0, int(index))
        self._release_cache()

    def _monitor(self) -> Monitor:
        monitors = self.monitors()
        if not monitors:
            raise ScreenCaptureError("No display is available to capture.")
        # Index 0 is the union of all screens in mss; prefer a real screen.
        real = [m for m in monitors if m.index > 0] or monitors
        chosen = next((m for m in real if m.index == self.monitor_index), None)
        if chosen is None:
            chosen = real[0]
        if self.region:
            left, top, width, height = self.region
            return Monitor(
                index=chosen.index,
                left=chosen.left + int(left),
                top=chosen.top + int(top),
                width=max(1, min(int(width), chosen.width - int(left))),
                height=max(1, min(int(height), chosen.height - int(top))),
            )
        return chosen

    # -- capture -----------------------------------------------------------
    def capture(self, *, force: bool = False) -> Screenshot:
        with self._lock:
            if self._paused:
                raise ScreenCaptureError(
                    "Screen access is paused by the owner. Resume it before asking "
                    "JARVIS to look at the screen."
                )
            now = time.time()
            cached = self._cached
            if (
                cached is not None
                and not force
                and self.min_interval_s
                and (now - cached.captured_at) < self.min_interval_s
            ):
                return cached
            monitor = self._monitor()
            try:
                raw, width, height = self.backend().grab(monitor)
            except ScreenCaptureError as exc:
                self.last_error = str(exc)
                raise
            except Exception as exc:
                self.last_error = _friendly(exc)
                raise ScreenCaptureError(self.last_error) from exc
            encoded = self._encode(raw, width, height)
            shot = Screenshot(
                data=encoded.data,
                mime=encoded.mime,
                width=encoded.width,
                height=encoded.height,
                monitor=monitor,
                source_width=width,
                source_height=height,
                captured_at=now,
            )
            self._cached = shot
            self.capture_count += 1
            self.last_error = ""
            return shot

    def _encode(self, raw: bytes, width: int, height: int) -> "EncodedImage":
        if self._encoder is not None:
            return self._encoder(raw, width, height, self.max_width, self.max_height)
        try:
            from PIL import Image
        except ImportError as exc:
            raise ScreenCaptureError(
                "Pillow is required to compress screenshots before upload."
            ) from exc
        try:
            image = Image.frombytes("RGB", (width, height), raw)
            scale = min(
                1.0, self.max_width / float(width), self.max_height / float(height)
            )
            if scale < 1.0:
                image = image.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    Image.BILINEAR,
                )
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=self.jpeg_quality, optimize=False)
            data = buffer.getvalue()
            size = image.size
            image.close()
            return EncodedImage(data=data, mime="image/jpeg", width=size[0], height=size[1])
        except ScreenCaptureError:
            raise
        except Exception as exc:  # pragma: no cover - encoder internals
            raise ScreenCaptureError(f"Screenshot encoding failed: {_friendly(exc)}") from exc

    # -- lifecycle ---------------------------------------------------------
    def _release_cache(self) -> None:
        if self._cached is not None:
            self._cached.release()
            self._cached = None

    def close(self) -> None:
        with self._lock:
            self._release_cache()
            backend, self._backend = self._backend, None
        if backend is not None:
            try:
                backend.close()
            except Exception:
                failsoft.suppress("agent.screen_capture:close")


@dataclass(frozen=True)
class EncodedImage:
    data: bytes
    mime: str
    width: int
    height: int


def _import_mss():
    try:
        import mss  # noqa: F811

        return mss
    except ImportError as exc:
        raise ScreenCaptureError(
            "The 'mss' package is not installed, so screen capture is unavailable."
        ) from exc


def _friendly(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.casefold()
    if "display" in lowered or "xgetimage" in lowered or "xlib" in lowered:
        return (
            "Screen capture failed because no accessible display is available. "
            "On Linux this usually means no X11 session (or a missing portal)."
        )
    if "permission" in lowered or "denied" in lowered:
        return (
            "Screen capture was denied by the operating system. Grant screen-recording "
            "permission to JARVIS (System Settings → Privacy) and retry."
        )
    try:
        from agent.store import redact

        return redact(text, 500)
    except Exception:  # pragma: no cover
        return text[:500]
