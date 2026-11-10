"""P0-2: the owner can turn computer control on/off, and ask why it is unavailable.

docs/research/JARVIS_SYSTEM_AUDIT.md B2: the engine could only be enabled with an
environment variable, and while off even its status tool was hidden.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.computer_control import approval, estop, flags, readiness, runner
from jarvis.computer_control.contract import ContractError, ToolSpec
from jarvis.computer_control.policy import ActionPolicy, AuthSnapshot
from jarvis.computer_control.runner import ActionRunner

OWNER = AuthSnapshot(privacy_locked=False, owner_allowed=True)
STRANGER = AuthSnapshot(privacy_locked=False, owner_allowed=False)
LOCKED = AuthSnapshot(privacy_locked=True, owner_allowed=True)
JARVIS_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture()
def saved(monkeypatch):
    """An in-memory saved setting; never the real config/api_keys.json."""
    store: dict = {}
    monkeypatch.setattr(flags, "_read_saved", lambda: {
        flags.KEY_ENABLED: store.get(flags.KEY_ENABLED) is True,
        flags.KEY_DRY_RUN: store.get(flags.KEY_DRY_RUN) is True})
    monkeypatch.setattr(flags, "_write_saved", store.update)
    monkeypatch.delenv(flags.ENV_ENABLED, raising=False)
    monkeypatch.delenv(flags.ENV_DRY_RUN, raising=False)
    flags.reload_saved()
    yield store
    flags.reload_saved()


@pytest.fixture()
def auth(monkeypatch):
    """Point the default runner's policy at a controllable auth view."""
    holder = {"auth": OWNER}
    estop.reset_for_tests()
    runner.set_runner(ActionRunner(policy=ActionPolicy(auth=lambda: holder["auth"])))
    yield holder
    runner.set_runner(None)
    estop.reset_for_tests()


def _status_payload(**params) -> dict:
    from jarvis.computer_control.tools import build_registry
    decl = {d["name"]: d for d in build_registry().declarations()}["cc_engine_status"]
    return json.loads(decl["handler"](parameters=params))


# ── flag precedence ────────────────────────────────────────────────────────────
class TestFlags:
    def test_off_without_any_choice(self, saved):
        with flags.override():
            assert flags.enabled() is False and flags.source() == "setting"

    def test_saved_setting_turns_it_on(self, saved):
        saved[flags.KEY_ENABLED] = True
        flags.reload_saved()
        with flags.override():
            assert flags.enabled() is True

    def test_environment_off_beats_the_saved_setting(self, saved, monkeypatch):
        saved[flags.KEY_ENABLED] = True
        flags.reload_saved()
        monkeypatch.setenv(flags.ENV_ENABLED, "0")
        with flags.override():
            assert flags.enabled() is False
            assert flags.source() == "environment"
            assert "environment" in flags.describe()

    def test_override_beats_everything(self, saved, monkeypatch):
        monkeypatch.setenv(flags.ENV_ENABLED, "1")
        with flags.override(enabled=False):
            assert flags.enabled() is False

    def test_save_setting_persists_and_notifies(self, saved):
        events = []
        listener = lambda changed, enabled: events.append((changed, enabled))  # noqa: E731
        flags.add_listener(listener)
        try:
            with flags.override():
                message = flags.save_setting(enabled=True)
                assert saved == {flags.KEY_ENABLED: True}
                assert flags.enabled() is True and message == "Computer control is on."
                flags.save_setting(dry_run=True)          # dry-run alone: no tool change
                assert flags.dry_run() is True
                flags.save_setting(enabled=False)
        finally:
            flags.remove_listener(listener)
        assert events == [(True, True), (False, True), (True, False)]

    def test_save_setting_says_when_the_environment_still_decides(self, saved, monkeypatch):
        monkeypatch.setenv(flags.ENV_ENABLED, "0")
        with flags.override():
            message = flags.save_setting(enabled=True)
        assert saved[flags.KEY_ENABLED] is True
        assert "still decides" in message and flags.ENV_ENABLED in message

    def test_a_failing_listener_does_not_undo_the_save(self, saved):
        def broken(changed, enabled):
            raise RuntimeError("listener bug")
        flags.add_listener(broken)
        try:
            with flags.override():
                flags.save_setting(enabled=True)
                assert flags.enabled() is True
        finally:
            flags.remove_listener(broken)


# ── what the model is offered ─────────────────────────────────────────────────
class TestDeclarations:
    def test_only_the_status_tool_is_offered_while_off(self, tmp_path, saved):
        from jarvis.core.action_loader import discover_actions
        (tmp_path / "cc.py").write_text("from jarvis.actions.computer_control_engine import TOOLS\n")
        registry = discover_actions(tmp_path, logger=lambda message: None)
        with flags.override():
            names = [d["name"] for d in registry.get_tool_declarations()]
        assert names == ["cc_engine_status"]

    def test_turning_it_on_offers_every_tool(self, tmp_path, saved):
        from jarvis.core.action_loader import discover_actions
        (tmp_path / "cc.py").write_text("from jarvis.actions.computer_control_engine import TOOLS\n")
        registry = discover_actions(tmp_path, logger=lambda message: None)
        with flags.override():
            flags.save_setting(enabled=True)
            names = {d["name"] for d in registry.get_tool_declarations()}
        assert {"cc_engine_status", "cc_task", "cc_app", "cc_browser", "cc_emergency_stop"} <= names

    def test_only_engine_status_may_be_always_available(self):
        spec = ToolSpec(id="cc_x", action="app.list", description="x", handler=lambda ctx: None,
                        always_available=True)
        with pytest.raises(ContractError):
            spec.validate()
        spec = ToolSpec(id="cc_y", action="app.list", description="y", handler=lambda ctx: None,
                        bypass_runner=True)
        with pytest.raises(ContractError):
            spec.validate()


# ── cc_engine_status ──────────────────────────────────────────────────────────
class TestStatusTool:
    def test_explains_why_while_off(self, saved, auth):
        with flags.override():
            payload = _status_payload()
        assert payload["status"] == "ok"
        assert "Computer control is off" in payload["message"]
        assert "computer_control setting" in payload["message"]
        assert payload["data"]["enabled"] is False
        checks = {c["id"]: c for c in payload["data"]["checks"]}
        assert checks["engine"]["reason"] == "engine_off"

    def test_reports_real_status_in_dry_run(self, auth):
        with flags.override(enabled=True, dry_run=True):
            payload = _status_payload()
        assert payload["status"] == "ok", payload
        assert "would perform" not in payload["message"]
        assert "dry-run" in payload["message"]

    def test_needs_the_owner(self, auth):
        auth["auth"] = STRANGER
        with flags.override(enabled=True):
            payload = _status_payload()
        assert payload["status"] == "denied"
        assert "Owner verification" in payload["message"]
        assert "checks" not in payload["data"]

    def test_hidden_during_privacy_lock(self, auth):
        auth["auth"] = LOCKED
        with flags.override(enabled=True):
            payload = _status_payload()
        assert payload["status"] == "denied" and "Privacy Lock" in payload["message"]

    def test_is_audited(self, auth):
        from jarvis.computer_control import audit
        with flags.override(enabled=True):
            _status_payload()
        assert audit.recent()[-1]["tool"] == "cc.engine.status"


# ── readiness ─────────────────────────────────────────────────────────────────
class TestReadiness:
    def test_every_part_is_reported_with_a_reason(self):
        with flags.override(enabled=True, dry_run=False):
            checks = readiness.report()
        assert [c.id for c in checks] == ["engine", "windows", "browser", "ocr", "vision",
                                          "approval", "stop"]
        assert all(c.reason and c.detail for c in checks)

    def test_unsupported_os_is_named(self, monkeypatch):
        monkeypatch.setattr(readiness.platform, "system", lambda: "Linux")
        check = readiness._windows()
        assert (check.ok, check.reason) == (False, "unsupported_os")
        assert "Linux" in check.detail

    def test_vision_check_never_includes_the_key(self, monkeypatch):
        from jarvis.agent import screen_vision
        monkeypatch.setattr(screen_vision.GeminiVisionProvider, "api_key",
                            lambda self: "AIzaSECRET-KEY-VALUE")
        monkeypatch.setattr(screen_vision.GeminiVisionProvider, "available", lambda self: True)
        check = readiness._vision()
        assert check.ok and "AIzaSECRET" not in json.dumps(check.as_dict())

    def test_approval_prompt_and_stop_states(self):
        approval.set_approver(None)
        assert readiness._approval().reason == "no_prompt"
        approval.bind_native_prompt(lambda request, timeout: None)
        try:
            assert readiness._approval().ok
        finally:
            approval.set_approver(None)
        estop.reset_for_tests()
        estop.get().engage("test hold", source="test")
        try:
            assert readiness._stop().reason == "stop_engaged"
        finally:
            estop.reset_for_tests()

    def test_a_crashing_probe_is_reported_not_raised(self, monkeypatch):
        def boom():
            raise RuntimeError("probe bug")
        monkeypatch.setattr(readiness, "_CHECKS", (readiness._engine, boom))
        checks = readiness.report()
        assert checks[-1].reason == "unknown" and not checks[-1].ok

    def test_summary_lists_ready_and_blocked_parts(self):
        checks = [readiness.Check("engine", "Engine", True, "ok", "On."),
                  readiness.Check("browser", "Web browser", True, "ok", "ready"),
                  readiness.Check("windows", "Windows apps", False, "unsupported_os", "Needs Windows.")]
        text = readiness.summary(checks)
        assert "Ready: Web browser." in text and "Windows apps: Needs Windows." in text


# ── owner switch through jarvis_settings ──────────────────────────────────────
class TestSettingsSwitch:
    @pytest.fixture()
    def banner(self, monkeypatch):
        from jarvis.actions import jarvis_settings
        shown = {}

        def request(*, key, title, detail, run):
            shown.update(key=key, title=title, detail=detail, run=run)
            return "[CONFIRMATION_PENDING]"
        monkeypatch.setattr(jarvis_settings.confirm_gate, "request", request)
        return shown

    def test_turning_on_needs_an_explained_confirmation(self, saved, banner):
        from jarvis.actions.jarvis_settings import jarvis_settings
        with flags.override():
            reply = jarvis_settings({"operation": "set", "setting": "computer_control", "value": "on"})
            assert reply == "[CONFIRMATION_PENDING]" and flags.enabled() is False
            assert banner["title"] == "Turn on computer control"
            assert "Privacy Lock" in banner["detail"] and "Jarvis, stop" in banner["detail"]
            assert banner["run"]() == "Computer control is on."
            assert flags.enabled() is True and saved[flags.KEY_ENABLED] is True

    def test_turning_off_and_dry_run_apply_directly(self, saved, banner):
        from jarvis.actions.jarvis_settings import jarvis_settings
        saved[flags.KEY_ENABLED] = True
        flags.reload_saved()
        with flags.override():
            off = jarvis_settings({"operation": "set", "setting": "computer_control", "value": "off"})
            assert flags.enabled() is False and "off" in off
            jarvis_settings({"operation": "set", "setting": "computer_control_dry_run", "value": "on"})
            assert flags.dry_run() is True
        assert not banner

    def test_get_shows_the_effective_value(self, saved):
        from jarvis.actions.jarvis_settings import jarvis_settings
        with flags.override():
            assert "computer_control is currently False" in jarvis_settings(
                {"operation": "get", "setting": "computer_control"}).replace("computer control", "computer_control")

    def test_changing_it_is_dangerous_for_the_outer_guard(self):
        from jarvis.core.security import TIER_DANGEROUS, tier_for
        assert tier_for("jarvis_settings", {"operation": "set", "setting": "computer_control",
                                            "value": "on"}) == TIER_DANGEROUS

    def test_declared_values(self):
        from jarvis.actions.jarvis_settings import TOOL
        enum = TOOL["parameters"]["properties"]["setting"]["enum"]
        assert {"computer_control", "computer_control_dry_run"} <= set(enum)


# ── live session reacts ───────────────────────────────────────────────────────
class TestLiveSession:
    def _host(self):
        from jarvis.main import JarvisLive
        host = JarvisLive.__new__(JarvisLive)
        logs, reconnects = [], []

        class _UI:
            def write_log(self, text):
                logs.append(text)
        host.ui = _UI()
        host.request_reconnect = lambda keep_context=True, reason="": reconnects.append(
            (keep_context, reason))
        return host, logs, reconnects

    def test_enabling_restarts_the_session_fresh(self):
        host, logs, reconnects = self._host()
        with flags.override(enabled=True):
            host._on_computer_control_setting(True, True)
        assert reconnects == [(False, "computer control on")]
        assert "Restarting the voice session" in logs[-1]

    def test_dry_run_change_does_not_restart(self):
        host, logs, reconnects = self._host()
        host._on_computer_control_setting(False, True)
        assert reconnects == [] and logs == []

    def test_prompt_is_bound_even_while_off(self, saved):
        host, logs, _ = self._host()
        prompt = lambda request, timeout: None  # noqa: E731
        host.ui.computer_control_prompt = lambda: prompt
        approval.set_approver(None)
        try:
            with flags.override():
                host._bind_computer_control()
            assert isinstance(approval.get_approver(), approval.NativeApprover)
            assert logs == []                     # nothing announced while off
        finally:
            flags.remove_listener(host._on_computer_control_setting)
            approval.set_approver(None)
