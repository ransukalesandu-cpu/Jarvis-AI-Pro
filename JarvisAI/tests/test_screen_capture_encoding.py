"""Tests for the screenshot encoding path.

A screenshot is taken on demand during a session, so its cost is paid while the
user is waiting. The old path encoded the raw screen to PNG, decoded it again in
PIL, thumbnailed it and re-encoded as JPEG; the PNG existed only to hand bytes
between two libraries. These tests pin the direct path, the fallbacks, and the
"same picture as before" guarantee.
"""

import io
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import unittest

from actions import screen_processor as sp


class FakeShot:
    def __init__(self, size, rgb):
        self.size = size
        self.rgb = rgb


def _gradient_rgb(width, height):
    """A cheap, repeatable screen-like image (no numpy needed here)."""
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(((x * 255) // max(1, width - 1),
                          (y * 255) // max(1, height - 1),
                          128))
        rows.append(bytes(row))
    return b"".join(rows)


class FakeMss:
    """Stands in for the ``mss`` module; records whether PNG was used."""

    def __init__(self, shot):
        self._shot = shot
        self.png_calls = 0
        self.tools = self

    # ``mss.mss()`` is used as a context manager.
    def mss(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def monitors(self):
        return [{}, self._shot.size]

    def grab(self, _target):
        return self._shot

    def to_png(self, *_args, **_kwargs):
        self.png_calls += 1
        raise AssertionError("the PNG round-trip must not run on the direct path")


class ScreenCaptureHarness(unittest.TestCase):
    def setUp(self):
        self._orig = (sp.mss, sp._MSS, sp._PIL)
        self.shot = FakeShot((640, 400), _gradient_rgb(640, 400))
        self.fake = FakeMss(self.shot)
        sp.mss = self.fake
        sp._MSS = True
        sp._PIL = True

    def tearDown(self):
        sp.mss, sp._MSS, sp._PIL = self._orig


class TestDirectEncoding(ScreenCaptureHarness):
    def test_capture_returns_jpeg(self):
        payload, mime = sp._capture_screen()
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual(self.fake.png_calls, 0, "PNG round-trip was used again")
        self.assertEqual(payload[:2], b"\xff\xd8", "not a JPEG")

    def test_capture_is_downscaled_to_the_vision_budget(self):
        from PIL import Image

        payload, _mime = sp._capture_screen()
        with Image.open(io.BytesIO(payload)) as img:
            self.assertLessEqual(img.width, sp._IMG_MAX_W)
            self.assertLessEqual(img.height, sp._IMG_MAX_H)
            # Aspect ratio is preserved, not squashed.
            self.assertAlmostEqual(img.width / img.height, 640 / 400, places=2)

    def test_direct_encoding_matches_the_old_png_path_byte_for_byte(self):
        """The optimisation must not change what the model is shown."""
        import mss.tools

        width, height = 320, 200
        rgb = _gradient_rgb(width, height)
        png = mss.tools.to_png(rgb, (width, height))
        old_payload, old_mime = sp._compress(png, "PNG")
        new_payload, new_mime = sp._encode_rgb(rgb, (width, height))
        self.assertEqual(old_mime, new_mime)
        self.assertEqual(old_payload, new_payload)

    def test_encode_rgb_uses_the_module_quality_setting(self):
        """A higher quality must produce a larger payload — proof it is applied."""
        original = sp._JPEG_Q
        try:
            sp._JPEG_Q = 95
            high, _ = sp._encode_rgb(self.shot.rgb, self.shot.size)
            sp._JPEG_Q = 40
            low, _ = sp._encode_rgb(self.shot.rgb, self.shot.size)
        finally:
            sp._JPEG_Q = original
        self.assertGreater(len(high), len(low))


class TestFallbacks(ScreenCaptureHarness):
    def test_without_pil_the_png_path_still_produces_an_image(self):
        sp._PIL = False
        # ``to_png`` is what the fallback needs, so let this fake answer it.
        self.fake.to_png = lambda rgb, size: b"\x89PNG\r\n\x1a\n" + bytes(16)
        payload, mime = sp._capture_screen()
        self.assertEqual(mime, "image/png")
        self.assertTrue(payload.startswith(b"\x89PNG"))

    def test_an_encoding_failure_falls_back_instead_of_losing_the_frame(self):
        def broken(_rgb, _size):
            raise ValueError("decoder exploded")

        original = sp._encode_rgb
        sp._encode_rgb = broken
        try:
            self.fake.to_png = lambda rgb, size: b"\x89PNG\r\n\x1a\n" + bytes(16)
            payload, mime = sp._capture_screen()
        finally:
            sp._encode_rgb = original
        self.assertEqual(mime, "image/png")
        self.assertTrue(payload.startswith(b"\x89PNG"))

    def test_missing_mss_explains_how_to_install_it(self):
        sp._MSS = False
        with self.assertRaises(RuntimeError) as caught:
            sp._capture_screen()
        self.assertIn("mss", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
