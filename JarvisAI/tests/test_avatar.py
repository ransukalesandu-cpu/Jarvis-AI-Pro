"""Tests for Holographic AI Avatar enhancements."""

import unittest
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QImage, QPainter

from core.avatar import HoloAvatar as MeshHoloAvatar
from core.artificial_avatar import HoloAvatar as SyntheticHoloAvatar


class AvatarTests(unittest.TestCase):
    def test_mesh_avatar_lifecycle_and_color_adaptation(self):
        avatar = MeshHoloAvatar()
        self.assertGreater(avatar.SPAN, 0)

        # Test step with different states and expressions
        avatar.step(0.016, amp=0.5, speaking=True, muted=False, state="SPEAKING")
        self.assertGreater(avatar._glow, 0.0)

        avatar.react_to_text("Emergency alert! Critical security warning.")
        avatar.step(0.016, amp=0.8, speaking=True, muted=False, state="SPEAKING")
        p, a = avatar._adapt_colors(0.016, QColor(113, 212, 194), QColor(217, 138, 89))
        self.assertTrue(p.isValid() and a.isValid())

        avatar.react_to_text("Hello good morning, welcome!")
        avatar.step(0.016, amp=0.2, speaking=False, muted=False, state="LISTENING")
        p_happy, a_happy = avatar._adapt_colors(0.016, QColor(113, 212, 194), QColor(217, 138, 89))
        self.assertTrue(p_happy.isValid() and a_happy.isValid())

    def test_mesh_avatar_paint_offscreen(self):
        avatar = MeshHoloAvatar()
        img = QImage(QSize(400, 400), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0))

        painter = QPainter(img)
        try:
            avatar.step(0.016, amp=0.6, speaking=True, state="SPEAKING",
                        v_open=0.8, v_wide=0.3, v_level=0.5)
            avatar.paint(painter, 200.0, 200.0, 150.0,
                         QColor(113, 212, 194), QColor(217, 138, 89), QColor(8, 14, 18))
        finally:
            painter.end()

    def test_synthetic_avatar_lifecycle_and_color_adaptation(self):
        avatar = SyntheticHoloAvatar()
        avatar.step(0.016, amp=0.7, speaking=True, muted=False, state="THINKING")
        self.assertGreater(avatar._energy, 0)

        avatar.react_to_text("warning emergency error")
        avatar.step(0.016, amp=0.0, speaking=False, muted=False, state="PROCESSING")

        img = QImage(QSize(400, 400), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0))

        painter = QPainter(img)
        try:
            avatar.paint(painter, 200.0, 200.0, 150.0,
                         QColor(113, 212, 194), QColor(217, 138, 89), QColor(8, 14, 18))
        finally:
            painter.end()

    def test_avatar_viseme_sequence_stepping(self):
        avatar = MeshHoloAvatar()
        v_seq = [
            (0.4, 0.8, 0.2),
            (0.6, 0.9, -0.1),
            (0.2, 0.1, 0.0),
        ]
        avatar.step(0.016, amp=0.5, speaking=True, state="SPEAKING",
                    v_seq=v_seq, v_hop=0.02)
        self.assertGreaterEqual(avatar._mouth, 0.0)


def _render(avatar, size=400, bg=QColor(0, 0, 0), yaw=None):
    img = QImage(QSize(size, size), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(bg)
    for _ in range(10):
        avatar.step(0.033, amp=0.0)
    if yaw is not None:
        avatar._yaw = yaw
    r = size * 0.9 / (avatar.SPAN + 0.08)
    painter = QPainter(img)
    try:
        avatar.paint(painter, size / 2, size * 0.04 + r, r,
                     QColor(30, 150, 255), QColor(30, 150, 255), bg)
    finally:
        painter.end()
    return img, r


class CyberAvatarTests(unittest.TestCase):
    def test_default_look_is_unchanged(self):
        self.assertEqual(MeshHoloAvatar().look, "shaded")

    def test_cyber_look_includes_shoulders_in_the_span(self):
        plain, cyber = MeshHoloAvatar(), MeshHoloAvatar(style="cyber")
        self.assertEqual(cyber.look, "cyber")
        self.assertGreater(cyber.SPAN, plain.SPAN + 0.5)

    def test_cyber_glass_is_see_through(self):
        # The same face over black and over white: a half-transparent head
        # lets the background change the cheek pixel; a solid one would not.
        cyber = MeshHoloAvatar(style="cyber")
        dark, r = _render(cyber, bg=QColor(0, 0, 0))
        light, _ = _render(MeshHoloAvatar(style="cyber"), bg=QColor(255, 255, 255))
        x, y = 200 + int(r * 0.33), int(400 * 0.04 + r + r * 0.25)   # a cheek
        # Average a patch so a wire crossing one pixel cannot decide the test.
        patch = [(x + i, y + j) for i in range(-4, 5) for j in range(-4, 5)]
        d_blue = sum(dark.pixelColor(*q).blue() for q in patch) / len(patch)
        gap = sum(light.pixelColor(*q).red() - dark.pixelColor(*q).red() for q in patch) / len(patch)
        self.assertGreater(d_blue, 30)                         # something is drawn
        self.assertGreater(gap, 40)                            # and it is not opaque

    def test_cyber_paints_when_turned(self):
        img, _ = _render(MeshHoloAvatar(style="cyber"), yaw=-0.6)
        self.assertFalse(img.isNull())

    def test_cyber_parts_avoid_the_features(self):
        from core.avatar_cyber import CyberParts
        from core.avatar_mesh import get_head_mesh
        mesh = get_head_mesh()
        parts = CyberParts.build(mesh)
        self.assertGreater(len(parts.traces), 20)
        self.assertGreater(len(parts.hair), 100)
        eyes = set(mesh["landmarks"]["eye_l"].tolist()) | set(mesh["landmarks"]["eye_r"].tolist())
        for trace in parts.traces:
            self.assertFalse(eyes & set(trace.tolist()))

    def test_sculpted_head_has_a_square_jaw(self):
        from core.avatar_mesh import get_head_mesh
        plain, sculpt = get_head_mesh(), get_head_mesh(sculpt=True)

        def jaw_width(mesh):
            v = mesh["verts"][:mesh["n_face"]]
            band = (v[:, 1] < -0.70) & (v[:, 1] > -0.85)
            return float(abs(v[band, 0]).max())
        self.assertGreater(jaw_width(sculpt), jaw_width(plain) * 1.12)
        self.assertEqual(len(plain["verts"]), len(sculpt["verts"]))   # same topology


if __name__ == "__main__":
    unittest.main()


class ImageHologramTests(unittest.TestCase):
    def _portrait(self, path):
        # A light checkerboard "transparent" background around an outlined face.
        img = QImage(QSize(200, 260), QImage.Format.Format_RGB32)
        for y in range(260):
            for x in range(200):
                v = 254 if ((x // 10 + y // 10) % 2) else 232
                img.setPixelColor(x, y, QColor(v, v, v))
        p = QPainter(img)
        p.setPen(QColor(0, 0, 0))
        p.setBrush(QColor(230, 180, 140))
        p.drawEllipse(40, 30, 120, 170)
        p.end()
        img.save(str(path))

    def test_picture_becomes_a_cut_out_hologram(self):
        import tempfile
        from pathlib import Path

        from core.avatar_image import ImageHologram, find_face
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hologram_face.png"
            self._portrait(path)
            self.assertEqual(find_face(Path(d)), path)
            holo = ImageHologram(path)
            self.assertAlmostEqual(holo.aspect, 121 / 171, delta=0.05)   # cropped to the face
            self.assertEqual(float(holo._alpha[0, 0]), 0.0)              # background is gone
            out = QImage(QSize(300, 300), QImage.Format.Format_ARGB32_Premultiplied)
            out.fill(QColor(0, 0, 0))
            painter = QPainter(out)
            try:
                holo.paint(painter, 150, 20, 260, QColor(40, 215, 255), QColor(200, 252, 255),
                           t=1.0, mouth=0.8, amp=0.5, blink=0.0)
            finally:
                painter.end()
            self.assertGreater(out.pixelColor(150, 150).blue(), 40)

    def test_image_style_falls_back_without_a_picture(self):
        from unittest import mock
        with mock.patch("core.avatar_image.find_face", return_value=None):
            avatar = MeshHoloAvatar(style="image")
        self.assertEqual(avatar.look, "volume")

    def test_expressions_move_the_picture(self):
        import tempfile
        from pathlib import Path

        from core.avatar_image import EMOTIONS, ImageHologram
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hologram_face.png"
            self._portrait(path)
            holo = ImageHologram(path)
            base = {"jaw": 0.0, "wide": 0.0, "brow": 0.0, "blink": 0.0, "gaze_x": 0.0,
                    "gaze_y": 0.0, **{k: 0.0 for k in EMOTIONS}}
            neutral = holo._warped(holo._image_for(QColor(40, 215, 255)), base)
            for name in ("happy", "sad", "surprised"):
                moved = holo._warped(holo._image_for(QColor(40, 215, 255)), {**base, name: 1.0})
                self.assertNotEqual(moved.copy(), neutral.copy(), name)

    def test_set_emotion_drives_the_face_targets(self):
        avatar = MeshHoloAvatar(style="volume")
        avatar.set_emotion("sad", hold=2.0)
        self.assertEqual(avatar._face_targets()["sad"], 1.0)
        avatar.react_to_text("Wow, that is amazing!")
        self.assertEqual(avatar._emotion, "surprised")
        avatar._t += 5.0
        self.assertEqual(avatar._face_targets()["surprised"], 0.0)   # it wears off

    def test_lips_follow_the_voice_without_lag(self):
        import tempfile
        from pathlib import Path

        from core.avatar_image import EMOTIONS, ImageHologram
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hologram_face.png"
            self._portrait(path)
            holo = ImageHologram(path)
            base = {"jaw": 0.0, "wide": 0.0, "brow": 0.0, "blink": 0.0, "gaze_x": 0.0,
                    "gaze_y": 0.0, **{k: 0.0 for k in EMOTIONS}}
            holo.expression(base, 0.0)
            f = holo.expression({**base, "jaw": 0.9, "wide": -0.6}, 0.016)
            self.assertEqual((f["jaw"], f["wide"]), (0.9, -0.6))     # same frame
            f = holo.expression({**base, "happy": 1.0}, 0.032)
            self.assertLess(f["happy"], 0.2)                         # moods ease in
            self.assertEqual(f["jaw"], 0.0)                          # and the lips shut at once

    def test_picture_look_uses_cyan(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hologram_face.png"
            self._portrait(path)
            with mock.patch("core.avatar_image.find_face", return_value=path):
                avatar = MeshHoloAvatar(style="image")
        self.assertEqual(avatar.look, "image")
        p, _ = avatar._base_colors()
        self.assertEqual(avatar._mood_primary.rgb(), p.rgb())
