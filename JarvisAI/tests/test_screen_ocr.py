"""Unit tests for OCR phrase matching and Tesseract path resolution."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from actions.screen_ocr import _configure_tesseract, _record_ocr_error, find_text_matches


def word(text, x, y=10, confidence=90, line=(1, 1, 1), w=None):
    return {
        "text": text, "x": x, "y": y, "w": w or max(8, len(text) * 7),
        "h": 14, "confidence": confidence, "line": line,
    }


class ScreenOCRMatchingTests(unittest.TestCase):
    def test_matches_phrase_across_adjacent_words(self):
        words = [word("Save", 10), word("Changes", 55), word("Cancel", 150)]
        matches = find_text_matches("Save Changes", words)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["text"], "Save Changes")
        self.assertGreater(matches[0]["x"], 10)

    def test_does_not_match_partial_word(self):
        words = [word("SaveAs", 10)]
        self.assertEqual(find_text_matches("Save", words), [])

    def test_duplicate_labels_remain_ambiguous(self):
        words = [
            word("Settings", 10, line=(1, 1, 1)),
            word("Settings", 200, line=(2, 1, 1)),
        ]
        matches = find_text_matches("Settings", words)
        self.assertEqual(len(matches), 2)

    def test_matching_is_case_and_punctuation_insensitive(self):
        words = [word("SAVE", 10), word("Changes!", 55)]
        self.assertEqual(len(find_text_matches("save changes", words)), 1)

    def test_empty_target_returns_no_matches(self):
        self.assertEqual(find_text_matches("  ", [word("Save", 10)]), [])

    @patch("actions.screen_ocr.shutil.which", return_value="C:/Tools/tesseract.exe")
    def test_path_install_is_preferred(self, _which):
        fake = SimpleNamespace(pytesseract=SimpleNamespace(tesseract_cmd="tesseract"))
        _configure_tesseract(fake)
        self.assertEqual(fake.pytesseract.tesseract_cmd, "tesseract")

    @patch("actions.screen_ocr.Path.is_file", return_value=True)
    @patch("actions.screen_ocr.shutil.which", return_value=None)
    @patch("actions.screen_ocr.platform.system", return_value="Windows")
    def test_standard_windows_installer_path_is_used(self, _system, _which, _is_file):
        fake = SimpleNamespace(pytesseract=SimpleNamespace(tesseract_cmd="tesseract"))
        _configure_tesseract(fake)
        self.assertEqual(
            fake.pytesseract.tesseract_cmd,
            str(Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")),
        )

    def test_ocr_error_is_sent_to_self_repair_logger(self):
        with patch("actions.screen_ocr.self_repair.record_error") as record:
            _record_ocr_error(RuntimeError("OCR failed"), "screen_ocr:test")
        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs["operation"], "screen_ocr:test")

    def test_ocr_error_logger_does_not_mask_original_failure(self):
        with patch("actions.screen_ocr.self_repair.record_error", side_effect=OSError("disk full")):
            _record_ocr_error(RuntimeError("OCR failed"), "screen_ocr:test")


if __name__ == "__main__":
    unittest.main()
