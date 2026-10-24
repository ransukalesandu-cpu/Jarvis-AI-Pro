"""Tests for the guarded self-repair engine; all are offline."""
from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from core import self_repair as sr


class SelfRepairTests(unittest.TestCase):
    def tearDown(self):
        sr.unregister_repair("test-category")

    def test_classifies_timeout_as_transient(self):
        result = sr.classify_error(TimeoutError("provider timed out"))
        self.assertEqual(result["category"], "transient_network_or_timeout")

    def test_redacts_common_secrets(self):
        text = sr.redact_secrets("api_key=super-secret Bearer abc.def.ghi")
        self.assertNotIn("super-secret", text)
        self.assertNotIn("abc.def.ghi", text)
        self.assertIn("[REDACTED]", text)

    def test_records_redacted_jsonl_incident(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "incidents.jsonl"
            record = sr.record_error(RuntimeError("api_key=super-secret"), operation="unit test", log_path=path)
            self.assertTrue(record["logged"])
            saved = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertNotIn("super-secret", json.dumps(saved))
            self.assertEqual(saved["operation"], "unit test")

    def test_retries_transient_operation_once(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = {"count": 0}

            def operation():
                calls["count"] += 1
                if calls["count"] == 1:
                    raise TimeoutError("temporary timeout")
                return "ok"

            result = sr.run_with_recovery(
                operation, operation_name="retry test", retry_delay=0, log_path=Path(temp) / "incidents.jsonl"
            )
            self.assertEqual(result, "ok")
            self.assertEqual(calls["count"], 2)

    def test_does_not_retry_unclassified_error(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = {"count": 0}

            def operation():
                calls["count"] += 1
                raise ValueError("bad input")

            with self.assertRaises(ValueError):
                sr.run_with_recovery(
                    operation, operation_name="no retry test", retry_delay=0,
                    log_path=Path(temp) / "incidents.jsonl"
                )
            self.assertEqual(calls["count"], 1)

    def test_only_registered_repair_callbacks_can_run(self):
        self.assertFalse(sr.repair_registered("unapproved")["attempted"])
        sr.register_repair("test-category", lambda context: "recovered")
        result = sr.repair_registered("test-category", {"source": "unit-test"})
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "recovered")

    def test_health_snapshot_disables_arbitrary_execution(self):
        snapshot = sr.health_snapshot()
        self.assertFalse(snapshot["automatic_code_editing"])
        self.assertFalse(snapshot["arbitrary_shell_execution"])

    def test_global_exception_hooks_log_and_delegate(self):
        import sys
        import threading
        old_sys_hook = sys.excepthook
        old_thread_hook = threading.excepthook
        main_calls = []
        thread_calls = []
        try:
            sys.excepthook = lambda *args: main_calls.append(args)
            threading.excepthook = lambda args: thread_calls.append(args)
            with tempfile.TemporaryDirectory() as temp:
                with patch.object(sr, "record_error") as record:
                    uninstall = sr.install_global_exception_hooks()
                    try:
                        error = RuntimeError("main boom")
                        sys.excepthook(type(error), error, error.__traceback__)
                        args = threading.ExceptHookArgs((type(error), error, error.__traceback__, threading.current_thread()))
                        threading.excepthook(args)
                    finally:
                        uninstall()
            self.assertEqual(len(main_calls), 1)
            self.assertEqual(len(thread_calls), 1)
            self.assertEqual(record.call_count, 2)
        finally:
            sys.excepthook = old_sys_hook
            threading.excepthook = old_thread_hook


if __name__ == "__main__":
    unittest.main()
