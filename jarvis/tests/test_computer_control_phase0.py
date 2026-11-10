"""Phase 0 of the Computer Control Engine: flag, policy, approval, stop, audit, runner, contract."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.computer_control import approval, audit, estop, flags, runner
from jarvis.computer_control.contract import ContractError, SpecRegistry, ToolSpec
from jarvis.computer_control.policy import (
    ActionPolicy, AuthSnapshot, Level, Origin, protected_path_reason,
)
from jarvis.computer_control.runner import ActionOutcome, ActionRunner

OWNER = AuthSnapshot(privacy_locked=False, owner_allowed=True)
LOCKED = AuthSnapshot(privacy_locked=True, owner_allowed=False)
STRANGER = AuthSnapshot(privacy_locked=False, owner_allowed=False)
JARVIS_DIR = Path(__file__).resolve().parents[1]


def make_runner(auth=OWNER, approver=None) -> ActionRunner:
    policy = ActionPolicy(auth=lambda: auth)
    return ActionRunner(policy, approver=(lambda: approver) if approver else None)


class _Approver:
    def __init__(self, approved: bool):
        self.approved = approved
        self.requests = []

    def request(self, req, timeout=0):
        self.requests.append(req)
        return approval.ApprovalResult(self.approved, "test", "ok" if self.approved else "no")


@pytest.fixture(autouse=True)
def _isolated():
    estop.reset_for_tests()
    approval.set_approver(None)
    audit.clear_for_tests()
    with flags.override(enabled=True, dry_run=False):
        yield
    estop.reset_for_tests()
    approval.set_approver(None)


# ── feature flag / dry run ──────────────────────────────────────────────────
class TestFlags:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv(flags.ENV_ENABLED, raising=False)
        with flags.override():
            assert flags.enabled() is False
            called = []
            result = make_runner().run_action("app.list", {}, lambda ctx: called.append(1))
            assert result.status == "disabled" and not called

    @pytest.mark.parametrize("value", ["1", "true", "ON", "yes"])
    def test_env_opt_in(self, monkeypatch, value):
        monkeypatch.setenv(flags.ENV_ENABLED, value)
        with flags.override():
            assert flags.enabled() is True

    def test_dry_run_plans_and_logs_but_never_executes(self):
        called = []
        with flags.override(enabled=True, dry_run=True):
            result = make_runner().run_action("file.write", {"path": "/tmp/x.txt"},
                                              lambda ctx: called.append(1))
        assert result.status == "dry_run" and result.ok and not called
        assert audit.recent()[-1]["status"] == "dry_run"

    def test_dry_run_still_needs_approval_for_high(self):
        called = []
        with flags.override(enabled=True, dry_run=True):
            result = make_runner().run_action("file.delete", {"path": "/tmp/x"},
                                              lambda ctx: called.append(1))
        assert result.status == "denied" and not called


# ── policy ───────────────────────────────────────────────────────────────────
class TestPolicy:
    policy = ActionPolicy(auth=lambda: OWNER)

    @pytest.mark.parametrize("action,level", [
        ("app.launch", Level.LOW), ("window.list", Level.LOW), ("browser.navigate", Level.LOW),
        ("file.write", Level.MEDIUM), ("file.move", Level.MEDIUM), ("element.click", Level.MEDIUM),
        ("file.delete", Level.HIGH), ("app.install", Level.HIGH), ("system.command", Level.HIGH),
        ("message.send", Level.HIGH), ("purchase", Level.HIGH), ("account.change", Level.HIGH),
        ("system.settings", Level.HIGH),
    ])
    def test_base_levels(self, action, level):
        assert self.policy.classify(action, {})[0] is level

    def test_unknown_action_escalates_to_high(self):
        level, why = self.policy.classify("frobnicate.everything", {})
        assert level is Level.HIGH and "unknown" in why[0]

    def test_plan_cannot_lower_a_level(self):
        assert self.policy.classify("file.delete", {"requested_level": "low"})[0] is Level.HIGH
        assert self.policy.classify("app.launch", {"requested_level": "high"})[0] is Level.HIGH

    def test_default_allow_folders(self, tmp_path):
        target = tmp_path / "Projects" / "notes.txt"
        assert protected_path_reason(target, write=True) == ""
        assert self.policy.classify("file.write", {"path": str(target)})[0] is Level.MEDIUM

    def test_jarvis_secrets_are_protected(self):
        secret = JARVIS_DIR / "config" / "api_keys.json"
        assert protected_path_reason(secret, write=False)
        assert self.policy.classify("file.read", {"path": str(secret)})[0] is Level.HIGH
        assert self.policy.classify("file.copy", {"src": str(secret), "dst": "/tmp/k"})[0] is Level.HIGH

    def test_quoted_or_variable_paths_are_judged_as_expanded(self, monkeypatch):
        # cc_file strips quotes and expands variables, so the policy checks that form too
        monkeypatch.setenv("CC_TEST_JARVIS", str(JARVIS_DIR))
        for raw in ("$CC_TEST_JARVIS/config/api_keys.json", f'"{JARVIS_DIR / "config" / "api_keys.json"}"'):
            assert protected_path_reason(raw, write=False), raw
            assert self.policy.classify("file.read", {"path": raw})[0] is Level.HIGH, raw
        assert protected_path_reason("$CC_TEST_UNSET_VAR/notes.txt", write=True) == ""

    def test_windows_system_dirs_are_protected(self, tmp_path, monkeypatch):
        fake_windows = tmp_path / "Windows"
        monkeypatch.setenv("SYSTEMROOT", str(fake_windows))
        target = fake_windows / "System32" / "drivers" / "etc" / "hosts"
        # (on Windows path_guard already names %SYSTEMROOT% as an OS location)
        assert protected_path_reason(target, write=True)
        assert self.policy.classify("file.write", {"path": str(target)})[0] is Level.HIGH

    @pytest.mark.windows_only
    @pytest.mark.skipif(os.name != "nt", reason="real Windows directories")
    def test_real_windows_system_dir(self):
        root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        assert self.policy.classify("file.write", {"path": root + r"\System32\x.dll"})[0] is Level.HIGH
        assert self.policy.classify("file.delete", {"path": root + r"\Temp\a"})[0] is Level.HIGH

    @pytest.mark.parametrize("label", ["Delete", "Send", "Pay now", "Place order", "Uninstall",
                                       "Sign out", "Empty Recycle Bin"])
    def test_destructive_controls_are_high(self, label):
        assert self.policy.classify("element.click", {"target": label})[0] is Level.HIGH

    def test_ordinary_controls_stay_medium(self):
        assert self.policy.classify("element.click", {"target": "Bold"})[0] is Level.MEDIUM

    def test_typing_into_a_shell_is_high(self):
        assert self.policy.classify("input.type", {"text": "dir", "window": "Windows PowerShell"})[0] is Level.HIGH
        assert self.policy.classify("input.type", {"text": "hi", "window": "Untitled - Notepad"})[0] is Level.MEDIUM

    @pytest.mark.parametrize("keys", ["win+r", "Win + X", ["ctrl", "shift", "esc"], "shift+delete"])
    def test_dangerous_hotkeys_are_high(self, keys):
        assert self.policy.classify("input.hotkey", {"keys": keys})[0] is Level.HIGH

    def test_ordinary_hotkey_is_medium(self):
        assert self.policy.classify("input.hotkey", {"keys": "ctrl+s"})[0] is Level.MEDIUM

    @pytest.mark.parametrize("url", ["file:///C:/Windows", "javascript:alert(1)", "data:text/html,x"])
    def test_non_web_urls_are_high(self, url):
        assert self.policy.classify("browser.navigate", {"url": url})[0] is Level.HIGH

    @pytest.mark.parametrize("name", [r"C:\Temp\evil.exe", "mshta", "rundll32.exe", "https://evil.test/x",
                                      "ms-settings:privacy", "run.bat", "script.ps1", "shortcut.lnk"])
    def test_launching_by_path_url_or_system_binary_is_high(self, name):
        assert self.policy.classify("app.launch", {"name": name})[0] is Level.HIGH

    def test_launch_arguments_are_at_least_medium(self):
        assert self.policy.classify("app.launch", {"name": "Notepad", "args": ["notes.txt"]})[0] is Level.MEDIUM

    def test_launching_a_shell_or_installer_is_high(self):
        assert self.policy.classify("app.launch", {"name": "powershell"})[0] is Level.HIGH
        assert self.policy.classify("app.launch", {"name": "setup.exe"})[0] is Level.HIGH
        assert self.policy.classify("app.launch", {"name": "notepad"})[0] is Level.LOW

    def test_tainted_arguments_raise_one_level(self):
        assert self.policy.classify("app.launch", {"name": "notepad"}, tainted=True)[0] is Level.MEDIUM
        assert self.policy.classify("file.write", {"path": "/tmp/a"}, tainted=True)[0] is Level.HIGH

    def test_privacy_lock_and_stranger_block_everything(self):
        for auth in (LOCKED, STRANGER):
            decision = ActionPolicy(auth=lambda a=auth: a).decide("window.list", {})
            assert not decision.allowed

    def test_auth_failure_fails_closed(self, monkeypatch):
        from jarvis.computer_control import policy as policy_mod
        from jarvis.core import security

        def broken():
            raise RuntimeError("no auth")
        monkeypatch.setattr(security, "get_auth_manager", broken)
        assert policy_mod._default_auth() == AuthSnapshot(privacy_locked=True, owner_allowed=False)
        assert not ActionPolicy().decide("app.list", {}).allowed

    def test_untrusted_origin_only_reads(self):
        assert self.policy.decide("browser.read", {}, origin=Origin.UNTRUSTED).allowed
        assert not self.policy.decide("file.write", {"path": "/tmp/a"}, origin="untrusted").allowed
        assert not self.policy.decide("element.click", {"target": "OK"}, origin="nonsense").allowed

    def test_high_needs_approval_even_with_full_access(self, monkeypatch):
        monkeypatch.setenv("JARVIS_FULL_ACCESS", "1")
        decision = self.policy.decide("file.delete", {"path": "/tmp/a"})
        assert decision.allowed and decision.needs_approval


# ── approval ─────────────────────────────────────────────────────────────────
class _FakeAuth:
    def __init__(self, *, locked=False, pin="1234", owner=True):
        self.locked, self.pin, self.owner = locked, pin, owner
        self.pin_checks = []

    def is_privacy_lock_active(self):
        return self.locked

    def is_pin_enrolled(self):
        return self.pin is not None

    def is_owner_access_allowed(self):
        return self.owner

    def verify_pin(self, pin):
        self.pin_checks.append(pin)
        return pin == self.pin


def _req(level=Level.HIGH):
    return approval.ApprovalRequest("file.delete", level, "Delete a file", "high risk")


class TestApproval:
    def test_no_approver_means_deny(self):
        called = []
        result = ActionRunner(ActionPolicy(auth=lambda: OWNER)).run_action(
            "file.delete", {"path": "/tmp/a"}, lambda ctx: called.append(1))
        assert result.status == "denied" and not called
        assert "approval" in result.message.lower()

    def test_approved_high_action_runs(self):
        ok = _Approver(True)
        result = make_runner(approver=ok).run_action("file.delete", {"path": "/tmp/a"},
                                                    lambda ctx: ActionOutcome(True, "deleted", verified=True))
        assert result.status == "ok" and len(ok.requests) == 1 and result.approval == "test"

    def test_each_high_action_is_asked_separately(self):
        ok = _Approver(True)
        run = make_runner(approver=ok)
        for _ in range(3):
            run.run_action("file.delete", {"path": "/tmp/a"}, lambda ctx: "x")
        assert len(ok.requests) == 3

    def test_low_and_medium_do_not_prompt(self):
        ask = _Approver(False)
        run = make_runner(approver=ask)
        assert run.run_action("window.list", {}, lambda ctx: "x").status == "ok"
        assert run.run_action("file.write", {"path": "/tmp/a"}, lambda ctx: "x").status == "ok"
        assert ask.requests == []

    def test_native_privacy_lock_denies_without_prompt(self):
        prompts = []
        approver = approval.NativeApprover(lambda r, t: prompts.append(r), auth_manager=_FakeAuth(locked=True))
        assert not approver.request(_req()).approved and prompts == []

    def test_native_pin_flow(self):
        auth = _FakeAuth()
        good = approval.NativeApprover(lambda r, t: approval.PromptAnswer(True, pin="1234"), auth_manager=auth)
        bad = approval.NativeApprover(lambda r, t: approval.PromptAnswer(True, pin="0000"), auth_manager=auth)
        missing = approval.NativeApprover(lambda r, t: approval.PromptAnswer(True), auth_manager=auth)
        assert good.request(_req()).approved
        assert not bad.request(_req()).approved
        assert not missing.request(_req()).approved
        assert auth.pin_checks == ["1234", "0000"]

    def test_native_decline_and_timeout(self):
        auth = _FakeAuth()
        declined = approval.NativeApprover(lambda r, t: approval.PromptAnswer(False), auth_manager=auth)
        timed_out = approval.NativeApprover(lambda r, t: None, auth_manager=auth)
        assert declined.request(_req()).method == "native_prompt"
        assert not declined.request(_req()).approved
        assert timed_out.request(_req()).method == "timeout"

    def test_native_without_pin_needs_verified_owner(self):
        prompts = []

        def prompt(r, t):
            prompts.append(r)
            return approval.PromptAnswer(True)
        assert not approval.NativeApprover(prompt, auth_manager=_FakeAuth(pin=None, owner=False)).request(_req()).approved
        assert prompts == []
        assert approval.NativeApprover(prompt, auth_manager=_FakeAuth(pin=None, owner=True)).request(_req()).approved

    def test_privacy_lock_during_the_prompt_denies(self):
        auth = _FakeAuth(pin=None, owner=True)

        def prompt(r, t):
            auth.locked = True          # the lock comes on while the dialog is open
            return approval.PromptAnswer(True)
        result = approval.NativeApprover(prompt, auth_manager=auth).request(_req())
        assert not result.approved and result.method == "privacy_lock"

    def test_prompt_crash_is_a_deny(self):
        def boom(r, t):
            raise RuntimeError("qt died")
        assert not approval.NativeApprover(boom, auth_manager=_FakeAuth()).request(_req()).approved

    def test_web_ui_cannot_reach_the_approver(self):
        """Owner decision 9: approval is native only; the web bridge must not reference it."""
        for path in (JARVIS_DIR / "webui").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "computer_control" not in text, path
        for path in (JARVIS_DIR.parent / "frontend" / "src").rglob("*.ts*"):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "bind_native_prompt" not in text and "computer_control.approval" not in text

    def test_approval_details_are_redacted(self):
        ok = _Approver(True)
        make_runner(approver=ok).run_action(
            "file.delete", {"path": "/tmp/a", "api_key": "AIzaSyD-very-secret-key-123456"}, lambda ctx: "x")
        assert ok.requests[0].details["api_key"] == "[redacted]"


# ── emergency stop ───────────────────────────────────────────────────────────
def _loop_until_stopped(ctx):
    while True:
        ctx.wait(0.5)


class TestEmergencyStop:
    def test_stop_interrupts_a_running_action_quickly(self):
        run = make_runner()
        holder = {}

        def go():
            holder["result"] = run.run_action("window.wait", {}, _loop_until_stopped, timeout=30)

        thread = threading.Thread(target=go)
        thread.start()
        time.sleep(0.15)
        t0 = time.perf_counter()
        estop.trigger("test")
        thread.join(5)
        latency = time.perf_counter() - t0
        assert holder["result"].status == "cancelled"
        assert latency < 0.5, latency

    def test_job_cancel_event_stops_only_that_action(self):
        cancel = threading.Event()
        threading.Timer(0.1, cancel.set).start()
        result = make_runner().run_action("window.wait", {}, _loop_until_stopped,
                                          cancel_event=cancel, timeout=10)
        assert result.status == "cancelled" and "cancelled" in result.message
        assert make_runner().run_action("window.list", {}, lambda ctx: "x").status == "ok"

    def test_new_actions_run_after_a_stop(self):
        estop.trigger("earlier")
        assert make_runner().run_action("window.list", {}, lambda ctx: "x").status == "ok"

    def test_held_stop_blocks_new_actions_until_released(self):
        estop.get().engage("hold")
        called = []
        assert make_runner().run_action("window.list", {}, lambda ctx: called.append(1)).status == "cancelled"
        estop.get().release()
        assert make_runner().run_action("window.list", {}, lambda ctx: "x").status == "ok"
        assert not called

    def test_stop_during_approval_cancels(self):
        class StopWhileAsking(_Approver):
            def request(self, req, timeout=0):
                estop.trigger("owner said stop")
                return super().request(req, timeout)
        called = []
        result = make_runner(approver=StopWhileAsking(True)).run_action(
            "file.delete", {"path": "/tmp/a"}, lambda ctx: called.append(1))
        assert result.status == "cancelled" and not called

    def test_stop_everything_triggers_the_estop(self):
        from jarvis.core.jobs import JobManager
        from jarvis.core.runtime.live_tools import ToolDispatchMixin

        class Live(ToolDispatchMixin):
            def __init__(self):
                self.manager = JobManager()

            def _job_manager(self):
                return self.manager
        before = estop.get().generation
        Live()._stop_everything()
        assert estop.get().generation == before + 1
        assert estop.get().last.source == "stop_everything"

    def test_interrupt_button_triggers_the_estop(self):
        from jarvis import main
        fake = SimpleNamespace(_loop=None, _interrupt_on_loop=lambda: None)
        before = estop.get().generation
        main.JarvisLive.interrupt(fake)
        assert estop.get().generation == before + 1

    def test_stop_word_path_reaches_stop_everything(self):
        source = (JARVIS_DIR / "main.py").read_text(encoding="utf-8")
        body = source.split("def _handle_stop_word", 1)[1].split("\n    def ", 1)[0]
        assert "_stop_everything()" in body

    def test_emergency_stop_tool_works_while_held(self):
        from jarvis.computer_control.tools import build_registry
        estop.get().engage("hold")
        result = build_registry().get("cc_emergency_stop").call({})
        assert result.status == "ok" and result.verified


# ── runner ───────────────────────────────────────────────────────────────────
class TestRunner:
    def test_timeout_abandons_a_hung_handler(self):
        t0 = time.perf_counter()
        result = make_runner().run_action("window.list", {}, lambda ctx: time.sleep(1.5), timeout=0.2)
        assert result.status == "timeout" and time.perf_counter() - t0 < 1.0

    def test_handler_timeout_error_is_an_error_not_a_hang(self):
        def raises_timeout(ctx):
            raise TimeoutError("socket timed out")
        t0 = time.perf_counter()
        result = make_runner().run_action("window.list", {}, raises_timeout, timeout=5)
        assert result.status == "error" and "socket timed out" in result.message
        assert time.perf_counter() - t0 < 1.0

    def test_error_text_is_redacted(self):
        key = "AIzaSyA1234567890abcdefghijklmnopqrs"

        def leaks(ctx):
            raise RuntimeError(f"bad request with key={key}")
        result = make_runner().run_action("window.list", {}, leaks)
        assert key not in result.message and key not in result.speakable()

    def test_errors_are_reported_not_raised(self):
        def boom(ctx):
            raise ValueError("no such window")
        result = make_runner().run_action("window.activate", {}, boom)
        assert result.status == "error" and "no such window" in result.message

    def test_verification(self):
        run = make_runner()
        good = run.run_action("file.write", {"path": "/tmp/a"}, lambda ctx: "written",
                              verify=lambda ctx, out: (True, "file exists"))
        bad = run.run_action("file.write", {"path": "/tmp/a"}, lambda ctx: "written",
                             verify=lambda ctx, out: (False, "file missing"))
        assert good.status == "ok" and good.verified is True
        assert bad.status == "unverified" and not bad.ok and "file missing" in bad.message

    def test_attempted_is_not_success(self):
        result = make_runner().run_action("element.click", {"target": "OK"},
                                          lambda ctx: ActionOutcome(ok=False, message="control disabled"))
        assert result.status == "failed" and not result.ok
        unchecked = make_runner().run_action("element.click", {"target": "OK"}, lambda ctx: "clicked")
        assert "not independently verified" in unchecked.speakable()

    def test_busy_instead_of_unbounded_queue(self, monkeypatch):
        monkeypatch.setattr(runner, "MAX_PENDING", 0)
        assert make_runner().run_action("window.list", {}, lambda ctx: "x").status == "busy"

    def test_nested_actions_run_inline(self):
        run = make_runner()

        def outer(ctx):
            inner = run.run_action("window.list", {}, lambda c: threading.current_thread().name)
            return ActionOutcome(True, inner.message)
        result = run.run_action("window.inspect", {}, outer)
        assert result.status == "ok" and result.message.startswith("cc-action")

    def test_listeners_see_start_and_end(self):
        events = []
        remove = runner.add_listener(events.append)
        try:
            make_runner().run_action("window.list", {}, lambda ctx: "x")
        finally:
            remove()
        assert [e["phase"] for e in events] == ["start", "end"]


# ── audit / redaction ────────────────────────────────────────────────────────
class TestAudit:
    def _log_lines(self):
        from jarvis.core import action_log
        return [json.loads(line) for line in action_log.log_path().read_text(encoding="utf-8").splitlines()]

    def test_every_action_is_logged_with_cc_prefix(self):
        make_runner().run_action("window.list", {}, lambda ctx: "3 windows")
        entry = self._log_lines()[-1]
        assert entry["tool"] == "cc.window.list" and entry["status"] == "ok" and entry["risk"] == "read"

    def test_denied_actions_are_logged_too(self):
        make_runner(auth=LOCKED).run_action("window.list", {}, lambda ctx: "x")
        assert self._log_lines()[-1]["status"] == "denied"

    def test_password_field_text_never_logged(self):
        secret = "hunter2-Sup3rSecret"
        make_runner().run_action("element.set_text", {"target": "Password", "is_password": True,
                                                      "text": secret}, lambda ctx: "typed")
        raw = Path(__import__("jarvis.core.action_log", fromlist=["x"]).log_path()).read_text(encoding="utf-8")
        assert secret not in raw and "[password-field]" in raw
        assert all(secret not in json.dumps(e) for e in audit.recent())

    def test_tokens_in_free_text_are_scrubbed(self):
        key = "AIzaSyA1234567890abcdefghijklmnopqrs"
        make_runner().run_action("input.type", {"text": f"my key is {key}"}, lambda ctx: "typed")
        assert key not in json.dumps(self._log_lines()[-1])

    def test_secret_keys_inside_json_strings_are_scrubbed(self):
        from jarvis.computer_control.redaction import redact_params, redact_text
        secret = "hunter2-Sup3rSecret"
        safe = redact_params({"op": "run", "params": '{"password": "%s", "user": "bob"}' % secret})
        assert secret not in json.dumps(safe) and '"user": "bob"' in safe["params"]
        assert secret not in redact_text('{"api_key":"%s"' % secret)      # malformed JSON too
        assert redact_text('plain "text": "kept"') == 'plain "text": "kept"'

    def test_mask_regions_paints_password_fields(self):
        from PIL import Image

        from jarvis.computer_control.redaction import mask_regions
        img = Image.new("RGB", (40, 20), (255, 255, 255))
        out = mask_regions(img, [(5, 5, 10, 5)])
        assert out.getpixel((7, 7)) == (0, 0, 0) and out.getpixel((1, 1)) == (255, 255, 255)
        assert img.getpixel((7, 7)) == (255, 255, 255)


# ── contract / registry ──────────────────────────────────────────────────────
class TestContract:
    def test_bad_specs_are_rejected(self):
        h = lambda ctx: None  # noqa: E731
        with pytest.raises(ContractError):
            ToolSpec(id="Bad-Id", action="app.list", description="x", handler=h).validate()
        with pytest.raises(ContractError):
            ToolSpec(id="cc_x", action="not.an.action", description="x", handler=h).validate()
        with pytest.raises(ContractError):
            ToolSpec(id="cc_x", action="app.list", description="x", handler=h,
                     input_schema={"type": "OBJECT", "properties": {"o": {"type": "OBJECT"}}}).validate()
        with pytest.raises(ContractError):
            ToolSpec(id="cc_x", action="app.list", description="x", handler=h,
                     input_schema={"type": "OBJECT", "properties": {}, "required": ["a"]}).validate()
        with pytest.raises(ContractError):
            ToolSpec(id="cc_x", action="app.list", description="x", handler=h, bypass_runner=True).validate()
        reg = SpecRegistry()
        reg.register(ToolSpec(id="cc_x", action="app.list", description="x", handler=h))
        with pytest.raises(ContractError):
            reg.register(ToolSpec(id="cc_x", action="app.list", description="y", handler=h))

    def test_declarations_load_through_the_existing_action_registry(self, tmp_path):
        from jarvis.core.action_loader import discover_actions
        (tmp_path / "cc_tools.py").write_text(
            "from jarvis.actions.computer_control_engine import TOOLS\n", encoding="utf-8")
        logs = []
        registry = discover_actions(tmp_path, logger=logs.append)
        assert {"cc_engine_status", "cc_emergency_stop"} <= registry.names(), logs
        assert registry.meta("cc_engine_status").risk == "read"
        with flags.override(enabled=False):
            # Only the read-only status tool, so the owner can ask why it is off.
            assert [d["name"] for d in registry.get_tool_declarations()
                    if d["name"].startswith("cc_")] == ["cc_engine_status"]
        with flags.override(enabled=True):
            names = {d["name"] for d in registry.get_tool_declarations()}
            assert "cc_engine_status" in names
            from jarvis.core.tool_catalog import build_catalog
            assert "cc_engine_status" in build_catalog(registries=[registry])

    def test_declaration_handler_returns_the_result_contract(self):
        from jarvis.computer_control.tools import build_registry
        decl = {d["name"]: d for d in build_registry().declarations()}["cc_engine_status"]
        payload = json.loads(decl["handler"](parameters={"device": "laptop"}))
        assert set(decl["cc_output_schema"]["required"]) <= set(payload)
        assert payload["action"] == "engine.status"

    def test_every_spec_declares_the_full_contract(self):
        from jarvis.computer_control.tools import build_registry
        for spec in build_registry().specs():
            spec.validate()
            decl = spec.to_declaration()
            for key in ("name", "description", "parameters", "handler", "risk", "timeout"):
                assert decl[key] not in (None, ""), (spec.id, key)
            assert spec.output_schema and spec.level in Level
