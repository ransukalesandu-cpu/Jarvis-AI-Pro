import asyncio
import json


from jarvis.core import ui_state
from jarvis.core.jobs import JobManager
from jarvis.webui import contract
from jarvis.webui.command_gate import JobGate
from jarvis.webui.jobs_feed import JobsFeed


def _run(coro):
    return asyncio.run(coro)


def test_listener_fires_on_start_and_finish_and_snapshot_has_no_result():
    async def main():
        m = JobManager()
        seen = []
        m.add_listener(lambda: seen.append([(j["status"]) for j in m.snapshot()]))

        async def work(job):
            return "SECRET RESULT"
        job = m.start("render", work, description="private description")
        await job.task
        return m, seen

    m, seen = _run(main())
    assert seen[0] == ["running"] and seen[-1] == ["done"]
    snap = m.snapshot()[0]
    assert set(snap) == {"id", "name", "status", "started", "finished"}
    assert "SECRET" not in json.dumps(snap) and "private" not in json.dumps(snap)


def test_request_cancel_from_another_thread_stops_a_running_job():
    import threading

    async def main():
        m = JobManager()

        async def work(job):
            await asyncio.sleep(30)
        job = m.start("slow", work)
        await asyncio.sleep(0)
        t = threading.Thread(target=lambda: results.append(m.request_cancel(job.id)))
        results = []
        t.start()
        t.join()
        await asyncio.sleep(0.05)
        return m, job, results

    m, job, results = _run(main())
    assert results == [True] and job.status == "cancelled"
    assert m.request_cancel(job.id) is False and m.request_cancel("nope") is False


def test_feed_publishes_rows_to_the_bus():
    async def main():
        bus = ui_state.StateBus()
        m = JobManager()
        JobsFeed(m, bus)

        async def work(job):
            return "x"
        job = m.start("a", work)
        await job.task
        return bus.get(ui_state.JOBS)

    rows = _run(main())
    assert len(rows) == 1 and rows[0][1] == "a" and rows[0][2] == "done" and rows[0][4] is not None


def test_job_gate_only_cancels_jobs_python_lists_as_running():
    t, cancelled = [0.0], []
    g = JobGate(lambda: ["job1", "job2"], lambda i: cancelled.append(i) or True, clock=lambda: t[0])
    assert g.cancel("job1") == "done" and g.cancel("job2") == "rate_limited"
    t[0] += 1
    assert g.cancel("job9") == "noop" and g.cancel("") == "unavailable" and g.cancel(5) == "unavailable" and g.cancel("x" * 30) == "unavailable"
    assert cancelled == ["job1"]


def test_contract_for_jobs():
    ok = {"id": "job1", "name": "render", "status": "running", "startedAt": 1700000000000, "finishedAt": None}
    assert contract.encode_event("jobs.updated", jobs=[ok])
    # Autonomous tasks add "waiting" and "paused" (agent/jobs_source.py); unknown states stay out.
    assert contract.encode_event("jobs.updated", jobs=[{**ok, "status": "paused"}, {**ok, "status": "waiting"}])
    for bad in ({**ok, "status": "stuck"}, {**ok, "result": "x"}, {**ok, "name": ""}, {**ok, "id": "x" * 25}, {**ok, "startedAt": -1}):
        assert contract.encode_event("jobs.updated", jobs=[bad]) is None
    assert contract.encode_event("jobs.updated", jobs=[ok] * 21) is None
    assert contract.parse_request(json.dumps({"kind": "job.cancel", "id": "job1"})) is not None
    for bad in ("", "x" * 25, 3, None):
        assert contract.parse_request(json.dumps({"kind": "job.cancel", "id": bad})) is None
