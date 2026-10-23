"""Unit tests for OCR phrase matching without requiring a screen or Tesseract."""
import unittest

from actions.screen_ocr import find_text_matches


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


if __name__ == "__main__":
    unittest.main()
