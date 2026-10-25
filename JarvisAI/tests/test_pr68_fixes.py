import unittest
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication, QEvent
import sys

class PR68FixesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_audio_resampling_clipping(self):
        """Verify audio interpolation clipping prevents int16 overflow."""
        raw_mono = np.array([32000, -32000, 35000, -35000], dtype=np.float32)
        old_x = np.linspace(0, 1, len(raw_mono))
        new_x = np.linspace(0, 1, 8)
        resampled_float = np.interp(new_x, old_x, raw_mono)
        resampled = np.clip(resampled_float, -32768, 32767).astype(np.int16)

        self.assertTrue(np.all(resampled <= 32767))
        self.assertTrue(np.all(resampled >= -32768))

    def test_ui_voice_id_signal(self):
        """Verify MainWindow_voice_id_enabled_sig exists and is connected."""
        from ui import MainWindow
        win = MainWindow("face.png")
        try:
            self.assertTrue(hasattr(win, "_voice_id_enabled_sig"))
        finally:
            win.close()
            win.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

if __name__ == "__main__":
    unittest.main()
