"""Lifecycle tests for lightweight dashboard skeleton animations."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.panels.modern_dashboard import SkeletonLoader


class TestSkeletonLoaderLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.loader = SkeletonLoader()

    def tearDown(self):
        self.loader.close()
        self.app.processEvents()

    def test_shimmer_runs_only_while_visible(self):
        self.assertFalse(self.loader._timer.isActive())

        self.loader.show()
        self.app.processEvents()
        self.assertTrue(self.loader._timer.isActive())

        self.loader.hide()
        self.app.processEvents()
        self.assertFalse(self.loader._timer.isActive())

        self.loader.show()
        self.app.processEvents()
        self.assertTrue(self.loader._timer.isActive())

    def test_stop_disables_future_shimmer_restarts(self):
        self.loader.show()
        self.app.processEvents()
        self.assertTrue(self.loader._timer.isActive())

        self.loader.stop()
        self.assertFalse(self.loader._timer.isActive())

        self.loader.hide()
        self.loader.show()
        self.app.processEvents()
        self.assertFalse(self.loader._timer.isActive())


if __name__ == "__main__":
    unittest.main()
