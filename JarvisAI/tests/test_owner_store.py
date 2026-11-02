"""Module 6: SQLite rules/routines/facts, event hook, watchers, session context."""
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

JARVIS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for p in (JARVIS_DIR, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from core import events, mail_calendar, owner_store  # noqa: E402


class _StoreCase(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "owner.db"
        owner_store.reset_owner_store_for_tests(owner_store.OwnerStore(self.db))
        events.reset_for_tests()
        self.fired = []
        events.set_rule_executor(lambda rule, source, payload: self.fired.append(
            (rule["name"], source, payload)))

    def tearDown(self):
        owner_store.reset_owner_store_for_tests(None)
        events.reset_for_tests()

    def restart(self):
        owner_store.reset_owner_store_for_tests(owner_store.OwnerStore(self.db))


class PersistenceTests(_StoreCase):
    def test_rules_routines_and_facts_survive_a_restart(self):
        from actions.owner_memory import facts, rules
        rules({"action": "add", "name": "Bank mail", "source": "email",
               "conditions": {"from": "mybank"}, "rule_action": "flag"})
        facts({"action": "remember", "key": "car", "value": "blue Corolla"})
        owner_store.get_owner_store().routines.save("work mode", [{"tool": "open", "args": {"target": "x"}}])
        self.restart()
        store = owner_store.get_owner_store()
        self.assertEqual(store.rules.get("bank mail")["conditions"], {"from": "mybank"})
        self.assertEqual(store.facts.get("car"), "blue Corolla")
        self.assertEqual(store.routines.get("Work Mode")["steps"][0]["tool"], "open")

    def test_edit_and_delete(self):
        from actions.owner_memory import facts, rules
        rules({"action": "add", "name": "r", "source": "email", "conditions": {"from": "a"}})
        rules({"action": "edit", "name": "r", "conditions": {"from": "b"}})
        self.assertEqual(owner_store.get_owner_store().rules.get("r")["conditions"], {"from": "b"})
        self.assertIn("disabled", rules({"action": "disable", "name": "r"}))
        self.assertIn("Deleted", rules({"action": "delete", "name": "r"}))
        facts({"action": "remember", "key": "k", "value": "v1"})
        facts({"action": "edit", "key": "k", "value": "v2"})
        self.assertIn("k: v2", facts({"action": "list"}))
        self.assertIn("Forgot", facts({"action": "forget", "key": "k"}))

    def test_store_stays_small(self):
        store = owner_store.get_owner_store()
        with self.assertRaises(ValueError):
            store.facts.remember("long", "x" * (owner_store.MAX_FACT_CHARS + 1))
        with self.assertRaises(ValueError):
            store.rules.save("bad", "email", {}, "explode")


class RuleFiringTests(_StoreCase):
    def test_rule_fires_on_a_matching_event_only(self):
        store = owner_store.get_owner_store()
        store.rules.save("flag bank", "email", {"from": "MyBank"}, "flag")
        store.rules.save("any download", "file", {"name": ".pdf"}, "notify",
                         {"message": "New PDF: {name}"})
        self.assertEqual(events.emit("email", {"from": "alerts@mybank.com", "subject": "Hi"}),
                         ["flag bank"])
        self.assertEqual(events.emit("email", {"from": "friend@x.com"}), [])
        self.assertEqual(events.emit("file", {"name": "invoice.pdf"}), ["any download"])
        self.assertEqual(store.rules.get("flag bank")["fire_count"], 1)
        self.assertEqual([f[0] for f in self.fired], ["flag bank", "any download"])

    def test_wildcard_source_and_text_condition(self):
        owner_store.get_owner_store().rules.save("urgent", "*", {"text": "urgent"}, "notify")
        self.assertEqual(events.emit("custom_plugin", {"title": "URGENT: server down"}), ["urgent"])

    def test_rules_tool_test_action(self):
        from actions.owner_memory import rules
        rules({"action": "add", "name": "t", "source": "test", "conditions": {"text": "ping"}})
        self.assertIn("Test event fired: t", rules({"action": "test", "source": "test",
                                                     "payload": {"msg": "ping"}}))


class WatcherTests(_StoreCase):
    def test_file_watcher_emits_new_files(self):
        from actions import event_sources as es
        folder = Path(tempfile.mkdtemp())
        owner_store.get_owner_store().rules.save("downloads", "file", {}, "notify",
                                                 {"folder": str(folder)})
        es._state.update(file_at=0.0, snapshots={})
        es.check_files(now=1000.0)                      # baseline
        (folder / "report.pdf").write_text("x", encoding="utf-8")
        es.check_files(now=1000.0 + es.FILE_EVERY + 1)
        self.assertEqual(self.fired[0][0], "downloads")
        self.assertEqual(self.fired[0][2]["change"], "created")

    def test_email_watcher_emits_each_new_message_once(self):
        from actions import event_sources as es

        class Mail(mail_calendar.MailProvider):
            name = "fake"
            def is_configured(self): return True
            def list_messages(self, query="", max_results=10):
                return [{"id": "1", "from": "boss@work.com", "subject": "Report", "date": "", "snippet": ""}]
            def read_message(self, i): return {}
            def create_draft(self, *a): return ""
            def send_message(self, *a): return ""

        mail_calendar.reset_for_tests()
        mail_calendar.register_mail_provider(Mail())
        owner_store.get_owner_store().rules.save("boss", "email", {"from": "boss@"}, "flag")
        es._state.update(email_at=0.0, seen_mail=set())
        es.check_email(now=10_000.0)
        es.check_email(now=10_000.0 + es.EMAIL_EVERY + 1)
        self.assertEqual([f[0] for f in self.fired], ["boss"])


class SessionAndExecutorTests(_StoreCase):
    def test_session_context_lists_facts_rules_routines(self):
        store = owner_store.get_owner_store()
        store.facts.remember("wifi", "home network is JARVIS-5G")
        store.rules.save("bank", "email", {"from": "bank"}, "flag")
        store.routines.save("work mode", [{"tool": "open", "args": {}}])
        text = owner_store.session_context()
        for needle in ("[OWNER STORE]", "wifi: home network is JARVIS-5G", "bank: on email",
                       "Saved routines: work mode"):
            self.assertIn(needle, text)


class LiveExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Path(tempfile.mkdtemp()) / "owner.db"
        owner_store.reset_owner_store_for_tests(owner_store.OwnerStore(self.db))

    async def asyncTearDown(self):
        owner_store.reset_owner_store_for_tests(None)
        events.reset_for_tests()

    async def test_notify_rule_is_announced_and_tool_rule_runs_a_tool(self):
        import live_replay
        host = live_replay.build_host()
        events.set_rule_executor(host._execute_rule_action)
        store = owner_store.get_owner_store()
        store.rules.save("bank", "email", {"from": "bank"}, "notify",
                         {"message": "Email from {from}: {subject}"})
        store.rules.save("log it", "email", {"from": "bank"}, "tool",
                         {"tool": "facts", "args": {"action": "remember", "key": "last bank mail",
                                                    "value": "{subject}"}})
        with patch("core.action_log.log_path", return_value=Path(tempfile.mkdtemp()) / "a.jsonl"), \
             patch("core.security.guard", side_effect=lambda _n, _a, run: run()):
            await asyncio.to_thread(events.emit, "email",
                                    {"from": "alerts@bank.com", "subject": "Statement ready"})
            for _ in range(100):
                if store.facts.get("last bank mail"):
                    break
                await asyncio.sleep(0.02)
        self.assertIn("Email from alerts@bank.com: Statement ready", host._announcements[-1])
        self.assertEqual(store.facts.get("last bank mail"), "Statement ready")

    async def test_schedule_trigger_emits_a_schedule_event(self):
        from core.runtime.live_services import BackgroundServicesMixin as M
        seen = []
        events.set_rule_executor(lambda rule, source, payload: seen.append((source, payload["name"])))
        owner_store.get_owner_store().rules.save("morning", "schedule", {"name": "brief"}, "notify")
        host = SimpleNamespace(_awake=True, ui=SimpleNamespace(write_log=lambda *_: None),
                               session=SimpleNamespace(send_client_content=lambda **_: asyncio.sleep(0)))
        await M._fire_trigger(host, SimpleNamespace(name="brief"), "Morning briefing")
        self.assertEqual(seen, [("schedule", "brief")])


if __name__ == "__main__":
    unittest.main()
