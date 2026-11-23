"""Owner-written routines file: parsing, phrase matching, routine tool integration."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from jarvis.core import routines_file

YAML = """
morning:
  description: Start the day
  phrases: ["Good morning", "morning mode"]
  steps:
    - {tool: open_app, args: {app_name: Outlook}}
    - {tool: phone_control, args: {action: mute_volume}}
work mode:
  phrases: "let's work"
  steps:
    - {tool: open_app, args: {app_name: Code}}
broken:
  steps: []
"""


@pytest.fixture(autouse=True)
def _fresh():
    routines_file.clear_cache()
    yield
    routines_file.clear_cache()


def test_yaml_parse_and_errors(tmp_path):
    (tmp_path / "routines.yaml").write_text(YAML, encoding="utf-8")
    routines, errors = routines_file.load(tmp_path)
    assert set(routines) == {"morning", "work mode"}
    assert routines["morning"]["phrases"] == ["good morning", "morning mode"]
    assert routines["work mode"]["phrases"] == ["let s work"]
    assert len(routines["morning"]["steps"]) == 2
    assert any("broken" in e for e in errors)


def test_json_file(tmp_path):
    (tmp_path / "routines.json").write_text(json.dumps({"routines": {
        "night": {"phrases": ["good night"], "steps": [{"tool": "pc_tools", "args": {"op": "lock"}}]}}}))
    assert routines_file.match_phrase("Good night!", tmp_path) == "night"


def test_phrase_matching_is_exact(tmp_path):
    (tmp_path / "routines.yaml").write_text(YAML, encoding="utf-8")
    m = lambda t: routines_file.match_phrase(t, tmp_path)  # noqa: E731
    assert m("Good morning") == "morning"
    assert m("Jarvis, good morning.") == "morning"
    assert m("start work mode") == "work mode"
    assert m("run morning routine") == "morning"
    assert m("let's work") == "work mode"
    assert m("good morning, what's the weather like") is None
    assert m("tell me about the morning news") is None
    assert m("") is None


def test_missing_file_and_bad_syntax(tmp_path):
    assert routines_file.load(tmp_path) == ({}, [])
    (tmp_path / "routines.json").write_text("{not json")
    routines, errors = routines_file.load(tmp_path)
    assert routines == {} and errors


def test_routine_tool_lists_and_runs_file_routines(tmp_path):
    (tmp_path / "routines.yaml").write_text(YAML, encoding="utf-8")
    from jarvis.actions import routines as action

    class Store:
        def list(self):
            return []

        def get(self, name):
            return None

        def delete(self, name):
            return False

        def mark_run(self, name):
            raise AssertionError("file routines are not marked in the store")

    calls = []
    with patch.object(action, "get_routine_store", return_value=Store()), \
            patch.object(routines_file, "_dir", return_value=tmp_path):
        listing = action.routine({"action": "list"})
        assert "morning [routines file] (say: good morning, morning mode)" in listing
        assert "Routines file problem" in listing
        out = action.routine({"action": "run", "name": "Morning"},
                             dispatch=lambda tool, args: calls.append((tool, args)) or "ok")
        assert "Ran routine 'morning'" in out
        assert calls == [("open_app", {"app_name": "Outlook"}), ("phone_control", {"action": "mute_volume"})]
        assert "only the owner" in action.routine({"action": "delete", "name": "morning"})


def test_typed_phrase_starts_routine(tmp_path):
    (tmp_path / "routines.yaml").write_text(YAML, encoding="utf-8")
    from jarvis.core.runtime.live_text import TextCommandMixin

    class Ui:
        def __init__(self):
            self.logs = []

        def write_log(self, m):
            self.logs.append(m)

    class Live(TextCommandMixin):
        _loop = None
        session = None

        def __init__(self):
            self.ui = Ui()
            self.dispatched = []
            self.spoken = []

        def _dispatch_tool_sync(self, name, args, timeout=0):
            self.dispatched.append((name, args))
            return "Ran routine 'morning':\n1. open_app: ok"

        def _speak_offline(self, text):
            self.spoken.append(text)

    live = Live()
    with patch.object(routines_file, "_dir", return_value=tmp_path), \
            patch("jarvis.core.security.mark_user_turn_started"), \
            patch("threading.Thread") as thread:
        thread.return_value.start.side_effect = lambda: thread.call_args.kwargs["target"]()
        assert live._run_phrase_routine("Good morning")
        assert not live._run_phrase_routine("good morning and the news")
    assert live.dispatched == [("routine", {"action": "run", "name": "morning"})]
    assert live.spoken == ["Ran routine 'morning':"]
