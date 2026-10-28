"""Screen capture, vision and computer-use tests with simulated desktops.

No real screen, mouse or cloud call is used: the capture backend, vision
provider, accessibility bridge and input backend are all injected doubles.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.computer_use import (
    ComputerUseConfig,
    ComputerUseController,
)
from agent.screen_capture import (
    EncodedImage,
    Monitor,
    ScreenCapture,
    ScreenCaptureError,
)
from agent.screen_vision import (
    ContinuousObserver,
    ElementTarget,
    OcrEngine,
    ScreenObservation,
    ScreenVision,
    ScreenVisionError,
    VerifyResult,
)


class FakeBackend:
    name = "fake"

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.grabs = 0
        self.closed = False

    def monitors(self):
        return [Monitor(0, 0, 0, 1920, 1080), Monitor(1, 0, 0, 1920, 1080)]

    def grab(self, monitor):
        if self.fail:
            raise ScreenCaptureError("Screen capture failed because no display is available.")
        self.grabs += 1
        return b"\x10" * (monitor.width * monitor.height * 3), monitor.width, monitor.height

    def close(self):
        self.closed = True


def half_scale_encoder(raw, width, height, max_width, max_height):
    return EncodedImage(b"jpeg-bytes", "image/jpeg", width // 2, height // 2)


class FakeProvider:
    name = "fake-vision"

    def __init__(self, payload=None, *, available=True, error=None):
        self.payload = payload or {}
        self._available = available
        self.error = error
        self.calls = 0
        self.prompts: list[str] = []

    def available(self):
        return self._available

    def analyze(self, shot, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.payload


class FakeAccessibility:
    def __init__(self, targets=None, available=True):
        self.targets = targets or []
        self._available = available
        self.queries: list[str] = []

    def available(self):
        return self._available

    def find(self, label):
        self.queries.append(label)
        return list(self.targets)


class FakeOcr:
    def __init__(self, available=True, text="", matches=None):
        self._available = available
        self._text = text
        self._matches = matches or []
        self.calls = 0

    def available(self):
        return self._available

    failure_reason = "not installed"

    def text(self, limit=2400):
        self.calls += 1
        if not self._available:
            raise ScreenVisionError("OCR unavailable")
        return self._text[:limit]

    def find(self, label):
        self.calls += 1
        if not self._available:
            raise ScreenVisionError("OCR unavailable")
        return list(self._matches)

    def read_words(self):
        return []


def make_capture(**kwargs) -> tuple[ScreenCapture, FakeBackend]:
    backend = FakeBackend()
    capture = ScreenCapture(backend, encoder=half_scale_encoder,
                            min_interval_s=kwargs.pop("min_interval_s", 0.0), **kwargs)
    return capture, backend


class ScreenCaptureTests(unittest.TestCase):
    def test_capture_and_coordinate_mapping(self):
        capture, backend = make_capture()
        shot = capture.capture()
        self.assertEqual(backend.grabs, 1)
        self.assertEqual((shot.width, shot.height), (960, 540))
        self.assertEqual((shot.source_width, shot.source_height), (1920, 1080))
        self.assertEqual(shot.percent_to_screen(0.5, 0.5), (960, 540))
        self.assertEqual(shot.percent_to_screen(0.0, 0.0), (0, 0))
        # The bottom-right pixel index is width-1/height-1, never width/height.
        self.assertEqual(shot.image_to_screen(960, 540), (1919, 1079))

    def test_min_interval_caches_and_force_recaptures(self):
        capture, backend = make_capture(min_interval_s=30.0)
        first = capture.capture()
        second = capture.capture()
        self.assertIs(first, second)
        self.assertEqual(backend.grabs, 1)
        capture.capture(force=True)
        self.assertEqual(backend.grabs, 2)

    def test_paused_capture_refuses_and_releases_cache(self):
        capture, _ = make_capture(min_interval_s=30.0)
        shot = capture.capture()
        capture.set_paused(True)
        self.assertEqual(shot.data, b"")
        with self.assertRaises(ScreenCaptureError) as ctx:
            capture.capture()
        self.assertIn("paused", str(ctx.exception).casefold())
        capture.set_paused(False)
        self.assertTrue(capture.capture().data)

    def test_backend_failure_is_wrapped(self):
        capture = ScreenCapture(FakeBackend(fail=True), encoder=half_scale_encoder)
        with self.assertRaises(ScreenCaptureError) as ctx:
            capture.capture()
        self.assertIn("display", str(ctx.exception))

    def test_close_releases_backend_and_frame(self):
        capture, backend = make_capture()
        shot = capture.capture()
        capture.close()
        self.assertTrue(backend.closed)
        self.assertEqual(shot.data, b"")
        self.assertIsNone(capture._cached)

    def test_region_and_monitor_selection(self):
        capture, backend = make_capture(region=(100, 50, 400, 300))
        shot = capture.capture()
        self.assertEqual((shot.monitor.left, shot.monitor.top), (100, 50))
        self.assertEqual((shot.monitor.width, shot.monitor.height), (400, 300))
        self.assertEqual(backend.grabs, 1)


class ScreenVisionTests(unittest.TestCase):
    def _vision(self, *, payload=None, providers=None, ocr=None, accessibility=None):
        capture, _ = make_capture()
        provider = FakeProvider(payload or {
            "summary": "A browser with a Save dialog.",
            "visible_text": "Save changes?",
            "active_app": "Chrome",
            "dialog": "Save changes?",
            "error": "",
            "confidence": 0.82,
            "elements": [
                {"label": "Save", "x_pct": 0.5, "y_pct": 0.5, "confidence": 0.9},
                {"label": "Cancel", "x_pct": 0.7, "y_pct": 0.5, "confidence": 0.8},
            ],
        })
        vision = ScreenVision(
            capture,
            providers=[provider] if providers is None else providers,
            ocr=ocr or FakeOcr(),
            accessibility=accessibility,
            logger_=lambda message: None,
        )
        return vision, provider

    def test_observation_is_parsed_and_coordinates_mapped(self):
        vision, provider = self._vision()
        observation = vision.observe("What is on screen?")
        self.assertEqual(provider.calls, 1)
        self.assertIn("Save dialog", observation.description)
        self.assertEqual(observation.active_app, "Chrome")
        self.assertEqual(observation.provider, "fake-vision")
        self.assertAlmostEqual(observation.confidence, 0.82)
        self.assertFalse(observation.uncertain)
        labels = [element.label for element in observation.elements]
        self.assertEqual(labels, ["Save", "Cancel"])
        self.assertEqual(observation.elements[0].x, 960)
        self.assertEqual(observation.elements[0].y, 540)
        self.assertEqual(observation.image_size, (960, 540))

    def test_low_confidence_marks_observation_uncertain(self):
        vision, _ = self._vision(payload={"summary": "Unclear blur.",
                                          "confidence": 0.2, "elements": []})
        self.assertTrue(vision.observe().uncertain)

    def test_provider_failure_falls_back_to_ocr_text(self):
        capture, _ = make_capture()
        failing = FakeProvider(error=ScreenVisionError("Gemini vision is rate-limited right now."))
        ocr = FakeOcr(text="Error: cannot save file")
        vision = ScreenVision(capture, providers=[failing], ocr=ocr,
                             logger_=lambda message: None)
        observation = vision.observe()
        self.assertTrue(observation.uncertain)
        self.assertEqual(observation.visible_text, "Error: cannot save file")
        self.assertTrue(observation.provider_errors)
        self.assertIn("OCR text only", observation.description)
        self.assertEqual(observation.provider, "")

    def test_no_provider_and_no_ocr_raises_actionable_error(self):
        capture, _ = make_capture()
        vision = ScreenVision(capture, providers=[], ocr=FakeOcr(available=False),
                              logger_=lambda message: None)
        with self.assertRaises(ScreenVisionError) as ctx:
            vision.observe()
        message = str(ctx.exception)
        self.assertIn("cannot see the screen", message)
        self.assertIn("GEMINI_API_KEY", message)

    def test_capture_failure_surfaces(self):
        capture = ScreenCapture(FakeBackend(fail=True), encoder=half_scale_encoder)
        vision = ScreenVision(capture, providers=[], ocr=FakeOcr(),
                              logger_=lambda message: None)
        with self.assertRaises(ScreenVisionError) as ctx:
            vision.observe()
        self.assertIn("display", str(ctx.exception))

    def test_find_prefers_accessibility_then_ocr_then_vision(self):
        accessibility_target = ElementTarget("Save button", 10, 20, 0.95,
                                             source="accessibility")
        accessibility = FakeAccessibility([accessibility_target])
        vision, provider = self._vision(accessibility=accessibility)
        found = vision.find("save")
        self.assertEqual(found[0].source, "accessibility")
        self.assertEqual(provider.calls, 0)

        ocr_target = ElementTarget("Save", 30, 40, 0.7, source="ocr")
        ocr = FakeOcr(matches=[ocr_target])
        vision, provider = self._vision(ocr=ocr,
                                        accessibility=FakeAccessibility([], available=False))
        found = vision.find("Save")
        self.assertEqual(found[0].source, "ocr")
        self.assertEqual(provider.calls, 0)

        vision, provider = self._vision(
            accessibility=FakeAccessibility([], available=False),
            ocr=FakeOcr(available=False),
        )
        found = vision.find("Save")
        self.assertEqual(found[0].source, "vision")
        self.assertEqual(provider.calls, 1)

    def test_find_returns_empty_when_no_match(self):
        vision, _ = self._vision(payload={"summary": "blank", "confidence": 0.9,
                                          "elements": []})
        self.assertEqual(vision.find("Nonexistent", min_confidence=0.9), [])

    def test_verify_reads_true_and_false(self):
        vision, _ = self._vision(payload={"summary": "TRUE: the dialog is open.",
                                          "confidence": 0.9})
        result = vision.verify("the dialog is open")
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "fake-vision")

        vision, _ = self._vision(payload={"summary": "FALSE: nothing changed.",
                                          "confidence": 0.6})
        self.assertFalse(vision.verify("the dialog is open").ok)

    def test_verify_without_provider_uses_ocr_and_says_it_is_weak(self):
        capture, _ = make_capture()
        vision = ScreenVision(capture, providers=[],
                              ocr=FakeOcr(text="Saved successfully"),
                              logger_=lambda message: None)
        result = vision.verify("saved")
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "ocr")
        self.assertLess(result.confidence, 0.6)

    def test_verify_no_provider_reports_clearly(self):
        capture, _ = make_capture()
        vision = ScreenVision(capture, providers=[], ocr=FakeOcr(available=False),
                              logger_=lambda message: None)
        result = vision.verify("anything")
        self.assertFalse(result.ok)
        self.assertIn("cannot verify", result.reason)

    def test_capabilities_reports_what_is_missing(self):
        vision, _ = self._vision(ocr=FakeOcr(available=False))
        capabilities = vision.capabilities()
        self.assertEqual(capabilities["vision"], ["fake-vision"])
        self.assertFalse(capabilities["ocr"])
        self.assertIn("not installed", capabilities["ocr_reason"])

    def test_ocr_engine_uses_injected_reader_and_matcher(self):
        engine = OcrEngine(
            reader=lambda: [{"text": "Save", "confidence": 90, "x": 5, "y": 6,
                             "w": 20, "h": 10, "line": (1, 1, 1)}],
            matcher=lambda label, words: [{"x": 15, "y": 11, "confidence": 90}],
        )
        targets = engine.find("Save")
        self.assertEqual(targets[0].x, 15)
        self.assertEqual(targets[0].confidence, 0.9)
        self.assertEqual(engine.text(), "Save")

    def test_ocr_reader_failure_is_reported_not_crashing(self):
        engine = OcrEngine(reader=lambda: (_ for _ in ()).throw(RuntimeError("tesseract missing")))
        with self.assertRaises(ScreenVisionError):
            engine.read_words()


class FakeInput:
    name = "fake-input"

    def __init__(self):
        self.ops: list[tuple] = []
        self._size = (1920, 1080)

    def available(self):
        return True

    def size(self):
        return self._size

    def position(self):
        return (0, 0)

    def move_to(self, x, y, duration=0.25):
        self.ops.append(("move", x, y))

    def click(self, x, y, *, button="left", clicks=1):
        self.ops.append(("click", x, y, button, clicks))

    def type_text(self, text, interval=0.01):
        self.ops.append(("type", text))

    def press(self, keys):
        self.ops.append(("press", tuple(keys)))

    def scroll(self, amount, x=None, y=None):
        self.ops.append(("scroll", amount))

    def focus_window(self, title):
        self.ops.append(("focus", title))
        return title.casefold() in {"chrome", "editor"}


class FakeVisionForUse:
    def __init__(self, targets=None, verify_ok=True):
        self.targets = targets if targets is not None else [
            ElementTarget("Save", 400, 300, 0.9, source="ocr")
        ]
        self.verify_ok = verify_ok
        self.observations = 0

    def find(self, label, **kwargs):
        return list(self.targets)

    def observe(self, question="", **kwargs):
        self.observations += 1
        return ScreenObservation(description="The dialog is still open.",
                                 provider="fake", confidence=0.7, uncertain=False)

    def verify(self, expectation, **kwargs):
        return VerifyResult(self.verify_ok, 0.8, "checked")


class ComputerUseTests(unittest.TestCase):
    def _controller(self, *, vision=None, config=None, authorize=None, stop=None):
        backend = FakeInput()
        controller = ComputerUseController(
            backend,
            vision=vision or FakeVisionForUse(),
            config=config or ComputerUseConfig(settle_s=0.0),
            authorize=authorize,
            stop_event=stop,
            sleep=lambda seconds: None,
        )
        return controller, backend

    def test_click_element_moves_and_clicks_then_reobserves(self):
        controller, backend = self._controller()
        result = controller.click_element("Save")
        self.assertTrue(result.ok)
        self.assertIn(("move", 400, 300), backend.ops)
        self.assertIn("click", [op[0] for op in backend.ops])
        self.assertEqual(controller.actions_taken, 1)
        self.assertIn("dialog", result.observed.casefold())

    def test_target_must_be_inside_the_screen(self):
        off_screen = FakeVisionForUse([ElementTarget("Save", 5000, 5000, 0.9)])
        controller, backend = self._controller(vision=off_screen)
        result = controller.click_element("Save")
        self.assertFalse(result.ok)
        self.assertTrue(result.retryable)
        self.assertIn("outside the usable desktop", result.detail)
        self.assertNotIn("click", [op[0] for op in backend.ops])

    def test_low_confidence_target_is_rejected(self):
        unsure = FakeVisionForUse([ElementTarget("Save", 100, 100, 0.1)])
        controller, backend = self._controller(vision=unsure)
        result = controller.click_element("Save")
        self.assertFalse(result.ok)
        self.assertIn("confidence", result.detail)
        self.assertNotIn("click", [op[0] for op in backend.ops])

    def test_missing_target_is_retryable_and_reports_observation(self):
        controller, backend = self._controller(vision=FakeVisionForUse([]))
        result = controller.click_element("Save")
        self.assertFalse(result.ok)
        self.assertTrue(result.retryable)
        self.assertIn("could not find", result.detail)
        self.assertIn("dialog", result.observed.casefold())

    def test_dry_run_never_touches_the_desktop(self):
        controller, backend = self._controller(config=ComputerUseConfig(dry_run=True))
        result = controller.click_element("Save")
        self.assertTrue(result.ok)
        self.assertTrue(result.dry_run)
        self.assertEqual([op for op in backend.ops if op[0] == "click"], [])
        self.assertEqual(controller.actions_taken, 0)

    def test_stop_prevents_further_actions(self):
        stop = threading.Event()
        controller, backend = self._controller(stop=stop)
        controller.stop()
        result = controller.click_element("Save")
        self.assertTrue(result.cancelled)
        self.assertEqual(backend.ops, [])

    def test_action_budget_is_enforced(self):
        controller, backend = self._controller(
            config=ComputerUseConfig(settle_s=0.0, max_actions=1)
        )
        self.assertTrue(controller.click_element("Save").ok)
        second = controller.click_element("Save")
        self.assertTrue(second.blocked)
        self.assertIn("budget", second.detail.casefold())
        self.assertEqual(len([op for op in backend.ops if op[0] == "click"]), 1)

    def test_typing_and_keys_and_scroll_are_recorded(self):
        controller, backend = self._controller()
        self.assertTrue(controller.type_text("hello world").ok)
        self.assertTrue(controller.press_keys(["ctrl", "s"]).ok)
        self.assertTrue(controller.scroll(-3).ok)
        self.assertIn(("type", "hello world"), backend.ops)
        self.assertIn(("press", ("ctrl", "s")), backend.ops)
        self.assertIn(("scroll", -3), backend.ops)

    def test_focus_window_reports_missing_window(self):
        controller, backend = self._controller()
        self.assertTrue(controller.focus_window("Chrome").ok)
        missing = controller.focus_window("Nonexistent")
        self.assertFalse(missing.ok)
        self.assertTrue(missing.retryable)

    def test_authorization_callback_can_block(self):
        controller, backend = self._controller(
            authorize=lambda description: (False, "Desktop control is disabled.")
        )
        result = controller.click_element("Save")
        self.assertFalse(result.ok)
        self.assertTrue(result.blocked)
        self.assertEqual(backend.ops, [])

    def test_verification_failure_is_reported(self):
        vision = FakeVisionForUse(verify_ok=False)
        controller, _ = self._controller(vision=vision)
        result = controller.click_element("Save", expectation="a new window opened")
        self.assertFalse(result.ok)
        self.assertTrue(result.retryable)
        self.assertIs(result.verified, False)

    def test_backend_failure_is_retryable(self):
        class BrokenInput(FakeInput):
            def click(self, x, y, *, button="left", clicks=1):
                raise RuntimeError("desktop is locked")

        controller = ComputerUseController(
            BrokenInput(), vision=FakeVisionForUse(),
            config=ComputerUseConfig(settle_s=0.0), sleep=lambda seconds: None,
        )
        result = controller.click_element("Save")
        self.assertFalse(result.ok)
        self.assertTrue(result.retryable)
        self.assertIn("desktop is locked", result.detail)

    def test_unavailable_backend_is_reported(self):
        class NoInput(FakeInput):
            def available(self):
                return False

            def size(self):
                return (0, 0)

        controller = ComputerUseController(NoInput(), vision=FakeVisionForUse(),
                                           sleep=lambda seconds: None)
        result = controller.click_element("Save")
        self.assertFalse(result.ok)
        self.assertIn("geometry", result.detail)


class ContinuousObserverTests(unittest.TestCase):
    def test_observer_collects_bounded_frames_and_stops(self):
        import time

        class CountingVision:
            def __init__(self):
                self.calls = 0

            def observe(self, question="", **kwargs):
                self.calls += 1
                return ScreenObservation(description=f"frame {self.calls}",
                                         confidence=0.9, uncertain=False)

        vision = CountingVision()
        seen = []
        observer = ContinuousObserver(vision, interval_s=2.0, max_frames=2,
                                      on_observation=seen.append,
                                      logger_=lambda message: None)
        # Drive the loop body without waiting the real interval.
        observer.interval_s = 0.01
        observer.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and observer.running:
            time.sleep(0.01)
        observer.stop()
        self.assertFalse(observer.running)
        self.assertEqual(observer.frames, 2)
        self.assertEqual(len(seen), 2)

    def test_observer_stops_after_repeated_failures(self):
        import time

        class BrokenVision:
            def __init__(self):
                self.calls = 0

            def observe(self, question="", **kwargs):
                self.calls += 1
                raise ScreenVisionError("capture failed")

        vision = BrokenVision()
        observer = ContinuousObserver(vision, interval_s=2.0,
                                      logger_=lambda message: None)
        observer.interval_s = 0.01  # the constructor floors this at 2s on purpose
        observer.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and observer.running:
            time.sleep(0.01)
        self.assertFalse(observer.running)
        self.assertLessEqual(vision.calls, 4)
        self.assertIn("capture failed", observer.last_error)


class NoGuiBackendsTest(unittest.TestCase):
    def test_missing_mss_and_pillow_raises_actionable_error(self):
        blocked = {"mss": None, "PIL": None, "PIL.ImageGrab": None}
        with patch.dict(sys.modules, blocked):
            capture = ScreenCapture()
            with self.assertRaises(ScreenCaptureError) as ctx:
                capture.backend()
        message = str(ctx.exception).casefold()
        self.assertIn("mss", message)
        self.assertIn("requirements", message)


if __name__ == "__main__":
    unittest.main()
