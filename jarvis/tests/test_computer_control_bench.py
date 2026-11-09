"""Project 8: the synthetic suite runs, every scenario reaches its expected outcome,
and every metric the master prompt asks for is reported."""
from __future__ import annotations

from jarvis.computer_control.bench import suite


def test_suite_passes_and_reports_metrics():
    report = suite.run_suite()
    failed = [(s.name, s.notes) for s in report.scenarios if not s.passed]
    assert not failed, failed
    for key in ("task_completion_rate", "verified_success_rate", "failure_rate", "recovery_rate",
                "avg_execution_s", "rss_peak_mb", "cpu_avg_percent", "cloud_requests", "tool_executions"):
        assert key in report.metrics, key
    assert report.metrics["task_completion_rate"] == 1.0
    assert report.metrics["cloud_requests"] == 0
    categories = {s.category for s in report.scenarios}
    assert {"app launch", "window management", "file management", "browser navigation", "multi-app workflow",
            "forms", "element detection", "recovery from unexpected dialogs", "cancellation", "verification",
            "security restrictions", "prompt injection"} <= categories
    assert "| metric | value |" in suite.to_markdown(report)
