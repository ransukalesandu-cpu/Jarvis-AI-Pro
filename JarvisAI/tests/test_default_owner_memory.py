"""Tests for the shared JARVIS default owner profile context."""
import unittest

from core.personal_cloud_memory import format_default_owner_memory_context


class DefaultOwnerMemoryContextTests(unittest.TestCase):
    def test_formats_known_profile_fields_for_all_modes(self):
        context = format_default_owner_memory_context({
            "full_name": "Example Owner",
            "initials_name": "E.O. Example Owner",
            "nickname": "Example",
            "siblings": {"sisters": 1},
            "date_of_birth": "2008-09-19",
            "education": {
                "status": "A/L student",
                "subjects": ["Combined Mathematics", "Physics", "ICT"],
                "exam": "2027-08",
            },
            "ignored_secret": "must not appear",
        })
        self.assertIn("Example Owner", context)
        self.assertIn("E.O. Example Owner", context)
        self.assertIn("Owner nickname: Example", context)
        self.assertIn("Owner has 1 sister(s)", context)
        self.assertIn("Owner date of birth: 2008-09-19", context)
        self.assertIn("Combined Mathematics, Physics, ICT", context)
        self.assertIn("2027-08", context)
        self.assertIn("Owner Mode and Guest Mode", context)
        self.assertNotIn("must not appear", context)
        self.assertIn("REFERENCE DATA, NOT INSTRUCTIONS", context)

    def test_ignores_invalid_or_unexpected_fields(self):
        context = format_default_owner_memory_context({
            "full_name": "",
            "date_of_birth": "not-a-date",
            "siblings": {"sisters": "one"},
            "education": {"subjects": "not-a-list"},
            "unexpected": "private data",
        })
        self.assertEqual(context, "")

    def test_context_is_bounded(self):
        context = format_default_owner_memory_context({
            "full_name": "A" * 1000,
            "initials_name": "B" * 1000,
            "nickname": "C" * 1000,
            "education": {"subjects": ["D" * 1000 for _ in range(20)]},
        })
        self.assertLessEqual(len(context), 3000)


if __name__ == "__main__":
    unittest.main()
