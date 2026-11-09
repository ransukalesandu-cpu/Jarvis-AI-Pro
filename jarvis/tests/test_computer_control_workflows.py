"""Project 5: record → owner-approved save → validate → run → trust tracking."""
from __future__ import annotations

import json

import pytest

from jarvis.computer_control import approval, audit, estop, flags, runner
from jarvis.computer_control.orchestrator import jobs as cc_jobs
from jarvis.computer_control.orchestrator.host import HostAgent
from jarvis.computer_control.policy import ActionPolicy, AuthSnapshot, Level
from jarvis.computer_control.runner import ActionRunner
from jarvis.computer_control.tools import build_registry
from jarvis.computer_control.windows.controller import WindowsController, set_controller
from jarvis.computer_control.windows.fake import FakeDesktop
from jarvis.computer_control.workflows import tools as wf_tools
from jarvis.computer_control.workflows.library import (
    PASSWORD_PARAM, TRUST_AFTER, LocalStore, WorkflowError, draft_from_report,
)
from jarvis.computer_control.workflows.runner import run_workflow, validate

OWNER = AuthSnapshot(False, True)


class Approver:
    def __init__(self, ok=True):
        self.ok, self.asked = ok, []

    def request(self, req, timeout=0):
        self.asked.append(req)
        return approval.ApprovalResult(self.ok, "test", "")


@pytest.fixture
def env(tmp_path, monkeypatch):
    desk = FakeDesktop()
    set_controller(WindowsController(desk, launch_timeout=2.0, poll=0.01))
    runner.set_runner(ActionRunner(ActionPolicy(auth=lambda: OWNER)))
    store = LocalStore(tmp_path / "wf.json")
    wf_tools.set_store(store)
    synced = []
    from jarvis.computer_control.workflows import library
    monkeypatch.setattr(library, "cloud_sync", lambda wf: synced.append(wf.name) or True)
    from jarvis.computer_control.workflows import runner as wf_runner
    monkeypatch.setattr(wf_runner, "cloud_sync", lambda wf: synced.append(wf.name) or True)
    monkeypatch.setattr(wf_tools, "cloud_sync", lambda wf: synced.append(wf.name) or True)
    estop.reset_for_tests()
    approval.set_approver(None)
    audit.clear_for_tests()
    with flags.override(enabled=True, dry_run=False):
        yield desk, build_registry(), store, synced
    set_controller(None)
    runner.set_runner(None)
    wf_tools.set_store(None)


NOTE_STEPS = [
    {"tool": "cc_app", "args": {"op": "launch", "name": "Notepad"}, "description": "open Notepad"},
    {"tool": "cc_control", "args": {"op": "set_text", "window": "Notepad", "control_type": "Edit",
                                    "text": "daily note"}, "description": "write the note"},
]


def run_task(specs, steps, objective="write my daily note"):
    host = HostAgent(specs)
    return host.run(host.plan_from(objective, steps))


class TestRecord:
    def test_only_successful_tasks_become_workflows(self, env):
        _d, specs, _s, _sync = env
        report = run_task(specs, [{"tool": "cc_app", "args": {"op": "launch", "name": "Photoshop 2099"}}])
        with pytest.raises(WorkflowError):
            draft_from_report(report, "broken")
        good = run_task(specs, NOTE_STEPS)
        draft = draft_from_report(good, "daily note")
        assert [s["tool"] for s in draft.steps] == ["cc_app", "cc_control"]
        with pytest.raises(WorkflowError):
            draft_from_report(good, "bad/name<>")

    def test_taint_survives_saving_and_replay(self, env):
        _d, specs, store, _sync = env
        report = run_task(specs, [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Notepad"}},
            {"tool": "cc_window", "args": {"op": "activate", "window": "{{0.data.window.title}}"}},
        ])
        assert report.trace[-1].tainted
        draft = draft_from_report(report, "tainted note")
        assert draft.steps[1]["tainted"] is True
        store.put(draft, new_version=True)
        replay = run_workflow(store.get("tainted note"), specs, store)
        # LOW activate with tainted args is raised to MEDIUM on replay too
        assert replay.success and replay.trace[-1].level == "medium" and replay.trace[-1].tainted

    def test_passwords_become_parameters(self, env):
        _d, specs, _s, _sync = env
        report = run_task(specs, [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Contoso Login"}},
            {"tool": "cc_control", "args": {"op": "set_text", "window": "Contoso", "name": "Password",
                                            "text": "TopSecret-77"}},
        ], "sign in")
        draft = draft_from_report(report, "sign in")
        assert draft.params == ["password"] and draft.steps[1]["args"]["text"] == PASSWORD_PARAM
        assert "TopSecret-77" not in json.dumps(draft.as_dict())


class TestStoreAndRun:
    def test_versions_and_bounded_file(self, env, tmp_path):
        _d, specs, store, _sync = env
        report = run_task(specs, NOTE_STEPS)
        store.put(draft_from_report(report, "daily note"), new_version=True)
        second = store.put(draft_from_report(report, "daily note"), new_version=True)
        assert second.version == 2 and store.get("daily note").version == 2
        assert store.get("daily note", version=1).version == 1
        assert store.delete("daily note") and store.get("daily note") is None

    def test_trust_needs_consecutive_verified_runs(self, env):
        desk, specs, store, synced = env
        wf = store.put(draft_from_report(run_task(specs, NOTE_STEPS), "daily note"), new_version=True)
        assert not wf.trusted
        for i in range(TRUST_AFTER):
            report = run_workflow(store.get("daily note"), specs, store)
            assert report.success, report.summary
        wf = store.get("daily note")
        assert wf.trusted and wf.successes == TRUST_AFTER and synced
        # the layout changes: the edit box disappears -> failure resets trust
        desk._make_notepad_original = desk._make_notepad

        def broken(pid, args):
            desk._make_notepad_original(pid, args)
            w = list(desk._windows.values())[-1]
            w.elements = [e for e in w.elements if e.control_type != "Edit"]
        desk._make_notepad = broken
        report = run_workflow(store.get("daily note"), specs, store)
        wf = store.get("daily note")
        assert not report.success and wf.failures == 1 and not wf.trusted and wf.streak == 0

    def test_validation_catches_missing_params_and_tools(self, env):
        _d, specs, store, _sync = env
        report = run_task(specs, [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Contoso Login"}},
            {"tool": "cc_control", "args": {"op": "set_text", "window": "Contoso", "name": "Password",
                                            "text": "x"}},
        ], "sign in")
        wf = store.put(draft_from_report(report, "sign in"), new_version=True)
        assert "needs password" in validate(wf, specs)[0]
        assert validate(wf, specs, {"password": "pw"}) == []
        wf.steps[0]["tool"] = "cc_gone"
        assert any("no longer exists" in p for p in validate(wf, specs, {"password": "pw"}))
        with pytest.raises(WorkflowError):
            run_workflow(wf, specs, store)

    def test_run_fills_password_at_run_time_only(self, env):
        desk, specs, store, _sync = env
        report = run_task(specs, [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Contoso Login"}},
            {"tool": "cc_control", "args": {"op": "set_text", "window": "Contoso", "name": "Password",
                                            "text": "first"}},
        ], "sign in")
        store.put(draft_from_report(report, "sign in"), new_version=True)
        assert run_workflow(store.get("sign in"), specs, store, params={"password": "RunTime-PW"}).success
        assert "RunTime-PW" not in store.path().read_text(encoding="utf-8")


class TestTool:
    def spec(self):
        return build_registry().get("cc_workflow")

    def test_save_needs_owner_approval(self, env):
        _d, specs, store, _sync = env
        cc_jobs._last_report = run_task(specs, NOTE_STEPS)
        denied = self.spec().call({"op": "save_last", "name": "daily note"})
        assert denied.status == "denied" and denied.level is Level.HIGH and store.get("daily note") is None
        approver = Approver(True)
        approval.set_approver(approver)
        saved = self.spec().call({"op": "save_last", "name": "daily note"})
        assert saved.status == "ok" and saved.verified and store.get("daily note")

    def test_untrusted_run_needs_approval_trusted_does_not(self, env):
        _d, specs, store, _sync = env
        wf = store.put(draft_from_report(run_task(specs, NOTE_STEPS), "daily note"), new_version=True)
        assert self.spec().call({"op": "run", "name": "daily note"}).status == "denied"
        approver = Approver(True)
        approval.set_approver(approver)
        assert self.spec().call({"op": "run", "name": "daily note"}).status == "ok"
        assert len(approver.asked) == 1
        wf = store.get("daily note")
        wf.streak = TRUST_AFTER
        store.put(wf, new_version=False)
        approval.set_approver(None)
        out = self.spec().call({"op": "run", "name": "daily note"})
        assert out.status == "ok" and out.level is Level.MEDIUM

    def test_run_time_password_never_reaches_approval_or_audit(self, env):
        _d, specs, store, _sync = env
        store.put(draft_from_report(run_task(specs, NOTE_STEPS), "daily note"), new_version=True)
        approver = Approver(True)
        approval.set_approver(approver)
        secret = "RunTime-Secret-PW"
        self.spec().call({"op": "run", "name": "daily note", "params": '{"password": "%s"}' % secret})
        assert approver.asked and secret not in json.dumps(approver.asked[0].details)
        from jarvis.core import action_log
        assert secret not in action_log.log_path().read_text(encoding="utf-8")
        assert all(secret not in json.dumps(e) for e in audit.recent())

    def test_list_show_validate_delete(self, env):
        _d, specs, store, _sync = env
        store.put(draft_from_report(run_task(specs, NOTE_STEPS), "daily note"), new_version=True)
        assert "daily note" in self.spec().call({"op": "list"}).message
        assert self.spec().call({"op": "validate", "name": "daily note"}).verified
        assert self.spec().call({"op": "delete", "name": "daily note"}).status == "ok"
        assert self.spec().call({"op": "show", "name": "daily note"}).status == "failed"

    def test_workflows_cannot_be_planned(self, env):
        from jarvis.computer_control.orchestrator.plan import PlanError
        _d, specs, _s, _sync = env
        with pytest.raises(PlanError):
            HostAgent(specs).plan_from("x", [{"tool": "cc_workflow", "args": {"op": "run"}}])


CONTOSO_STEPS = [
    {"tool": "cc_app", "args": {"op": "launch", "name": "Contoso Login"}},
    {"tool": "cc_control", "args": {"op": "set_text", "window": "Contoso", "name": "Password", "text": "first"}},
]


class TestReviewFixes:
    """Review of #282: replay secrets, lossy drafts, store integrity, trust, keys, approval binding."""

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_filled_password_never_logged_even_if_target_lookup_fails(self, env, monkeypatch, dry_run):
        _d, specs, store, _sync = env
        store.put(draft_from_report(run_task(specs, CONTOSO_STEPS, "sign in"), "sign in"), new_version=True)

        import sys

        from jarvis.computer_control.windows import tools as win_tools
        real_controller = win_tools.get_controller

        class _Unreachable:
            def window(self, *a, **kw):
                raise RuntimeError("target lookup failed")

        def controller_for_caller():
            # only the policy-time lookup fails; the handler itself still works
            if sys._getframe(1).f_code.co_name == "_enrich_control":
                return _Unreachable()
            return real_controller()
        monkeypatch.setattr(win_tools, "get_controller", controller_for_caller)
        secret = "Replay-Secret-991"
        with flags.override(enabled=True, dry_run=dry_run):
            report = run_workflow(store.get("sign in"), specs, store, params={"password": secret})
        from jarvis.core import action_log
        assert secret not in action_log.log_path().read_text(encoding="utf-8")
        assert all(secret not in json.dumps(e) for e in audit.recent())
        assert secret not in json.dumps(report.as_dict())

    def test_lossy_arguments_are_not_saved(self, env):
        _d, specs, _store, _sync = env
        for text in ("x" * 400, "key AIzaSyA1234567890abcdefghijklmnopqrs"):
            steps = [NOTE_STEPS[0], {**NOTE_STEPS[1], "args": {**NOTE_STEPS[1]["args"], "text": text}}]
            report = run_task(specs, steps)
            assert report.success, report.summary
            with pytest.raises(WorkflowError, match="cannot be stored exactly"):
                draft_from_report(report, "lossy")

    def test_unverified_state_changing_steps_are_not_saved(self, env):
        _d, specs, _store, _sync = env
        report = run_task(specs, NOTE_STEPS)
        report.trace[-1].verified = None
        with pytest.raises(WorkflowError, match="not checked"):
            draft_from_report(report, "unchecked")

    def test_a_corrupt_store_is_kept_aside_and_a_read_error_overwrites_nothing(self, env, monkeypatch):
        _d, specs, store, _sync = env
        draft = draft_from_report(run_task(specs, NOTE_STEPS), "daily note")
        store.path().write_text("{not json", encoding="utf-8")
        store.put(draft, new_version=True)
        kept = list(store.path().parent.glob(f"{store.path().stem}.corrupt-*.json"))
        assert kept and kept[0].read_text(encoding="utf-8") == "{not json"
        before = store.path().read_text(encoding="utf-8")
        from pathlib import Path
        real_read = Path.read_text

        def flaky(self, *a, **kw):
            if self == store.path():
                raise PermissionError("sharing violation")
            return real_read(self, *a, **kw)
        monkeypatch.setattr(Path, "read_text", flaky)
        with pytest.raises(PermissionError):
            store.put(draft_from_report(run_task(specs, NOTE_STEPS), "other"), new_version=True)
        assert store.get("daily note") is None and store.all() == []      # reads stay non-raising
        monkeypatch.setattr(Path, "read_text", real_read)
        assert store.path().read_text(encoding="utf-8") == before

    def test_success_without_any_verified_step_earns_no_trust(self, env):
        _d, specs, store, _sync = env
        from types import SimpleNamespace

        from jarvis.computer_control.workflows.runner import record_result
        wf = store.put(draft_from_report(run_task(specs, NOTE_STEPS), "daily note"), new_version=True)
        wf.streak = TRUST_AFTER - 1
        unchecked = SimpleNamespace(status="completed", success=True, steps_verified=0, summary="ok")
        record_result(wf, unchecked, store, 0.1)
        assert store.get("daily note").streak == 0 and not store.get("daily note").trusted

    def test_distinct_names_get_distinct_keys(self):
        from jarvis.computer_control.workflows.library import Workflow

        def key(name):
            return Workflow(name=name, objective="", steps=[]).key
        assert len({key("daily note"), key("daily-note"), key("daily.note")}) == 3
        assert key("日報") != key("月報")
        assert key("Daily  Note") == key("daily note")
        # a name that spells out another name's key gets a different key too
        assert key("daily note") != key(key("daily note")) and key("daily-note") != key(key("daily-note"))

    def test_the_store_refuses_to_file_a_workflow_under_another_ones_key(self, env, monkeypatch):
        _d, specs, store, _sync = env
        from jarvis.computer_control.workflows.library import Workflow
        store.put(draft_from_report(run_task(specs, NOTE_STEPS), "daily note"), new_version=True)
        monkeypatch.setattr(Workflow, "key", property(lambda self: "forced-collision"))
        store.path().write_text(json.dumps({"forced-collision": [
            {**store.all()[0].as_dict(), "name": "daily note"}]}), encoding="utf-8")
        with pytest.raises(WorkflowError, match="clashes"):
            store.put(draft_from_report(run_task(specs, NOTE_STEPS), "other note"), new_version=True)
        assert store.get("daily note").name == "daily note"

    def test_run_is_refused_when_the_workflow_changed_after_the_check(self, env, monkeypatch):
        _d, specs, store, _sync = env
        wf = store.put(draft_from_report(run_task(specs, NOTE_STEPS), "daily note"), new_version=True)
        spec = build_registry().get("cc_workflow")
        real_get = store.get
        calls = {"n": 0}

        def stale_then_real(name, version=None):
            calls["n"] += 1
            got = real_get(name, version)
            if calls["n"] == 1 and got is not None:          # what _enrich sees: trusted
                got.streak = TRUST_AFTER
            return got
        monkeypatch.setattr(store, "get", stale_then_real)
        out = spec.call({"op": "run", "name": "daily note"})
        assert out.status == "failed" and "no longer trusted" in out.message
        # trusted, but a new version appeared after the check
        wf.streak = TRUST_AFTER
        store.put(wf, new_version=False)
        calls["n"] = 0

        def old_version_then_real(name, version=None):
            calls["n"] += 1
            got = real_get(name, version)
            if calls["n"] == 1 and got is not None:
                got.version = 0
            return got
        monkeypatch.setattr(store, "get", old_version_then_real)
        out = spec.call({"op": "run", "name": "daily note"})
        assert out.status == "failed" and "changed" in out.message
