"""Regression tests for safe Gemini Live API-key configuration loading."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import _get_api_key


class LiveAPIKeyConfigTests(unittest.TestCase):
    def _with_config_path(self, path, callback):
        with patch("main.API_CONFIG_PATH", Path(path)):
            return callback()

    def test_valid_key_is_trimmed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api_keys.json"
            path.write_text(json.dumps({"gemini_api_key": "  test-key  "}), encoding="utf-8")
            key = self._with_config_path(path, _get_api_key)
        self.assertEqual(key, "test-key")

    def test_missing_file_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            with patch("main.API_CONFIG_PATH", path):
                with self.assertRaisesRegex(RuntimeError, "configuration file is missing"):
                    _get_api_key()

    def test_invalid_json_does_not_echo_file_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api_keys.json"
            path.write_text('{"gemini_api_key": "SECRET', encoding="utf-8")
            with patch("main.API_CONFIG_PATH", path):
                with self.assertRaisesRegex(RuntimeError, "unreadable or invalid JSON") as caught:
                    _get_api_key()
        self.assertNotIn("SECRET", str(caught.exception))

    def test_non_object_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api_keys.json"
            path.write_text("[]", encoding="utf-8")
            with patch("main.API_CONFIG_PATH", path):
                with self.assertRaisesRegex(RuntimeError, "JSON object"):
                    _get_api_key()

    def test_missing_or_blank_key_is_rejected(self):
        for config in ({"other": "value"}, {"gemini_api_key": "  "}):
            with self.subTest(config=config):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "api_keys.json"
                    path.write_text(json.dumps(config), encoding="utf-8")
                    with patch("main.API_CONFIG_PATH", path):
                        with self.assertRaisesRegex(RuntimeError, "gemini_api_key entry"):
                            _get_api_key()


if __name__ == "__main__":
    unittest.main()
