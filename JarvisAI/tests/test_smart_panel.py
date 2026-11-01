"""Behavioral tests for the SmartPanelHeader navigation bridge."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

from ui.smart_panel import SmartPanelHeader


class TestSmartPanelHeaderSignals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.header = SmartPanelHeader()
        self.header.resize(520, 116)
        self.header.show()
        self.app.processEvents()

    def tearDown(self):
        self.header.close()
        self.app.processEvents()

    def test_mouse_activation_emits_requested_view(self):
        requested = QSignalSpy(self.header.view_requested)
        cursor = self.header.document().find("TIME")
        self.assertFalse(cursor.isNull())
        self.assertTrue(cursor.charFormat().isAnchor())
        point = self.header.cursorRect(cursor).center()

        QTest.mouseClick(
            self.header.viewport(),
            Qt.MouseButton.LeftButton,
            pos=point,
        )
        self.app.processEvents()

        self.assertEqual(requested.count(), 1)
        self.assertEqual(requested.at(0)[0], "timers")

    def test_close_command_emits_close_signal(self):
        closed = QSignalSpy(self.header.close_requested)
        self.header._route_link(QUrl("jarvis://close"))
        self.assertEqual(closed.count(), 1)

    def test_external_url_is_ignored(self):
        requested = QSignalSpy(self.header.view_requested)
        closed = QSignalSpy(self.header.close_requested)
        self.header._route_link(QUrl("https://example.com/"))
        self.assertEqual(requested.count(), 0)
        self.assertEqual(closed.count(), 0)

    def test_unknown_local_command_is_ignored(self):
        requested = QSignalSpy(self.header.view_requested)
        closed = QSignalSpy(self.header.close_requested)
        self.header._route_link(QUrl("jarvis://view/not-allowed"))
        self.assertEqual(requested.count(), 0)
        self.assertEqual(closed.count(), 0)


if __name__ == "__main__":
    unittest.main()
