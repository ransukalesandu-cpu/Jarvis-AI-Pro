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


if __name__ == "__main__":
    unittest.main()
