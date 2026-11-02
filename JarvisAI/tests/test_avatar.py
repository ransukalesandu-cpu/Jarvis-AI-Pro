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
        d, w = dark.pixelColor(x, y), light.pixelColor(x, y)
        self.assertGreater(d.blue(), 30)                       # something is drawn
        self.assertGreater(w.red() - d.red(), 40)              # and it is not opaque

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


if __name__ == "__main__":
    unittest.main()
