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
