"""P0-3: steer the model to the Computer Control Engine while it is on (audit B3)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.computer_control import flags, routing
from jarvis.eval import tool_choice

READY = {"windows": True, "browser": True}
NOTHING_READY = {"windows": False, "browser": False}


@pytest.fixture()
def mode(monkeypatch):
    """Set the routing mode (engine on) for one test."""
    monkeypatch.delenv(flags.ENV_ROUTING, raising=False)

    def set_mode(name: str | None):
        if name is None:
            monkeypatch.delenv(flags.ENV_ROUTING, raising=False)
        else:
            monkeypatch.setenv(flags.ENV_ROUTING, name)
    return set_mode


# ── which tools are hidden ────────────────────────────────────────────────────
class TestHiddenTools:
    @pytest.mark.parametrize("name", ["both", "prefer_engine"])
    def test_nothing_hidden_unless_engine_only(self, mode, name):
        mode(name)
        with flags.override(enabled=True):
            assert routing.hidden_tools(READY) == frozenset()

    def test_nothing_hidden_while_the_engine_is_off(self, mode):
        mode("engine_only")
        with flags.override(enabled=False):
            assert routing.active_mode() == "off"
            assert routing.hidden_tools(READY) == frozenset()

    def test_engine_only_hides_what_the_ready_engine_replaces(self, mode):
        mode("engine_only")
        with flags.override(enabled=True):
            assert routing.hidden_tools(READY) == {"computer_control", "ui_interaction",
                                                   "ui_automate", "browser_control"}
            assert routing.hidden_tools({"windows": False, "browser": True}) == {"browser_control"}
            assert routing.hidden_tools(NOTHING_READY) == frozenset()

    def test_file_tools_open_app_screen_and_engineering_tools_are_never_hidden(self):
        for keep in ("files", "file_controller", "open_app", "screen_process", "autonomous_task",
                     "computer_settings", "see_screen"):
            assert keep not in routing.SUPERSEDED

    def test_default_mode_is_prefer_engine(self, mode):
        with flags.override(enabled=True):
            assert flags.tool_routing() == "prefer_engine"
        mode("not-a-mode")
        assert flags.tool_routing() == "prefer_engine"
        mode("engine only")
        assert flags.tool_routing() == "engine_only"


# ── the routing section of the system prompt ──────────────────────────────────
class TestPromptBlock:
    OFFERED = {"cc_task", "cc_app", "cc_browser", "cc_file", "cc_screen", "autonomous_task",
               "screen_process", "open_app"}

    def test_absent_for_both_or_when_off(self, mode):
        mode("both")
        with flags.override(enabled=True):
            assert routing.prompt_block(self.OFFERED, ready=READY) == ""
        mode("prefer_engine")
        with flags.override(enabled=False):
            assert routing.prompt_block(self.OFFERED, ready=READY) == ""

    def test_prefer_engine_routes_desktop_and_multi_step_work(self, mode):
        mode("prefer_engine")
        with flags.override(enabled=True):
            text = routing.prompt_block(self.OFFERED, ready=READY)
        assert text.startswith("[COMPUTER CONTROL ROUTING]")
        assert "cc_task" in text and "exception to" in text
        assert "cc_browser" in text and "screen_process" in text and "autonomous_task" in text

    def test_says_windows_control_is_unavailable_when_it_is(self, mode):
        mode("prefer_engine")
        with flags.override(enabled=True):
            text = routing.prompt_block(self.OFFERED, ready=NOTHING_READY)
        assert "not available on this computer" in text
        assert "cc_browser" not in text        # browser not ready -> not recommended

    def test_never_names_a_tool_that_is_not_offered(self, mode):
        mode("prefer_engine")
        with flags.override(enabled=True):
            text = routing.prompt_block({"cc_task", "screen_process"}, ready=READY)
            assert "cc_file" not in text and "autonomous_task" not in text and "cc_browser" not in text
            assert routing.prompt_block({"screen_process"}, ready=READY) == ""


# ── settings and session restart ─────────────────────────────────────────────
class TestSetting:
    @pytest.fixture()
    def saved(self, monkeypatch):
        store: dict = {}
        monkeypatch.setattr(flags, "_read_saved", lambda: {
            flags.KEY_ENABLED: store.get(flags.KEY_ENABLED) is True,
            flags.KEY_DRY_RUN: False,
            flags.KEY_ROUTING: flags._routing_value(store.get(flags.KEY_ROUTING))})
        monkeypatch.setattr(flags, "_write_saved", store.update)
        for name in (flags.ENV_ENABLED, flags.ENV_ROUTING):
            monkeypatch.delenv(name, raising=False)
        flags.reload_saved()
        yield store
        flags.reload_saved()

    def test_routing_change_restarts_the_session_only_while_on(self, saved):
        events = []
        listener = lambda changed, enabled: events.append((changed, enabled))  # noqa: E731
        flags.add_listener(listener)
        try:
            with flags.override():
                flags.save_setting(routing="engine_only")        # engine off: no restart
                flags.save_setting(enabled=True)
                flags.save_setting(routing="both")               # engine on: restart
                flags.save_setting(routing="both")               # unchanged: no restart
        finally:
            flags.remove_listener(listener)
        assert events == [(False, False), (True, True), (True, True), (False, True)]
        assert saved[flags.KEY_ROUTING] == "both"

    def test_jarvis_settings_accepts_spoken_values(self, saved):
        from jarvis.actions.jarvis_settings import TOOL, jarvis_settings
        with flags.override():
            reply = jarvis_settings({"operation": "set", "setting": "computer_control_tool_routing",
                                     "value": "Engine Only"})
            assert flags.tool_routing() == "engine_only" and "Tool routing: engine_only" in reply
            assert "Invalid" in jarvis_settings({"operation": "set",
                                                 "setting": "computer_control_tool_routing",
                                                 "value": "everything"})
        assert "computer_control_tool_routing" in TOOL["parameters"]["properties"]["setting"]["enum"]

    def test_live_session_helper_hides_nothing_when_routing_fails(self, monkeypatch):
        from jarvis.main import JarvisLive
        host = JarvisLive.__new__(JarvisLive)
        monkeypatch.setenv(flags.ENV_ROUTING, "engine_only")
        monkeypatch.setattr(routing, "_ready", lambda parts: (_ for _ in ()).throw(RuntimeError("x")))
        with flags.override(enabled=True):
            assert host._computer_control_routing() == ({}, frozenset())

    def test_live_session_helper_uses_routing(self, monkeypatch):
        from jarvis.main import JarvisLive
        host = JarvisLive.__new__(JarvisLive)
        monkeypatch.setenv(flags.ENV_ROUTING, "engine_only")
        monkeypatch.setattr(routing, "_ready", lambda parts: dict(READY))
        with flags.override(enabled=True):
            ready, hidden = host._computer_control_routing()
        assert ready == READY and "computer_control" in hidden
        with flags.override(enabled=False):
            assert host._computer_control_routing() == ({}, frozenset())


# ── the eval harness ──────────────────────────────────────────────────────────
class TestEval:
    def test_cases_only_name_real_tools(self):
        app, actions, plugins = tool_choice._registries()
        with flags.override(enabled=True):
            names = ({d["name"] for d in app.TOOL_DECLARATIONS}
                     | {d["name"] for d in actions.get_tool_declarations()}
                     | {d["name"] for d in plugins.get_tool_declarations()})
        for case in tool_choice.load_cases():
            unknown = (set(case.accept) | set(case.engine)) - names
            assert not unknown, (case.id, unknown)

    @pytest.mark.parametrize("ready", [READY, NOTHING_READY, {"windows": False, "browser": True}])
    def test_every_mode_leaves_every_request_a_tool(self, ready):
        report = tool_choice.offline_report(tool_choice.load_cases(), ready=ready)
        for mode_name, row in report["modes"].items():
            assert row["cases_without_an_offered_tool"] == [], (mode_name, ready)
        assert report["modes"]["engine_only"]["tools"] <= report["modes"]["both"]["tools"]
        assert report["modes"]["prefer_engine"]["routing_section"]
        assert not report["modes"]["both"]["routing_section"]

    def test_engine_only_really_removes_the_tools_from_the_declarations(self):
        setup = tool_choice.build_setup("engine_only", ready=READY)
        names = {d["name"] for d in setup.declarations}
        assert not names & set(routing.SUPERSEDED)
        assert {"cc_task", "cc_control", "open_app", "files"} <= names

    def test_score(self):
        case = tool_choice.Case("x", "t", ("open_app",), ("cc_app",))
        assert tool_choice.score(case, ["cc_app"]) == "engine"
        assert tool_choice.score(case, ["open_app", "cc_app"]) == "accepted"
        assert tool_choice.score(case, ["web_search"]) == "other"
        assert tool_choice.score(case, []) == "no_tool"

    def test_live_run_records_the_first_tool_and_never_executes(self):
        sent, configs = [], []

        class _Session:
            async def send_client_content(self, *, turns, turn_complete):
                sent.append(turns["parts"][0]["text"])

            async def receive(self):
                text = sent[-1]
                name = "cc_task" if "Notepad" in text else "computer_settings"
                yield SimpleNamespace(tool_call=SimpleNamespace(
                    function_calls=[SimpleNamespace(name=name, args={})]), server_content=None)
                raise AssertionError("the eval must stop reading after the first tool call")

        class _Connect:
            def __init__(self, config):
                configs.append(config)

            async def __aenter__(self):
                return _Session()

            async def __aexit__(self, *exc):
                return False

        client = SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(
            connect=lambda model, config: _Connect(config))))
        cases = [tool_choice.Case("n", "Open Notepad and save a note.", ("ui_automate",), ("cc_task",)),
                 tool_choice.Case("v", "Volume to 30.", ("computer_settings",), ())]
        result = asyncio.run(tool_choice.run_live(cases, ["prefer_engine"], client=client,
                                                  model="test-model"))
        row = result["modes"]["prefer_engine"]
        assert row["counts"]["engine"] == 1 and row["counts"]["accepted"] == 1
        assert row["engine_rate"] == 1.0 and row["useful_rate"] == 1.0
        assert "[COMPUTER CONTROL ROUTING]" in configs[0]["system_instruction"]
        assert all("handler" not in d for d in configs[0]["tools"][0]["function_declarations"])
