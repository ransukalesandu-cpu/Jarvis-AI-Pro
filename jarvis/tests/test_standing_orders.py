"""Standing orders: storage, caps, prompt block, tiers, startup notice."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jarvis.actions import standing_orders as tool
from jarvis.core import owner_store, security
from jarvis.core import standing_orders as orders


class StandingOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = owner_store.OwnerStore(Path(self.tmp.name) / "owner.db")
        owner_store.reset_owner_store_for_tests(self.store)
        orders.reset_for_tests()
        self.addCleanup(owner_store.reset_owner_store_for_tests, None)
        self.addCleanup(orders.reset_for_tests)

    def test_add_list_remove_and_update_in_place(self):
        orders.add("Read Back", "Read emails back before sending.")
        orders.add("read-back", "Read every email back before sending it.")
        rows = orders.list_orders()
        self.assertEqual([(r["name"], r["instruction"]) for r in rows],
                         [("read-back", "Read every email back before sending it.")])
        self.assertTrue(orders.remove("read-back"))
        self.assertFalse(orders.remove("read-back"))

    def test_validation_and_caps(self):
        for args in (("bad name!", "x"), ("ok", ""), ("ok", "y" * (orders.MAX_TEXT + 1))):
            with self.assertRaises(ValueError, msg=args):
                orders.add(*args)
        for i in range(orders.MAX_ORDERS):
            orders.add(f"o{i}", "rule")
        with self.assertRaises(ValueError):
            orders.add("one-too-many", "rule")
        orders.add("o0", "changed")                       # updating is still allowed
        self.assertEqual(len(orders.list_orders()), orders.MAX_ORDERS)

    def test_prompt_block_only_enabled_and_marks_owner_authority(self):
        self.assertEqual(orders.prompt_block(), "")
        orders.add("a", "Always greet me in Sinhala.")
        orders.add("b", "Never open links from emails.")
        orders.set_enabled("b", False)
        block = orders.prompt_block()
        self.assertIn("set by the owner", block)
        self.assertIn("Always greet me in Sinhala.", block)
        self.assertNotIn("Never open links", block)
        self.assertIn("never standing orders", block)

    def test_block_is_capped(self):
        for i in range(orders.MAX_ORDERS):
            orders.add(f"o{i}", "x" * orders.MAX_TEXT)
        self.assertLessEqual(len(orders.prompt_block()), orders.MAX_BLOCK_CHARS)

    def test_tool_flow(self):
        run = tool.standing_orders
        self.assertEqual(run({"action": "list"}), "No standing orders.")
        self.assertIn("saved", run({"action": "add", "name": "greet", "instruction": "Say hi first."}))
        self.assertIn("greet: Say hi first.", run({"action": "list"}))
        self.assertIn("disabled", run({"action": "disable", "name": "greet"}))
        self.assertIn("(off)", run({"action": "list"}))
        self.assertIn("Not saved", run({"action": "add", "name": "x y!", "instruction": "z"}))
        self.assertIn("No standing order", run({"action": "remove", "name": "zzz"}))
        self.assertIn("Removed", run({"action": "remove", "name": "greet"}))

    def test_tiers(self):
        self.assertEqual(security.tier_for("standing_orders", {"action": "list"}), security.TIER_SAFE)
        for action in ("add", "remove", "enable", "disable"):
            self.assertEqual(security.tier_for("standing_orders", {"action": action}), security.TIER_DANGEROUS)


class StartupNoticeTests(unittest.TestCase):
    def test_interrupted_tasks_are_announced_not_resumed(self):
        import jarvis.main as main_mod
        host = SimpleNamespace()
        pending = [SimpleNamespace(objective="Organise downloads folder"), SimpleNamespace(objective="Research X")]
        service = SimpleNamespace(store=SimpleNamespace(unfinished=lambda: pending), resume_last=MagicMock())
        with patch("jarvis.agent.integration.get_service", return_value=service):
            main_mod.JarvisLive._announce_unfinished_tasks(host)
        text = host._announcements[0]
        self.assertIn("2 autonomous task(s)", text)
        self.assertIn("Organise downloads folder", text)
        self.assertIn("do not resume unless they say so", text)
        service.resume_last.assert_not_called()

    def test_nothing_pending_nothing_announced_and_errors_are_swallowed(self):
        import jarvis.main as main_mod
        host = SimpleNamespace()
        service = SimpleNamespace(store=SimpleNamespace(unfinished=lambda: []))
        with patch("jarvis.agent.integration.get_service", return_value=service):
            main_mod.JarvisLive._announce_unfinished_tasks(host)
        self.assertFalse(hasattr(host, "_announcements"))
        with patch("jarvis.agent.integration.get_service", side_effect=RuntimeError("boom")):
            main_mod.JarvisLive._announce_unfinished_tasks(host)


if __name__ == "__main__":
    unittest.main()
