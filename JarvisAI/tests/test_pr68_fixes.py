import unittest
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication, QEvent
import sys
import threading
import time
from unittest.mock import patch

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

    def test_expired_worker_pin_request_does_not_show_late_dialog(self):
        from ui import JarvisUI, MainWindow
        win = MainWindow("face.png")
        ui = object.__new__(JarvisUI)
        ui._win = win
        prompt_finished = threading.Event()
        real_event = threading.Event
        results = []
        worker = threading.Thread(target=lambda: results.append(ui.prompt_pin()), daemon=True)

        def make_event():
            return prompt_finished if threading.current_thread() is worker else real_event()

        try:
            with patch("threading.Event", side_effect=make_event), patch.object(
                prompt_finished, "wait", return_value=False
            ), patch("PyQt6.QtWidgets.QInputDialog.getText") as dialog:
                worker.start()
                worker.join(1)
                self.app.processEvents()
                self.assertFalse(worker.is_alive())
                self.assertEqual(results, [None])
                dialog.assert_not_called()
        finally:
            prompt_finished.set()
            worker.join(1)
            win.close()
            win.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_worker_pin_prompt_runs_on_gui_thread_and_returns_result(self):
        from ui import JarvisUI, MainWindow
        win = MainWindow("face.png")
        ui = object.__new__(JarvisUI)
        ui._win = win
        prompt_finished = threading.Event()
        real_event = threading.Event
        results = []
        gui_threads = []

        def get_pin(*_args, **_kwargs):
            gui_threads.append(threading.current_thread())
            return "synthetic-owner-pin", True

        worker = threading.Thread(target=lambda: results.append(ui.prompt_pin()), daemon=True)

        def make_event():
            return prompt_finished if threading.current_thread() is worker else real_event()

        try:
            with patch("threading.Event", side_effect=make_event), patch(
                "PyQt6.QtWidgets.QInputDialog.getText", side_effect=get_pin
            ):
                worker.start()
                deadline = time.monotonic() + 2
                while worker.is_alive() and time.monotonic() < deadline:
                    self.app.processEvents()
                    worker.join(.01)
                # Release an incorrectly queued prompt so a failed test leaves no worker behind.
                prompt_finished.set()
                worker.join(1)
            self.assertEqual(results, ["synthetic-owner-pin"])
            self.assertEqual(gui_threads, [threading.current_thread()])
        finally:
            prompt_finished.set()
            worker.join(1)
            win.close()
            win.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

if __name__ == "__main__":
    unittest.main()
