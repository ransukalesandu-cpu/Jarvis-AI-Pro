"""Regression checks for consolidated Bihansa modes and portrait geometry."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtCore import QCoreApplication, QEvent, QRectF, QSettings, QTimer
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication, QLineEdit, QPushButton

from memory import config_manager as cfg
from actions.jarvis_settings import _set_setting
from ui.hologram.bihansa_hologram import BihansaHologramWidget, BIHANSA_MESH_TRIANGLES
from ui.hologram.bihansa_settings import BihansaModeSettings, BihansaSettingsDialog


class BihansaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        config_patch = patch.object(cfg, 'CONFIG_FILE', self.root / 'api_keys.json')
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.settings = QSettings(str(self.root / 'settings.ini'), QSettings.Format.IniFormat)
        self.prefs = BihansaModeSettings(self.settings)

    def track(self, widget):
        def dispose():
            widget.close()
            widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.addCleanup(dispose)
        return widget

    def test_voice_restores_jarvis_choice_without_overwriting_it(self):
        self.assertEqual(cfg.get_assistant_mode(), 'jarvis')
        cfg.save_voice('Puck')
        _set_setting('assistant_mode', 'bihansa')
        self.assertEqual(cfg.get_voice(), 'Kore')
        _set_setting('voice', 'Aoede')
        self.assertEqual(cfg.get_voice(), 'Aoede')
        self.assertIn('Unsupported voice', _set_setting('voice', 'Fenrir'))
        _set_setting('assistant_mode', 'jarvis')
        self.assertEqual(cfg.get_voice(), 'Puck')
        self.assertEqual(json.loads(cfg.CONFIG_FILE.read_text())['voice_name'], 'Puck')

    def test_reset_applies_immediately_and_preserves_unrelated_preferences(self):
        self.settings.setValue('other/enabled', True)
        cfg.save_voice('Puck')
        self.prefs.assistant_mode = 'bihansa'
        self.prefs.glow_intensity = 10
        self.assertEqual(self.prefs.glow_intensity, 1.5)
        applied = Mock()
        dialog = self.track(BihansaSettingsDialog(settings=self.prefs, on_applied=applied))
        dialog._reset_defaults()
        applied.assert_called_once_with()
        self.assertEqual(cfg.get_assistant_mode(), 'jarvis')
        self.assertEqual(cfg.get_voice(), 'Puck')
        self.assertTrue(self.settings.value('other/enabled', type=bool))

    def test_portrait_landmarks_follow_fitted_rect_and_remain_triangulated(self):
        widget = self.track(BihansaHologramWidget())
        widget.set_reduced_motion(True)
        rect = QRectF(10, 20, 400, 480)
        points = widget._project_face_mesh(rect)
        self.assertEqual(len(points), 82)
        # Fixed reference anchors are independent of the implementation's mesh table.
        self.assertAlmostEqual(points[27][0], 10 + .492 * 400, places=3)
        self.assertAlmostEqual(points[27][1], 20 + .328 * 480, places=3)
        self.assertAlmostEqual(points[8][1], 20 + .548 * 480, places=3)
        self.assertGreater(len(BIHANSA_MESH_TRIANGLES), 40)
        for x, y, _ in points:
            self.assertTrue(rect.contains(x, y))
        widget.set_viseme('aa', 1.0)
        self.assertGreater(widget._project_face_mesh(rect)[66][1], points[66][1])
        image = QImage(640, 640, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        try:
            widget._draw_3d_face_mesh(painter, QRectF(0, 0, 640, 640))
        finally:
            painter.end()

    def test_main_window_mode_selector_updates_mesh_and_requests_one_voice_change(self):
        from ui import MainWindow
        with patch('ui.hologram.bihansa_settings.QSettings', return_value=self.settings):
            window = self.track(MainWindow('face.png'))
        self.assertIsNotNone(window._bihansa_hologram)
        callback = Mock()
        window.on_voice_change = callback
        window._mode_btn.setCurrentIndex(1)
        self.assertIs(window._hologram_mode_stack.currentWidget(), window._bihansa_hologram)
        self.assertEqual(cfg.get_voice(), 'Kore')
        callback.assert_called_once_with()
        window._mode_btn.setCurrentIndex(0)
        self.assertIs(window._hologram_mode_stack.currentWidget(), window.hud)

    def test_first_run_enrollment_rejects_mismatch_then_saves_pin_locally(self):
        from ui import MainWindow
        from security.auth_manager import AuthManager
        auth = AuthManager(vault_path=self.root / 'pin_vault.dat', state_path=self.root / 'auth_state.json')
        with patch('ui.hologram.bihansa_settings.QSettings', return_value=self.settings):
            window = self.track(MainWindow('face.png'))
        observations = []
        def fill_dialog():
            dialog = QApplication.activeModalWidget()
            fields = dialog.findChildren(QLineEdit)
            button = next(b for b in dialog.findChildren(QPushButton) if b.text() == 'SAVE & CONTINUE')
            fields[0].setText('synthetic-owner-pin')
            fields[1].setText('mismatch')
            button.click()
            observations.append(auth.is_pin_enrolled())
            fields[1].setText('synthetic-owner-pin')
            button.click()
            observations.append(all(field.text() == '' for field in fields))
        with patch('core.security.get_auth_manager', return_value=auth), \
             patch('PyQt6.QtWidgets.QMessageBox.warning') as warning:
            QTimer.singleShot(0, fill_dialog)
            window._show_owner_privacy_setup_if_needed()
        self.assertEqual(observations, [False, True])
        warning.assert_called_once()
        self.assertTrue(auth.verify_pin('synthetic-owner-pin'))
        with patch('core.security.get_auth_manager', return_value=auth), \
             patch.object(window, '_show_owner_privacy_setup') as show:
            window._show_owner_privacy_setup_if_needed()
        show.assert_not_called()
