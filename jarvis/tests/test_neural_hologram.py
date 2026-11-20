"""The neural hologram look: blue photo head with veins, neck disc, strands into an orb."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PyQt6.QtCore import QPointF, QSize
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from jarvis.core import avatar_neural as neural
from jarvis.core.avatar_image import ImageHologram
from jarvis.ui.hologram.neural_stage import NeuralStage

_APP = QApplication.instance() or QApplication([])


def _dark_portrait(path: Path, speck: bool = True) -> None:
    """A lit head and neck on a dark navy backdrop, plus a stray bright speck."""
    img = QImage(QSize(220, 300), QImage.Format.Format_RGB32)
    img.fill(QColor(6, 12, 30))
    p = QPainter(img)
    p.setPen(QColor(60, 40, 30))
    p.setBrush(QColor(205, 165, 135))            # an ordinary (skin-toned) photo, not a hologram
    p.drawEllipse(50, 20, 120, 170)              # head
    p.drawRect(85, 170, 50, 129)                 # neck down to the bottom edge
    if speck:
        p.setBrush(QColor(200, 220, 255))
        p.drawEllipse(5, 5, 6, 6)                # a speck that must not survive the cut
    p.end()
    img.save(str(path))


class CutTests(unittest.TestCase):
    def test_dark_backdrop_is_cut_and_specks_are_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hologram_face.png"
            _dark_portrait(path)
            from jarvis.core.avatar_image import _to_array
            rgba = _to_array(QImage(str(path)))
            self.assertTrue(neural.border_is_dark(rgba))
            mask = neural.cut_dark_background(rgba)
            self.assertLess(mask[8, 8], 0.5)                       # the speck is gone
            self.assertLess(mask[150, 10], 0.5)                    # backdrop
            self.assertGreater(mask[100, 110], 0.9)                # face
            self.assertGreater(mask[250, 110], 0.9)                # neck

    def test_largest_region_keeps_one_blob(self):
        fg = np.zeros((40, 40), dtype=bool)
        fg[5:30, 5:30] = True
        fg[35:38, 35:38] = True
        out = neural.largest_region(fg)
        self.assertTrue(out[10, 10])
        self.assertFalse(out[36, 36])


class VeinTests(unittest.TestCase):
    def setUp(self):
        self.mask = np.zeros((300, 220), dtype=np.float32)
        yy, xx = np.mgrid[0:300, 0:220]
        self.mask[((xx - 110) / 60) ** 2 + ((yy - 105) / 85) ** 2 < 1] = 1
        self.mask[170:300, 85:135] = 1
        self.layout = {"eyes": [(0.40, 0.30), (0.60, 0.30)], "mouth": (0.50, 0.50, 0.16)}

    def test_veins_stay_inside_and_clear_of_the_face_centre(self):
        veins = neural.grow_veins(self.mask, self.layout, seed=3)
        self.assertGreater(len(veins), 8)
        pts = np.concatenate([v[:, :2] for v in veins])
        H, W = self.mask.shape
        inside = self.mask[(pts[:, 1] * (H - 1)).astype(int), (pts[:, 0] * (W - 1)).astype(int)]
        self.assertTrue((inside > 0.5).all())
        centre = (pts[:, 0] > 0.40) & (pts[:, 0] < 0.60) & (pts[:, 1] > 0.22) & (pts[:, 1] < 0.52)
        self.assertEqual(int(centre.sum()), 0)
        self.assertEqual(len(neural.grow_veins(self.mask, self.layout, seed=3)), len(veins))   # deterministic

    def test_rasterized_veins_and_tint(self):
        veins = neural.grow_veins(self.mask, self.layout, seed=3)
        vmap = neural.rasterize_veins(veins, self.mask.shape)
        self.assertEqual(vmap.shape, self.mask.shape)
        self.assertGreater(float(vmap.max()), 0.5)
        lum = self.mask * 0.6
        img = neural.neural_tint(lum, self.mask, np.zeros_like(lum), np.zeros_like(lum), vmap,
                                 neural.NEURAL_PRIMARY)
        self.assertEqual((img.width(), img.height()), (220, 300))
        c = img.pixelColor(110, 100)
        self.assertGreater(c.blue(), c.red())                       # blue, not cyan line-art
        self.assertEqual(img.pixelColor(2, 2).alpha(), 0)          # outside stays clear


class NeuralPictureTests(unittest.TestCase):
    def test_neural_style_paints_and_reports_its_neck(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hologram_face.png"
            _dark_portrait(path)
            holo = ImageHologram(path, style="neural")
            self.assertEqual(holo.style, "neural")
            self.assertGreater(len(holo._veins), 0)
            out = QImage(QSize(400, 420), QImage.Format.Format_ARGB32_Premultiplied)
            out.fill(QColor(0, 0, 0))
            p = QPainter(out)
            try:
                holo.paint(p, 200, 20, 330, neural.NEURAL_PRIMARY, neural.NEURAL_ACCENT,
                           t=1.0, mouth=0.6, amp=0.5, blink=0.0)
            finally:
                p.end()
            self.assertIsNotNone(holo.base)
            x, y, w = holo.base
            self.assertAlmostEqual(x, 200)
            self.assertGreater(y, 250)
            self.assertGreater(out.pixelColor(200, 120).blue(), 60)

    def test_classic_style_is_unchanged_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hologram_face.png"
            _dark_portrait(path, speck=False)
            self.assertEqual(ImageHologram(path).style, "classic")
            self.assertEqual(ImageHologram(path, style="bogus").style, "classic")

    def test_avatar_neural_look_and_fallback(self):
        from jarvis.core.avatar import HoloAvatar
        with mock.patch("jarvis.core.avatar_image.find_face", return_value=None):
            self.assertEqual(HoloAvatar(style="neural").look, "volume")   # no picture: the volume head
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hologram_face.png"
            _dark_portrait(path)
            with mock.patch("jarvis.core.avatar_image.find_face", return_value=path):
                av = HoloAvatar(style="neural")
            self.assertEqual(av.look, "neural")
            self.assertEqual(av._base_colors()[0].name(), neural.NEURAL_PRIMARY.name())
            self.assertIsNone(av.neck_base)                                 # until the first frame


class StageTests(unittest.TestCase):
    def test_geometry_puts_the_orb_under_the_face(self):
        for w, h in ((900, 560), (1312, 816), (2400, 1500)):
            face_h, orb, orb_r = NeuralStage.geometry(w, h, 12, h * 0.85, w / 2)
            self.assertGreater(orb.y() - orb_r * 2, 12 + face_h * 0.9)
            self.assertLess(orb.y() + orb_r, 12 + h * 0.85 + orb_r)
            self.assertAlmostEqual(orb.x(), w / 2)

    def test_every_state_paints_and_the_tier_maps_wires_to_strands(self):
        stage = NeuralStage()
        stage.wires = 2
        self.assertEqual(stage.strands, 11)
        stage.wires = 5
        self.assertEqual(stage.wires, 5)
        img = QImage(QSize(500, 520), QImage.Format.Format_ARGB32_Premultiplied)
        for state in ("IDLE", "LISTENING", "THINKING", "SPEAKING", "ERROR", "MUTED"):
            img.fill(QColor(0, 0, 0))
            p = QPainter(img)
            try:
                stage.paint_back(p, 250, 150, 200, 1.0)
                stage.paint(p, base=(250.0, 260.0, 120.0), orb=QPointF(250, 420), orb_r=40,
                            t=1.0, level=0.6, state=state)
            finally:
                p.end()
            self.assertGreater(img.pixelColor(250, 420).blue(), 150)       # the bright core
        stage.pulses = False
        p = QPainter(img)
        stage.paint(p, base=(250.0, 260.0, 120.0), orb=QPointF(250, 420), orb_r=40, t=2.0, level=0.0, state="IDLE")
        p.end()


class ConfigTests(unittest.TestCase):
    def test_hologram_look_defaults_to_neural_and_validates(self):
        from jarvis.memory import config_manager as cm
        with mock.patch.object(cm, "load_api_keys", return_value={}):
            self.assertEqual(cm.get_hologram_look(), "neural")
        with mock.patch.object(cm, "load_api_keys", return_value={"hologram_look": "Classic"}):
            self.assertEqual(cm.get_hologram_look(), "classic")
        with mock.patch.object(cm, "load_api_keys", return_value={"hologram_look": "weird"}):
            self.assertEqual(cm.get_hologram_look(), "neural")
        saved = {}
        with mock.patch.object(cm, "_save_flag", side_effect=lambda k, v: saved.update({k: v})):
            cm.save_hologram_look("classic")
            self.assertEqual(saved, {"hologram_look": "classic"})


if __name__ == "__main__":
    unittest.main()


class KeepColoursTests(unittest.TestCase):
    """A picture that is already a hologram is shown exactly as drawn."""

    def _holo_picture(self, path: Path) -> None:
        img = QImage(QSize(220, 300), QImage.Format.Format_RGB32)
        img.fill(QColor(2, 6, 14))
        p = QPainter(img)
        p.setPen(QColor(120, 230, 255))
        p.setBrush(QColor(30, 150, 200))
        p.drawEllipse(50, 20, 120, 170)
        p.drawRect(85, 170, 50, 129)
        p.end()
        img.save(str(path))

    def test_hologram_picture_keeps_its_colours_and_animates(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hologram_face.png"
            self._holo_picture(path)
            holo = ImageHologram(path, style="neural")
            self.assertTrue(holo.keep_colors)
            self.assertEqual(holo._veins, [])                       # its own veins, none generated
            img = holo._image_for(neural.NEURAL_PRIMARY)
            c = img.pixelColor(img.width() // 2, img.height() // 3)
            self.assertGreater(c.green(), c.red())                  # cyan as drawn, not re-lit
            out = QImage(QSize(400, 420), QImage.Format.Format_ARGB32_Premultiplied)
            out.fill(QColor(0, 0, 0))
            p = QPainter(out)
            try:
                holo.paint(p, 200, 20, 330, neural.NEURAL_PRIMARY, neural.NEURAL_ACCENT, t=1.0,
                           mouth=0.8, amp=0.6, blink=0.0, face={"happy": 1.0, "gaze_x": 0.5})
            finally:
                p.end()
            self.assertGreater(out.pixelColor(200, 140).green(), 60)

    def test_json_can_force_tint_and_veins(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hologram_face.png"
            self._holo_picture(path)
            path.with_suffix(".json").write_text('{"colors": "tint", "veins": true}', encoding="utf-8")
            holo = ImageHologram(path, style="neural")
            self.assertFalse(holo.keep_colors)
            self.assertGreater(len(holo._veins), 0)

    def test_ordinary_photo_is_not_mistaken_for_a_hologram(self):
        rgb = np.full((50, 50, 3), (200.0, 160.0, 130.0), dtype=np.float32)
        self.assertFalse(neural.already_hologram(rgb, np.ones((50, 50), dtype=np.float32)))
        rgb[:] = (30.0, 150.0, 220.0)
        self.assertTrue(neural.already_hologram(rgb, np.ones((50, 50), dtype=np.float32)))
