"""Task Flow tracker (core/task_flow.py), its contract shape and the show_task_progress tool."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jarvis.agent.models import StepKind, StepState, Task, TaskState, TaskStep
from jarvis.core import task_flow
from jarvis.core.task_flow import GROUP_GAP_S, FlowTracker, pretty_tool
from jarvis.webui import contract


@pytest.fixture
def rig():
    t = [1_000.0]
    tr = FlowTracker(clock=lambda: t[0])
    seen: list[tuple[str, object]] = []
    tr.subscribe(lambda k, p: seen.append((k, p)))
    return tr, t, seen


def test_pretty_tool_names():
    assert pretty_tool("open_app") == "Open app"
    assert pretty_tool("cc.click_button") == "Cc click button"
    assert pretty_tool("") == "Tool"


def test_tool_calls_in_one_exchange_share_a_flow(rig):
    tr, t, seen = rig
    a = tr.tool_started("file_search")
    t[0] += 1
    b = tr.tool_started("send_message")          # still running -> same flow
    tr.tool_finished(a, "ok", "found 3 files")
    t[0] += 1
    tr.tool_finished(b, "ok", "sent")
    flows = tr.flows()
    assert len(flows) == 1
    f = flows[0]
    assert f["state"] == "done" and f["finishedAt"] is not None
    assert [s["status"] for s in f["steps"]] == ["done", "done"]
    assert f["steps"][0]["detail"] == "found 3 files"
    assert f["title"] == "File search"                  # generic: named after the first tool
    assert all(k == "flow" for k, _ in seen)


def test_a_pause_starts_a_new_flow(rig):
    tr, t, _ = rig
    tr.tool_finished(tr.tool_started("open_app"), "ok", "opened")
    t[0] += GROUP_GAP_S + 0.5
    tr.tool_finished(tr.tool_started("web_search"), "ok", "5 results")
    assert [f["title"] for f in tr.flows()] == ["Open app", "Web search"]


def test_owner_words_name_the_flow_before_or_after(rig):
    tr, t, _ = rig
    tr.note_command("find my CV and send it to my phone")
    tr.tool_finished(tr.tool_started("file_search"), "ok", "")
    assert tr.latest()["title"] == "find my CV and send it to my phone"
    t[0] += 30
    tok = tr.tool_started("open_app")
    t[0] += 2
    tr.note_command("open my work apps")                  # transcript arrives after the call started
    tr.tool_finished(tok, "ok", "")
    assert tr.latest()["title"] == "open my work apps"


def test_stale_words_do_not_name_a_later_flow(rig):
    tr, t, _ = rig
    tr.note_command("old request")
    t[0] += 60
    tr.tool_finished(tr.tool_started("open_app"), "ok", "")
    assert tr.latest()["title"] == "Open app"


def test_statuses_errors_and_jobs(rig):
    tr, _, _ = rig
    tr.tool_finished(tr.tool_started("run_command"), "error", "exit code 1")
    assert tr.latest()["state"] == "failed" and tr.latest()["steps"][0]["status"] == "error"
    tr2 = FlowTracker(clock=lambda: 5.0)
    tr2.tool_finished(tr2.tool_started("computer_control"), "job_started", "Started background job j1")
    assert tr2.latest()["steps"][0]["detail"] == "running in the background"
    tr3 = FlowTracker(clock=lambda: 5.0)
    tr3.tool_finished(tr3.tool_started("files"), "cancelled", "Cancelled.")
    assert tr3.latest()["state"] == "cancelled" and tr3.latest()["steps"][0]["status"] == "skipped"


def test_hidden_tool_and_unknown_token_are_ignored(rig):
    tr, _, seen = rig
    assert tr.tool_started("show_task_progress") is None
    tr.tool_finished(None, "ok")
    tr.tool_finished("nope", "ok")
    assert tr.flows() == [] and seen == []


def test_secrets_never_reach_a_flow(rig):
    tr, _, _ = rig
    tr.note_command("my api_key=hunter2hunter2 please")
    tr.tool_finished(tr.tool_started("email"), "ok", "token: sk-proj-abcdef1234567890ABCDEF")
    text = json.dumps(tr.latest())
    assert "hunter2" not in text and "sk-proj" not in text


def test_history_is_bounded(rig):
    tr, t, _ = rig
    for i in range(task_flow.MAX_FLOWS + 5):
        t[0] += GROUP_GAP_S + 1
        tr.tool_finished(tr.tool_started(f"tool_{i}"), "ok", "")
    assert len(tr.flows()) == task_flow.MAX_FLOWS


def _task():
    task = Task("Clean up the downloads folder")
    task.set_plan([TaskStep("List files", kind=StepKind.READ_FILE),
                   TaskStep("Move old files", kind=StepKind.NOTE)])
    return task


def test_agent_tasks_mirror_steps_and_stay_quiet_without_change(rig):
    tr, _, seen = rig
    task = _task()
    task.transition(TaskState.PLANNING)
    task.transition(TaskState.RUNNING)
    task.steps[0].mark_running()
    tr.agent_task(task)
    tr.agent_task(task)                                   # poll, nothing changed
    assert len(seen) == 1
    f = tr.latest()
    assert f["source"] == "agent" and f["state"] == "running"
    assert [s["status"] for s in f["steps"]] == ["running", "pending"]
    task.steps[0].mark(StepState.COMPLETED, output="12 files")
    task.steps[1].mark(StepState.BLOCKED, error="needs approval")
    task.transition(TaskState.FAILED)
    tr.agent_task(task)
    f = tr.latest()
    assert f["state"] == "failed" and [s["status"] for s in f["steps"]] == ["done", "error"]
    assert len(tr.flows()) == 1


def test_every_snapshot_passes_the_contract(rig):
    tr, t, seen = rig
    tr.note_command("x" * 500)
    tok = tr.tool_started("a" * 200)
    tr.tool_finished(tok, "ok", "y" * 900)
    task = _task()
    tr.agent_task(task)
    for kind, payload in seen:
        assert contract.encode_event("task.flow", flow=payload) is not None, payload


def test_contract_rejects_bad_flows_and_views():
    good = {"id": "f1", "title": "t", "source": "command", "state": "done", "startedAt": 1, "finishedAt": None, "steps": []}
    assert contract.encode_event("task.flow", flow=good)
    for bad in ({**good, "state": "exploded"}, {**good, "source": "page"}, {**good, "extra": 1},
                {**good, "steps": [{"id": "s1"}]}, {**good, "title": ""}):
        assert contract.encode_event("task.flow", flow=bad) is None
    assert contract.encode_event("ui.task_flow", view="page")
    assert contract.encode_event("ui.task_flow", view="explode") is None


def test_show_task_progress_tool_requests_a_view(monkeypatch):
    tr = FlowTracker(clock=lambda: 1.0)
    monkeypatch.setattr(task_flow, "_TRACKER", tr)
    views = []
    tr.subscribe(lambda k, p: views.append(p) if k == "view" else None)
    from jarvis.actions.show_task_progress import show_task_progress
    assert "window" in show_task_progress({})
    assert "page" in show_task_progress({"view": "page"})
    assert "hidden" in show_task_progress({"view": "hide"})
    show_task_progress({"view": "bogus"})
    assert views == ["window", "page", "hide", "window"]


def test_agent_service_mirrors_its_events(monkeypatch):
    tr = FlowTracker(clock=lambda: 1.0)
    monkeypatch.setattr(task_flow, "_TRACKER", tr)
    from jarvis.agent.integration import AgentService
    task = _task()
    fake = SimpleNamespace(runner=SimpleNamespace(active_task=task, _tasks={task.id: task}),
                           _mirror_flow=AgentService._mirror_flow)
    AgentService.mirror_active_flow(fake)
    assert tr.latest()["title"] == "Clean up the downloads folder"


# ── web feed (Qt) ────────────────────────────────────────────────────────
def test_task_feed_forwards_only_when_unlocked_and_names_flows():
    QtCore = pytest.importorskip("PyQt6.QtCore")
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    from jarvis.core import log_tap
    from jarvis.webui.task_feed import TaskFeed

    class Bridge:
        def __init__(self):
            self.sent = []

        def publish(self, kind, **fields):
            self.sent.append((kind, contract.encode_event(kind, **fields)))
            return True

    class Host(QtCore.QObject):
        ready = QtCore.pyqtSignal()

        def __init__(self):
            super().__init__()
            self.bridge = Bridge()

    host, avail = Host(), ["ok"]
    tr = FlowTracker(clock=lambda: 10.0)
    feed = TaskFeed(host, lambda: avail[0], tracker=tr)
    try:
        log_tap.publish("You: open my work apps")
        tr.tool_finished(tr.tool_started("open_app"), "ok", "opened")
        tr.request_view("window")
        app.processEvents()
        kinds = [k for k, _ in host.bridge.sent]
        assert kinds == ["task.flow", "task.flow", "ui.task_flow"]
        assert all(text is not None for _, text in host.bridge.sent)
        assert json.loads(host.bridge.sent[-2][1])["flow"]["title"] == "open my work apps"

        host.bridge.sent.clear()
        avail[0] = "locked"                                   # locked / PIN / guest: nothing leaves
        tr.tool_finished(tr.tool_started("files"), "ok", "x")
        host.ready.emit()
        app.processEvents()
        assert host.bridge.sent == []

        avail[0] = "ok"
        host.ready.emit()                                     # a reloaded page gets the recent flows again
        assert [k for k, _ in host.bridge.sent] == ["task.flow"]
    finally:
        feed.close()
