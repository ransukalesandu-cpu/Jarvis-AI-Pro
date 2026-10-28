"""Screen understanding: cloud vision with local OCR and honest uncertainty.

Three sources are combined, cheapest first:

1. **Accessibility tree** (``agent.accessibility``) — exact control names, no
   upload at all. Available on Windows (UI Automation via pywinauto) and on some
   Linux desktops (AT-SPI). Always preferred for *acting*.
2. **Local OCR** (``actions.screen_ocr``, Tesseract) — reads text without
   sending a pixel anywhere. Used for "read what is on screen" and as a fallback
   when a vision provider is offline.
3. **Cloud vision** — Gemini (default, same key as Live) or an OpenAI-compatible
   vision model. Used for layout, dialogs, errors and "what is this app doing".

The result is one :class:`ScreenObservation` with an explicit ``confidence`` and
``uncertain`` flag. When only OCR was available the description says so, because
an assistant that *sounds* sure about a screen it could not see is worse than one
that admits it could not look.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agent.models import StepKind  # noqa: F401  (re-exported for callers' typing)
from agent.screen_capture import Screenshot, ScreenCapture, ScreenCaptureError
from agent.store import redact

logger = logging.getLogger("Jarvis.Agent.Vision")

_MAX_ELEMENTS = 12


class ScreenVisionError(RuntimeError):
    """No way to see the screen succeeded. Message is safe to speak."""


# ── result types ─────────────────────────────────────────────────────────────

@dataclass
class ElementTarget:
    """A clickable/typeable target located on screen."""

    label: str
    x: int
    y: int
    confidence: float = 0.0
    source: str = "vision"          # accessibility | ocr | vision
    bounds: tuple[int, int, int, int] | None = None
    uncertain: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "x": self.x, "y": self.y,
            "confidence": round(float(self.confidence), 3),
            "source": self.source, "bounds": self.bounds,
            "uncertain": self.uncertain,
        }


@dataclass
class ScreenObservation:
    """What JARVIS believes is on screen right now."""

    description: str = ""
    visible_text: str = ""
    active_app: str = ""
    dialog: str = ""
    error_text: str = ""
    elements: list[ElementTarget] = field(default_factory=list)
    provider: str = ""
    confidence: float = 0.0
    uncertain: bool = True
    ocr_available: bool = False
    provider_errors: list[str] = field(default_factory=list)
    captured_at: float = field(default_factory=time.time)
    image_size: tuple[int, int] = (0, 0)

    def summary(self, *, max_chars: int = 700) -> str:
        parts = [self.description or "No visual description available."]
        if self.active_app:
            parts.append(f"Active app: {self.active_app}")
        if self.dialog:
            parts.append(f"Dialog: {self.dialog}")
        if self.error_text:
            parts.append(f"Visible error: {self.error_text}")
        if self.visible_text:
            parts.append(f"Visible text: {self.visible_text[:400]}")
        if self.uncertain:
            parts.append("(Interpretation uncertain — ask before acting on details.)")
        text = "\n".join(parts)
        return text[:max_chars]


@dataclass
class VerifyResult:
    """Answer to "did that action do what we expected?"."""

    ok: bool
    confidence: float
    reason: str
    observation: ScreenObservation | None = None
    provider: str = ""


# ── providers ────────────────────────────────────────────────────────────────

class VisionProvider(Protocol):  # pragma: no cover - structural typing
    name: str

    def available(self) -> bool: ...

    def analyze(self, shot: Screenshot, prompt: str) -> dict[str, Any]: ...


_JSON_CONTRACT = (
    "Reply with a single JSON object and nothing else, using exactly these keys:\n"
    '{"summary": str, "visible_text": str, "active_app": str, "dialog": str, '
    '"error": str, "confidence": number between 0 and 1, '
    '"elements": [{"label": str, "x_pct": number 0-1, "y_pct": number 0-1, '
    '"confidence": number 0-1}]}\n'
    "Use empty strings when a field does not apply. x_pct/y_pct are the centre of "
    "the element as a fraction of image width/height. Never invent UI elements that "
    "are not visible; lower 'confidence' when the screen is unclear."
)


def _key_from_config(name: str, env: str) -> str:
    value = os.environ.get(env, "").strip()
    if value:
        return value
    try:
        from memory.config_manager import load_api_keys

        return str(load_api_keys().get(name) or "").strip()
    except Exception:
        return ""


def _extract_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ScreenVisionError("The vision provider returned an empty response.")
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ScreenVisionError("The vision provider returned malformed JSON.") from exc
    raise ScreenVisionError("The vision provider did not return JSON.")


class GeminiVisionProvider:
    """Gemini vision via the same google-genai dependency Live already uses."""

    name = "gemini"

    def __init__(self, model: str = "", *, client_factory: Callable[[str], Any] | None = None,
                 timeout_s: float = 45.0):
        self.model = model or os.environ.get("JARVIS_VISION_MODEL", "gemini-2.5-flash")
        self._client_factory = client_factory
        self.timeout_s = timeout_s

    def api_key(self) -> str:
        return _key_from_config("gemini_api_key", "GEMINI_API_KEY")

    def available(self) -> bool:
        if not self.api_key():
            return False
        try:
            import google.genai  # noqa: F401
        except ImportError:
            return False
        return True

    def _client(self, api_key: str):
        if self._client_factory is not None:
            return self._client_factory(api_key)
        from google import genai
        from google.genai import types

        options = None
        try:
            options = types.HttpOptions(timeout=int(self.timeout_s * 1000))
        except Exception:
            options = None
        if options is not None:
            return genai.Client(api_key=api_key, http_options=options)
        return genai.Client(api_key=api_key)

    def analyze(self, shot: Screenshot, prompt: str) -> dict[str, Any]:
        client = self._client(self.api_key())
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=[{
                    "inline_data": {"mime_type": shot.mime, "data": shot.data},
                }, f"{prompt}\n\n{_JSON_CONTRACT}"],
                config={"response_mime_type": "application/json",
                        "temperature": 0.1},
            )
        except Exception as exc:
            raise ScreenVisionError(_provider_error("Gemini vision", exc)) from exc
        return _extract_json(getattr(response, "text", ""))


class OpenAIVisionProvider:
    """Optional second opinion through an OpenAI-compatible vision endpoint."""

    name = "openai"

    def __init__(self, model: str = "", *, client_factory: Callable[[str], Any] | None = None,
                 timeout_s: float = 45.0):
        self.model = model or os.environ.get("JARVIS_VISION_OPENAI_MODEL", "gpt-4o-mini")
        self._client_factory = client_factory
        self.timeout_s = timeout_s

    def api_key(self) -> str:
        return os.environ.get("OPENAI_API_KEY", "").strip()

    def available(self) -> bool:
        if not self.api_key():
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def _client(self, api_key: str):
        if self._client_factory is not None:
            return self._client_factory(api_key)
        from openai import OpenAI

        return OpenAI(api_key=api_key, timeout=self.timeout_s)

    def analyze(self, shot: Screenshot, prompt: str) -> dict[str, Any]:
        import base64

        client = self._client(self.api_key())
        image = base64.b64encode(shot.data).decode("ascii")
        try:
            completion = client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"{prompt}\n\n{_JSON_CONTRACT}"},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{shot.mime};base64,{image}",
                            "detail": "low",
                        }},
                    ],
                }],
                temperature=0.1,
            )
            text = completion.choices[0].message.content
        except Exception as exc:
            raise ScreenVisionError(_provider_error("OpenAI vision", exc)) from exc
        return _extract_json(text)


def default_providers() -> list[VisionProvider]:
    """Configured providers, in preference order. Empty when no key is set."""
    providers: list[VisionProvider] = []
    gemini = GeminiVisionProvider()
    if gemini.available():
        providers.append(gemini)
    openai_provider = OpenAIVisionProvider()
    if openai_provider.available():
        providers.append(openai_provider)
    return providers


# ── OCR ──────────────────────────────────────────────────────────────────────

class OcrEngine:
    """Thin wrapper over ``actions.screen_ocr`` with an injectable reader."""

    def __init__(self, reader: Callable[[], list[dict]] | None = None,
                 matcher: Callable[[str, list[dict]], list[dict]] | None = None):
        self._reader = reader
        self._matcher = matcher
        self._failure_reason = ""

    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError as exc:
            self._failure_reason = f"OCR dependencies missing: {exc.name}"
            return False
        if self._reader is not None:
            return True
        try:
            import shutil

            if shutil.which("tesseract"):
                return True
            for candidate in (
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                "/opt/homebrew/bin/tesseract",
                "/usr/local/bin/tesseract",
                "/usr/bin/tesseract",
            ):
                if os.path.isfile(candidate):
                    return True
        except Exception:
            pass
        self._failure_reason = "the Tesseract OCR engine is not installed"
        return False

    @property
    def failure_reason(self) -> str:
        return self._failure_reason

    def read_words(self) -> list[dict]:
        if self._reader is not None:
            try:
                return list(self._reader() or [])
            except Exception as exc:
                raise ScreenVisionError(redact(f"OCR failed: {exc}", 300)) from exc
        try:
            from actions.screen_ocr import read_screen_words

            return list(read_screen_words() or [])
        except Exception as exc:
            raise ScreenVisionError(redact(f"OCR failed: {exc}", 300)) from exc

    def find(self, label: str) -> list[ElementTarget]:
        words = self.read_words()
        matches: list[dict] = []
        if self._matcher is not None:
            matches = list(self._matcher(label, words) or [])
        else:
            from actions.screen_ocr import find_text_matches

            matches = list(find_text_matches(label, words) or [])
        return [
            ElementTarget(
                label=label,
                x=int(match.get("x", 0)),
                y=int(match.get("y", 0)),
                confidence=float(match.get("confidence", 0.0)) / 100.0,
                source="ocr",
                bounds=None,
                uncertain=False,
            )
            for match in matches
        ]

    def text(self, limit: int = 2400) -> str:
        words = self.read_words()
        return " ".join(str(word.get("text") or "") for word in words)[:limit]


# ── the facade ───────────────────────────────────────────────────────────────

class ScreenVision:
    """Capture → understand → locate → verify, with graceful degradation."""

    def __init__(
        self,
        capture: ScreenCapture,
        *,
        providers: list[VisionProvider] | None = None,
        ocr: OcrEngine | None = None,
        accessibility: Any | None = None,
        logger_: Callable[[str], None] | None = None,
    ):
        self.capture = capture
        self.providers = list(providers) if providers is not None else None
        self.ocr = ocr if ocr is not None else OcrEngine()
        self.accessibility = accessibility
        self._log = logger_ or (lambda message: logger.info("%s", message))
        self.last_observation: ScreenObservation | None = None
        self.provider_used = ""

    # -- helpers -----------------------------------------------------------
    def _resolved_providers(self) -> list[VisionProvider]:
        if self.providers is not None:
            return list(self.providers)
        self.providers = default_providers()
        return list(self.providers)

    def capabilities(self) -> dict[str, Any]:
        providers = self._resolved_providers()
        return {
            "vision": [provider.name for provider in providers if provider.available()],
            "ocr": self.ocr.available(),
            "ocr_reason": "" if self.ocr.available() else self.ocr.failure_reason,
            "accessibility": bool(self.accessibility and self.accessibility.available()),
            "capture": bool(self.capture and not self.capture.paused),
        }

    # -- observation -------------------------------------------------------
    def observe(self, question: str = "", *, include_ocr: bool = True,
                force_capture: bool = False) -> ScreenObservation:
        try:
            shot = self.capture.capture(force=force_capture)
        except ScreenCaptureError as exc:
            raise ScreenVisionError(str(exc)) from exc

        prompt = question.strip() or (
            "Describe this desktop screenshot for a voice assistant: the active "
            "application, any dialog, any visible error message, and the main "
            "clickable controls."
        )
        observation = ScreenObservation(image_size=(shot.width, shot.height),
                                        ocr_available=self.ocr.available())
        for provider in self._resolved_providers():
            if not provider.available():
                continue
            try:
                data = provider.analyze(shot, prompt)
            except ScreenVisionError as exc:
                observation.provider_errors.append(str(exc))
                continue
            except Exception as exc:  # provider SDK surprises
                observation.provider_errors.append(
                    _provider_error(provider.name, exc, include_type=True)
                )
                continue
            self._apply_vision(observation, data, shot, provider.name)
            break

        if include_ocr and not observation.visible_text and self.ocr.available():
            try:
                observation.visible_text = self.ocr.text()
            except ScreenVisionError as exc:
                observation.provider_errors.append(str(exc))

        if observation.provider:
            observation.uncertain = observation.confidence < 0.55
            observation.description = observation.description or (
                f"Screen observed with {observation.provider}."
            )
        else:
            # No cloud provider: be explicit rather than silently guessing.
            observation.uncertain = True
            observation.confidence = 0.3 if observation.visible_text else 0.0
            if observation.visible_text:
                observation.description = (
                    "No vision provider is configured, so this is OCR text only; "
                    "layout, dialogs and icons were not interpreted."
                )
            else:
                raise ScreenVisionError(
                    "I cannot see the screen: no vision provider is configured "
                    + ("and OCR is unavailable. " if not self.ocr.available()
                       else "and OCR returned no text. ")
                    + _configure_hint()
                )

        shot.release()
        self.last_observation = observation
        return observation

    @staticmethod
    def _apply_vision(observation: ScreenObservation, data: dict[str, Any],
                      shot: Screenshot, provider_name: str) -> None:
        if not isinstance(data, dict):
            raise ScreenVisionError(f"{provider_name} returned an unexpected payload.")
        observation.provider = provider_name
        observation.description = str(data.get("summary") or "").strip()
        observation.visible_text = str(data.get("visible_text") or "").strip()
        observation.active_app = str(data.get("active_app") or "").strip()
        observation.dialog = str(data.get("dialog") or "").strip()
        observation.error_text = str(data.get("error") or "").strip()
        try:
            observation.confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            observation.confidence = 0.5
        elements: list[ElementTarget] = []
        for item in (data.get("elements") or [])[:_MAX_ELEMENTS]:
            if not isinstance(item, dict):
                continue
            try:
                x_pct = float(item.get("x_pct"))
                y_pct = float(item.get("y_pct"))
            except (TypeError, ValueError):
                continue
            if not (0.0 <= x_pct <= 1.0 and 0.0 <= y_pct <= 1.0):
                continue
            x, y = shot.percent_to_screen(x_pct, y_pct)
            try:
                confidence = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            elements.append(ElementTarget(
                label=str(item.get("label") or "control")[:80],
                x=x, y=y,
                confidence=max(0.0, min(1.0, confidence)),
                source="vision",
                uncertain=confidence < 0.5,
            ))
        observation.elements = elements

    # -- element location --------------------------------------------------
    def find(self, label: str, *, allow_ocr: bool = True,
             min_confidence: float = 0.35) -> list[ElementTarget]:
        """Locate a control, preferring accessibility over OCR over pixels."""
        wanted = str(label or "").strip()
        if not wanted:
            raise ScreenVisionError("No element label was given.")

        targets: list[ElementTarget] = []
        if self.accessibility is not None and self.accessibility.available():
            try:
                targets = list(self.accessibility.find(wanted) or [])
            except Exception as exc:
                self._log(f"Agent accessibility lookup failed: {redact(exc, 200)}")
                targets = []
        if targets:
            return targets

        if allow_ocr and self.ocr.available():
            try:
                targets = self.ocr.find(wanted)
            except ScreenVisionError as exc:
                self._log(f"Agent OCR lookup failed: {redact(exc, 200)}")
                targets = []
            if targets:
                return targets

        observation = self.observe(f"Locate the control labelled {wanted!r}.")
        matches = [
            element for element in observation.elements
            if _normalise(wanted) in _normalise(element.label)
            or _normalise(element.label) in _normalise(wanted)
        ]
        if not matches:
            matches = observation.elements[:1] if observation.elements else []
        return [match for match in matches if match.confidence >= min_confidence]

    # -- verification ------------------------------------------------------
    def verify(self, expectation: str, *, before: ScreenObservation | None = None) -> VerifyResult:
        """Ask a vision model whether the expectation now holds on screen."""
        expected = str(expectation or "").strip()
        if not expected:
            return VerifyResult(False, 0.0, "No expectation was provided to verify.")
        try:
            shot = self.capture.capture(force=True)
        except ScreenCaptureError as exc:
            return VerifyResult(False, 0.0, str(exc))

        prompt = (
            f"Check this screenshot and decide whether the following is true: {expected!r}. "
            "Judge only what is visible. If you cannot tell, set confidence low and "
            "explain why. Put the answer in 'summary' prefixed with TRUE: or FALSE:."
        )
        for provider in self._resolved_providers():
            if not provider.available():
                continue
            try:
                data = provider.analyze(shot, prompt)
            except Exception as exc:
                logger.info("Vision verify failed: %s", redact(exc, 200))
                continue
            summary = str(data.get("summary") or "")
            confidence = _confidence(data)
            ok = bool(re.match(r"\s*true\b", summary, re.IGNORECASE))
            if not ok and re.match(r"\s*false\b", summary, re.IGNORECASE):
                ok = False
            elif not summary:
                # Fall back to the model's own verdict field when present.
                ok = bool(data.get("ok", False))
            shot.release()
            return VerifyResult(ok, confidence, summary or expected, None, provider.name)

        shot.release()
        if self.ocr.available():
            try:
                text = self.ocr.text()
                lowered, needle = text.casefold(), expected.casefold()
                if needle and needle in lowered:
                    return VerifyResult(True, 0.5,
                                        "The expected text is present on screen (OCR).",
                                        None, "ocr")
                return VerifyResult(False, 0.3,
                                    "The expected text was not found by OCR; this is "
                                    "weak evidence because layout was not analysed.",
                                    None, "ocr")
            except ScreenVisionError as exc:
                return VerifyResult(False, 0.0, str(exc))
        return VerifyResult(
            False, 0.0,
            "I cannot verify that on screen: no vision provider is configured. "
            + _configure_hint(),
        )

    # -- read-only extras --------------------------------------------------
    def read_text(self) -> str:
        if self.ocr.available():
            try:
                text = self.ocr.text()
                if text.strip():
                    return text
            except ScreenVisionError:
                pass
        return self.observe("Transcribe all readable text on this screen.").visible_text

    def describe(self) -> str:
        return self.observe().summary()


def _confidence(data: dict[str, Any]) -> float:
    try:
        return max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        return 0.5


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _provider_error(name: str, exc: BaseException, *, include_type: bool = False) -> str:
    detail = f"{type(exc).__name__}: {exc}" if include_type else str(exc)
    detail = redact(detail, 300)
    lowered = detail.casefold()
    if "api key" in lowered or "401" in lowered or "unauthorized" in lowered:
        return f"{name} rejected the configured API key."
    if "quota" in lowered or "429" in lowered or "rate limit" in lowered:
        return f"{name} is rate-limited right now."
    if "timed out" in lowered or "timeout" in lowered:
        return f"{name} timed out."
    if "connect" in lowered or "network" in lowered or "dns" in lowered:
        return f"{name} could not be reached."
    return f"{name} failed: {detail[:200]}"


def _configure_hint() -> str:
    return (
        "Add a Gemini API key in JARVIS settings (or set GEMINI_API_KEY) to enable "
        "screen vision, and install Tesseract plus pytesseract for local OCR."
    )


class ContinuousObserver:
    """Opt-in, bounded background observation.

    Off by default: the agent captures on demand. When the owner explicitly asks
    for "watch the screen", this polls at a fixed interval, keeps at most
    ``max_frames`` observations, and stops on demand or when captures start
    failing (a locked screen must not spin forever). It runs on its own daemon
    thread and never touches Qt or the audio path.
    """

    def __init__(
        self,
        vision: ScreenVision,
        *,
        interval_s: float = 15.0,
        max_frames: int = 120,
        on_observation: Callable[[ScreenObservation], None] | None = None,
        logger_: Callable[[str], None] | None = None,
    ):
        import threading  # local: keeps the module import surface tiny

        self.vision = vision
        self.interval_s = max(2.0, float(interval_s))
        self.max_frames = max(1, int(max_frames))
        self.on_observation = on_observation
        self._log = logger_ or (lambda message: None)
        self._stop = threading.Event()
        self._thread: Any = None
        self.frames = 0
        self.last_error = ""

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        import threading

        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="jarvis-screen-observer", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        self._thread = None

    def _loop(self) -> None:
        consecutive_failures = 0
        while not self._stop.is_set() and self.frames < self.max_frames:
            if self._stop.wait(self.interval_s):
                return
            try:
                observation = self.vision.observe("Observe the screen for changes.",
                                                  force_capture=True)
            except Exception as exc:
                consecutive_failures += 1
                self.last_error = redact(exc, 300)
                self._log(f"Continuous observation skipped: {self.last_error}")
                if consecutive_failures >= 3:
                    self._log("Continuous observation stopped after three failures.")
                    return
                continue
            consecutive_failures = 0
            self.frames += 1
            callback = self.on_observation
            if callback is not None:
                try:
                    callback(observation)
                except Exception:
                    continue
