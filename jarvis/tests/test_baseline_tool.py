"""Baseline tool (tools/baseline.py) used for before/after numbers of the production-architecture upgrade."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from jarvis.tools import baseline


def test_parse_probe_output_finds_the_marked_line():
    out = "noise\n[JARVIS] something\n" + baseline.MARK + json.dumps({"probe": "x", "rss_mb": 1.5}) + "\n"
    assert baseline.parse_probe_output("x", out) == {"probe": "x", "rss_mb": 1.5}


def test_parse_probe_output_reports_the_error_tail():
    row = baseline.parse_probe_output("x", "", "Traceback ...\nModuleNotFoundError: No module named 'q'")
    assert row == {"probe": "x", "error": "ModuleNotFoundError: No module named 'q'"}
    assert baseline.parse_probe_output("x", "", "")["error"] == "no output"


def test_engine_imports_without_qt():
    """The engine split (plan §3.3) relies on jarvis.main importing with PyQt6 unavailable."""
    row = baseline.run_probe("engine_no_qt")
    assert "error" not in row, row
    assert row["qt_loaded"] is False
    assert row["desktop_ui_loaded"] is False
    assert row["rss_mb"] > 0


def _write(path, rows):
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_latency_records_filtered_by_day_and_bad_lines_skipped(tmp_path):
    today = datetime(2026, 11, 24, 12, 0)
    _write(tmp_path / "latency-2026-11-24.jsonl", [
        json.dumps({"e2e_ms": 700, "server_ms": 550, "local_ms": 150, "audible_est_ms": 780}),
        "not json",
        json.dumps({"no": "e2e"}),
        json.dumps({"e2e_ms": 900, "server_ms": 700, "local_ms": 200, "audible_est_ms": 980}),
    ])
    _write(tmp_path / "latency-2026-11-01.jsonl", [json.dumps({"e2e_ms": 5000})])   # outside 7 days
    (tmp_path / "unrelated.jsonl").write_text(json.dumps({"e2e_ms": 1}) + "\n", encoding="utf-8")

    records = baseline.load_latency_records(tmp_path, 7, today=today)
    assert [r["e2e_ms"] for r in records] == [700, 900]
    summary = baseline.summarize_latency(records)
    assert summary["n"] == 2
    assert summary["p50_ms"] == 700.0
    assert summary["server_ms_p50"] == 550.0
    assert summary["local_ms_p50"] == 150.0


def test_latency_missing_directory_is_empty_with_a_hint(tmp_path):
    out = baseline.measure_latency(7, tmp_path / "missing")
    assert out["n"] == 0 and "JARVIS_LATENCY_TRACE=1" in out["hint"]


def test_cli_latency_prints_json(tmp_path, monkeypatch, capsys):
    from jarvis.core import latency_trace
    monkeypatch.setattr(latency_trace, "default_log_dir", lambda: tmp_path)
    assert baseline.main(["latency"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["latency"]["n"] == 0
    assert {"created_at", "platform", "python", "took_s"} <= set(report)


def test_cli_rejects_unknown_command():
    with pytest.raises(SystemExit):
        baseline.main(["bogus"])
