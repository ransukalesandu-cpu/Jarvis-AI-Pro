"""Regression coverage for appending signed memory events after legacy rows."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory.memory_audit import _verify_signed_events
from memory.memory_manager import _append_audit, _audit_signature


class MemoryAuditUnsignedTailTests(unittest.TestCase):
    def test_new_event_links_to_latest_signed_event_not_unsigned_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with patch("memory.memory_manager.BASE_DIR", base):
                first = {
                    "id": "signed-first",
                    "memory_id": "memory-1",
                    "action": "create",
                    "actor": "system",
                    "at": "2026-01-01T00:00:00",
                    "why": "initial fact",
                    "previous_hash": "",
                }
                first["hmac"] = _audit_signature(first)
                legacy_unsigned = {
                    "id": "legacy-unsigned",
                    "memory_id": "memory-legacy",
                    "action": "migration_import",
                    "actor": "system",
                    "at": "2026-01-01T00:00:01",
                    "why": "legacy compatibility row",
                }
                memory = {"memory_audit": [first, legacy_unsigned]}

                _append_audit(memory, "memory-2", "create", "system", "new fact")

                last = memory["memory_audit"][-1]
                self.assertEqual(last["previous_hash"], first["hmac"])
                key = (base / "config" / "memory_audit.key").read_bytes()
                checked, reason = _verify_signed_events(memory["memory_audit"], key)
                self.assertEqual(reason, "")
                self.assertEqual(checked, 2)


if __name__ == "__main__":
    unittest.main()
