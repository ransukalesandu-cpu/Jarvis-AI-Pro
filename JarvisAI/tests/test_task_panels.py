"""Tests for context-aware glass task panels and their deterministic layout.

The panels are the only part of the home screen that grows while JARVIS works, so
two properties matter and are asserted here:

1. **Truthfulness** — a panel draws a control only when a real callback exists,
   indeterminate work never renders a fake percentage, and only the code that
   finished the work can mark it done.
2. **Placement** — the hologram's rectangle is never covered, panels never
   overlap each other, and nothing is placed outside the stage.
"""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

if sys.platform != "win32" and not os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import unittest

from PyQt6.QtCore import QCoreApplication, QEvent, QRect
from PyQt6.QtWidgets import QApplication, QToolButton

app = QApplication.instance() or QApplication(sys.argv)

from core.hologram_theme import BIHANSA_PALETTE, JARVIS_PALETTE
from ui.task_panels import (
    GlassTaskPanel,
    TaskKind,
    TaskPanelManager,
    TaskSpec,
    TaskState,
    kind_for_action,
    layout_candidates,
)

FACE = QRect(400, 120, 480, 380)


class WidgetHarness(unittest.TestCase):
    def setUp(self):
        self._widgets = []

    def track(self, widget):
        self._widgets.append(widget)
        return widget

    def tearDown(self):
        for widget in self._widgets:
            try:
                widget.close()
                widget.deleteLater()
            except RuntimeError:
                pass
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        except RuntimeError:
            pass


class TestLayoutCandidates(unittest.TestCase):
    def test_best_candidate_avoids_the_face(self):
        bounds = QRect(0, 0, 1280, 720)
        candidates = layout_candidates(bounds, FACE, (280, 64))
        self.assertTrue(candidates)
        best_cost, best = candidates[0]
        self.assertEqual(FACE.intersected(best).width() * FACE.intersected(best).height(), 0)
        self.assertTrue(bounds.adjusted(12, 12, -12, -12).contains(best))
        # Costs are sorted best-first.
        self.assertEqual(candidates, sorted(candidates, key=lambda item: item[0]))

    def test_candidates_are_deterministic(self):
        bounds = QRect(0, 0, 1024, 680)
        first = layout_candidates(bounds, FACE, (300, 74))
        second = layout_candidates(bounds, FACE, (300, 74))
        self.assertEqual(first, second)

    def test_placed_panels_push_new_ones_away(self):
        bounds = QRect(0, 0, 1280, 720)
        first = layout_candidates(bounds, FACE, (280, 64))[0][1]
        second = layout_candidates(bounds, FACE, (280, 64), placed=[first])[0][1]
        self.assertNotEqual(first, second)
        self.assertEqual(first.intersected(second).isEmpty(), True)

    def test_no_space_returns_nothing(self):
        # Stage exactly the size of the face: there is no honest slot.
        bounds = QRect(0, 0, 500, 400)
        self.assertEqual(layout_candidates(bounds, QRect(0, 0, 500, 400), (280, 64)), [])


class TestKindForAction(unittest.TestCase):
    def test_maps_real_tool_names(self):
        self.assertEqual(kind_for_action("youtube_video"), TaskKind.VIDEO)
        self.assertEqual(kind_for_action("play_music"), TaskKind.MUSIC)
        self.assertEqual(kind_for_action("screen_process"), TaskKind.IMAGE)
        self.assertEqual(kind_for_action("game_updater"), TaskKind.DOWNLOAD)
        self.assertEqual(kind_for_action("set_timer"), TaskKind.REMINDER)
        self.assertEqual(kind_for_action("web_search"), TaskKind.SEARCH)

    def test_unknown_and_empty_actions_are_generic(self):
        self.assertEqual(kind_for_action("recall_memory"), TaskKind.GENERIC)
        self.assertEqual(kind_for_action(""), TaskKind.GENERIC)
        self.assertEqual(kind_for_action(None), TaskKind.GENERIC)


class TestTaskSpec(unittest.TestCase):
    def test_progress_is_clamped_and_none_stays_indeterminate(self):
        self.assertIsNone(TaskSpec("a", progress=None).normalised().progress)
        self.assertEqual(TaskSpec("a", progress=3.0).normalised().progress, 1.0)
        self.assertEqual(TaskSpec("a", progress=-2).normalised().progress, 0.0)
        self.assertIsNone(TaskSpec("a", progress="junk").normalised().progress)

    def test_unknown_state_falls_back_to_running(self):
        self.assertEqual(TaskSpec("a", state="nonsense").normalised().state, TaskState.RUNNING)

    def test_terminal_states(self):
        self.assertTrue(TaskSpec("a", state=TaskState.COMPLETED).is_terminal)
        self.assertTrue(TaskSpec("a", state=TaskState.FAILED).is_terminal)
        self.assertFalse(TaskSpec("a", state=TaskState.RUNNING).is_terminal)

    def test_invalid_duration_is_dropped(self):
        spec = TaskSpec("a", position=5.0, duration=0.0).normalised()
        self.assertIsNone(spec.duration)


class TestThumbnailDrivenSizing(WidgetHarness):
    def test_media_panels_stay_compact_without_a_real_thumbnail(self):
        manager = TaskPanelManager(self.track(__import__("PyQt6.QtWidgets", fromlist=["QWidget"]).QWidget()))
        manager.resize(1280, 720)
        self.assertEqual(
            manager._panel_size(TaskSpec("v", TaskKind.VIDEO, "Clip")),
            TaskPanelManager.PANEL_SIZES[TaskKind.VIDEO],
        )
        self.assertEqual(
            manager._panel_size(TaskSpec("v", TaskKind.VIDEO, "Clip", thumbnail_path="/nope/missing.png")),
            TaskPanelManager.PANEL_SIZES[TaskKind.VIDEO],
        )

    def test_media_panels_grow_for_an_existing_thumbnail(self):
        manager = TaskPanelManager(self.track(__import__("PyQt6.QtWidgets", fromlist=["QWidget"]).QWidget()))
        manager.resize(1280, 720)
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png") as handle:
            size = manager._panel_size(
                TaskSpec("v", TaskKind.VIDEO, "Clip", thumbnail_path=handle.name)
            )
        self.assertEqual(size, TaskPanelManager.MEDIA_SIZES[TaskKind.VIDEO])


class TestGlassTaskPanel(WidgetHarness):
    def test_no_buttons_without_callbacks(self):
        panel = self.track(GlassTaskPanel(TaskSpec("t", TaskKind.GENERIC, "Searching"), JARVIS_PALETTE))
        self.assertEqual(panel.findChildren(QToolButton), [])

    def test_music_controls_only_for_real_callbacks(self):
        spec = TaskSpec(
            "m", TaskKind.MUSIC, "Track", state=TaskState.RUNNING,
            on_play_pause=lambda: None, on_dismiss=lambda: None,
        )
        panel = self.track(GlassTaskPanel(spec, BIHANSA_PALETTE))
        buttons = panel.findChildren(QToolButton)
        # play/pause + dismiss, but no previous/next because those are None.
        self.assertEqual(len(buttons), 2)
        labels = sorted(button.toolTip() for button in buttons)
        self.assertEqual(labels, ["Dismiss", "Play/pause"])

    def test_dismiss_signal_is_emitted(self):
        seen = []
        spec = TaskSpec("d", TaskKind.GENERIC, "Task", on_dismiss=lambda: seen.append("cb"))
        panel = self.track(GlassTaskPanel(spec, JARVIS_PALETTE))
        panel.sig_dismiss.connect(seen.append)
        panel._emit_dismiss()
        self.assertEqual(sorted(seen), ["cb", "d"])

    def test_broken_callback_is_contained(self):
        def explode():
            raise RuntimeError("nope")

        panel = self.track(GlassTaskPanel(TaskSpec("x", TaskKind.GENERIC, "T", on_open=explode), JARVIS_PALETTE))
        panel._invoke(explode)   # must not raise

    def test_context_and_palette_follow_spec(self):
        spec = TaskSpec("c", TaskKind.VIDEO, "Clip")
        panel = self.track(GlassTaskPanel(spec, JARVIS_PALETTE))
        panel.apply_spec(TaskSpec("c", TaskKind.MUSIC, "Song", on_play_pause=lambda: None),
                         BIHANSA_PALETTE)
        self.assertEqual(panel.spec.kind, TaskKind.MUSIC)
        self.assertEqual(panel._palette.primary, BIHANSA_PALETTE.primary)
        self.assertEqual(len(panel.findChildren(QToolButton)), 1)

    def test_flash_decays(self):
        panel = self.track(GlassTaskPanel(TaskSpec("f", TaskKind.GENERIC, "T"), JARVIS_PALETTE))
        panel.flash()
        self.assertEqual(panel._highlight, 1.0)
        for _ in range(4):
            panel._tick()
        self.assertLess(panel._highlight, 1.0)


class TestTaskPanelManager(WidgetHarness):
    def _manager(self, width=1280, height=720):
        from PyQt6.QtWidgets import QWidget

        stage = self.track(QWidget())
        stage.resize(width, height)
        manager = TaskPanelManager(stage, JARVIS_PALETTE)
        manager.resize(stage.rect().size())
        manager.set_blocked_rect(QRect(400, 120, 480, 380))
        return manager

    def test_open_update_close_cycle(self):
        manager = self._manager()
        manager.open_task(TaskSpec("t1", TaskKind.SEARCH, "Searching the web",
                                   state=TaskState.RUNNING, progress=None))
        self.assertTrue(manager.has_task("t1"))
        self.assertEqual(manager.panel("t1").spec.state, TaskState.RUNNING)

        self.assertTrue(manager.update_task("t1", state=TaskState.COMPLETED, progress=1.0))
        self.assertEqual(manager.panel("t1").spec.state, TaskState.COMPLETED)

        manager.close_task("t1")
        self.assertFalse(manager.has_task("t1"))
        self.assertEqual([spec.task_id for spec in manager.archive()], ["t1"])

    def test_update_unknown_task_returns_false(self):
        manager = self._manager()
        self.assertFalse(manager.update_task("ghost", state=TaskState.FAILED))

    def test_unknown_field_raises(self):
        manager = self._manager()
        manager.open_task(TaskSpec("t", TaskKind.GENERIC, "T"))
        with self.assertRaises(AttributeError):
            manager.update_task("t", not_a_field=1)

    def test_reopen_restores_archived_task(self):
        manager = self._manager()
        manager.open_task(TaskSpec("t", TaskKind.REMINDER, "Reminder"))
        manager.close_task("t")
        self.assertTrue(manager.reopen("t"))
        self.assertTrue(manager.has_task("t"))

    def test_panels_never_cover_the_face_or_each_other(self):
        manager = self._manager()
        for index in range(4):
            manager.open_task(TaskSpec(f"t{index}", TaskKind.GENERIC, f"Task {index}"))
        rects = []
        for task_id in manager.task_ids():
            panel = manager.panel(task_id)
            if panel.isHidden():
                continue
            rect = panel.geometry()
            self.assertEqual(rect.intersected(QRect(400, 120, 480, 380)).isEmpty(), True)
            self.assertEqual(manager.rect().adjusted(0, 0, 0, 0).contains(rect), True)
            rects.append(rect)
        for i, first in enumerate(rects):
            for second in rects[i + 1:]:
                self.assertEqual(first.intersected(second).isEmpty(), True)

    def test_layout_survives_resize(self):
        manager = self._manager()
        manager.open_task(TaskSpec("t", TaskKind.MUSIC, "Song"))
        before = manager.panel("t").geometry()
        manager.resize(1024, 680)
        manager.set_blocked_rect(QRect(300, 100, 420, 340))
        manager.stage_resized()
        after = manager.panel("t").geometry()
        self.assertNotEqual(before, after)
        self.assertTrue(QRect(0, 0, 1024, 680).contains(after))

    def test_hides_rather_than_overflows_when_stage_is_tiny(self):
        manager = self._manager(width=620, height=420)
        manager.set_blocked_rect(QRect(170, 60, 280, 300))
        manager.open_task(TaskSpec("t", TaskKind.VIDEO, "Clip"))
        panel = manager.panel("t")
        if not panel.isHidden():
            self.assertTrue(QRect(0, 0, 620, 420).contains(panel.geometry()))

    def test_flash_and_energy_feed(self):
        manager = self._manager()
        manager.open_task(TaskSpec("t", TaskKind.MUSIC, "Song"))
        self.assertTrue(manager.flash("t"))
        self.assertFalse(manager.flash("missing"))
        manager.set_energy(0.7)
        self.assertAlmostEqual(manager.specs()[0].energy, 0.7)
        manager.set_energy("junk")
        self.assertEqual(manager.specs()[0].energy, 0.0)

    def test_specs_lists_live_tasks(self):
        manager = self._manager()
        manager.open_task(TaskSpec("a", TaskKind.GENERIC, "A"))
        manager.open_task(TaskSpec("b", TaskKind.GENERIC, "B"))
        self.assertEqual(sorted(spec.task_id for spec in manager.specs()), ["a", "b"])

    def test_palette_propagates_to_open_panels(self):
        manager = self._manager()
        manager.open_task(TaskSpec("t", TaskKind.GENERIC, "T"))
        manager.set_palette(BIHANSA_PALETTE)
        self.assertEqual(manager.panel("t")._palette.primary, BIHANSA_PALETTE.primary)


if __name__ == "__main__":
    unittest.main()
