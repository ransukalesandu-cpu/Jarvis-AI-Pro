"""Workstream B: heart, orb and energy wires around the face."""
import unittest

from PyQt6.QtCore import QPointF, QSize
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from ui.hologram.stage import WIRES, HologramStage

_APP = QApplication.instance() or QApplication([])   # sprites are QPixmaps


class StageTests(unittest.TestCase):
    def test_geometry_keeps_face_orb_and_heart_apart(self):
        for w, h in ((900, 560), (1200, 800), (2400, 1500)):
            face_h, orb, orb_r, heart, heart_r = HologramStage.geometry(w, h, 12, h * 0.85, w / 2)
            self.assertGreater(orb.y() - orb_r, 12 + face_h * 0.98)        # orb under the face
            self.assertAlmostEqual(orb.x(), w / 2)
            self.assertLess(heart.x() + heart_r, w * 0.3)                  # heart low on the left
            self.assertGreater(heart.y(), h * 0.5)
            self.assertLess(heart_r, orb_r * 1.2)                          # the heart is the small one

    def test_five_wires_neck_to_heart_to_orb(self):
        stage = HologramStage()
        neck, heart, orb = QPointF(300, 200), QPointF(80, 330), QPointF(300, 360)
        paths = stage._wire_paths(neck, heart, orb, 6.0)
        self.assertEqual(len(paths), WIRES)
        for to_heart, to_orb in paths:
            self.assertAlmostEqual(to_heart[0].y(), neck.y())
            self.assertLess(abs(to_heart[3].x() - heart.x()), 6.0)
            self.assertEqual(to_heart[3], to_orb[0])                       # continuous
            self.assertLess(abs(to_orb[3].x() - orb.x()), 6.0)

    def test_every_state_paints_and_sprites_are_cached(self):
        stage = HologramStage()
        img = QImage(QSize(500, 420), QImage.Format.Format_ARGB32_Premultiplied)
        for state in ("IDLE", "LISTENING", "THINKING", "SPEAKING", "SLEEPING", "MUTED"):
            img.fill(QColor(0, 0, 0))
            p = QPainter(img)
            try:
                stage.paint(p, neck=QPointF(250, 200), orb=QPointF(250, 340), orb_r=30,
                            heart=QPointF(70, 360), heart_r=20, t=1.5, level=0.7, state=state)
            finally:
                p.end()
            self.assertGreater(img.pixelColor(250, 340).blue(), 100, state)     # the orb
            self.assertGreater(img.pixelColor(70, 362).red(), 100, state)       # the heart
        n = len(stage._sprites)
        p = QPainter(img)
        stage.paint(p, neck=QPointF(250, 200), orb=QPointF(250, 340), orb_r=30,
                    heart=QPointF(70, 360), heart_r=20, t=1.6, level=0.7, state="SPEAKING")
        p.end()
        self.assertLessEqual(len(stage._sprites), n + 3)          # reused, not rebuilt per frame


if __name__ == "__main__":
    unittest.main()
