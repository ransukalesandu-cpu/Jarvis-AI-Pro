"""Unit tests for responsive JARVIS dashboard grid placement."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JARVIS = ROOT / "JarvisAI"
for path in (ROOT, JARVIS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ui.panels.modern_dashboard import dashboard_grid_positions


class TestDashboardGridPositions(unittest.TestCase):
    def test_wide_layout_uses_two_columns(self):
        self.assertEqual(
            dashboard_grid_positions(1200, 5),
            ((0, 0), (0, 1), (1, 0), (1, 1), (2, 0)),
        )

    def test_compact_layout_uses_one_column(self):
        self.assertEqual(
            dashboard_grid_positions(760, 5),
            ((0, 0), (1, 0), (2, 0), (3, 0), (4, 0)),
        )

    def test_layout_threshold_is_stable(self):
        self.assertEqual(len(dashboard_grid_positions(761, 6)), 6)
        self.assertEqual(dashboard_grid_positions(761, 6)[1], (0, 1))
        self.assertEqual(dashboard_grid_positions(760, 6)[1], (1, 0))

    def test_empty_and_negative_counts_are_safe(self):
        self.assertEqual(dashboard_grid_positions(500, 0), ())
        self.assertEqual(dashboard_grid_positions(500, -2), ())


if __name__ == "__main__":
    unittest.main()
