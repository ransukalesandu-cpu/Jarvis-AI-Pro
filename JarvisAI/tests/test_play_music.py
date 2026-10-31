from __future__ import annotations

import unittest
from unittest.mock import Mock

from actions.play_music import play_music


class TestPlayMusic(unittest.TestCase):
    def test_opens_youtube_music_inside_hud(self):
        player = Mock()
        result = play_music({"query": "Daft Punk - Get Lucky"}, player=player)

        player.show_webpage.assert_called_once_with(
            "https://music.youtube.com/search?q=Daft+Punk+-+Get+Lucky",
            "YOUTUBE MUSIC",
        )
        self.assertIn("inside JARVIS", result)

    def test_empty_query_does_not_open_workspace(self):
        player = Mock()
        result = play_music({"query": "  "}, player=player)

        player.show_webpage.assert_not_called()
        self.assertIn("song title", result)

    def test_missing_hud_does_not_launch_external_app(self):
        result = play_music({"query": "ambient music"})

        self.assertIn("workspace is unavailable", result)

    def test_workspace_failure_is_reported(self):
        player = Mock()
        player.show_webpage.side_effect = RuntimeError("web engine unavailable")

        result = play_music({"query": "ambient music"}, player=player)

        self.assertIn("Could not open YouTube Music", result)


if __name__ == "__main__":
    unittest.main()
