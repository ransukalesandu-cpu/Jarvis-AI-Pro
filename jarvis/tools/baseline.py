"""Before/after numbers for the production-architecture upgrade (docs/plans/PROD_ARCH_UPGRADE_PLAN.md §4).

    python -m jarvis.tools.baseline imports            # import time + RSS, each probe in a fresh interpreter
    python -m jarvis.tools.baseline eval               # memory-retrieval eval metrics (offline)
    python -m jarvis.tools.baseline latency [--days 7] # summary of JARVIS_LATENCY_TRACE=1 records
    python -m jarvis.tools.baseline all --save         # all of the above, saved under <user data>/baselines/

RAM of the *running* app is measured with ``jarvis/tools/profile_ram.py --pid <PID>`` (idle and during a
Live conversation); that needs the real app on the real machine, so it is not repeated here.

Reads only local files and process metadata. No network.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

MARK = "BASELINE_JSON "

# Each probe runs in its own interpreter so earlier imports cannot hide the cost of later ones.
# "engine_no_qt" makes PyQt6 unimportable: it must keep working for the engine split (plan §3.3).
_PROBE = r'''
import importlib.abc, json, sys, time
t0 = time.perf_counter()
mode = sys.argv[1]
class _BlockQt(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "PyQt6" or name.startswith("PyQt6."):
            raise ImportError("blocked by baseline probe: " + name)
        return None
row = {"probe": mode}
try:
    if mode == "engine_with_qt":
        import jarvis.main  # noqa: F401
    elif mode == "engine_no_qt":
        sys.meta_path.insert(0, _BlockQt())
        import jarvis.main as jm
        row["desktop_ui_loaded"] = jm.JarvisUI is not None
    elif mode in ("host_webui", "host_with_hud"):
        from PyQt6 import QtWidgets, QtWebEngineWidgets  # noqa: F401
        import jarvis.webui.host  # noqa: F401
        if mode == "host_with_hud":
            import jarvis.ui  # noqa: F401
    else:
        raise SystemExit("unknown probe " + mode)
    row["import_s"] = round(time.perf_counter() - t0, 3)
    import psutil
    row["rss_mb"] = round(psutil.Process().memory_info().rss / 2**20, 1)
    row["qt_loaded"] = "PyQt6.QtCore" in sys.modules
except Exception as exc:
    row["error"] = (type(exc).__name__ + ": " + str(exc))[:300]
print("''' + MARK + r'''" + json.dumps(row))
'''

PROBES = ("engine_with_qt", "engine_no_qt", "host_webui", "host_with_hud")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_probe(mode: str, *, timeout: float = 180.0) -> dict:
    """One probe in a fresh interpreter. Returns its JSON row (with 'error' on failure)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_repo_root()) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        proc = subprocess.run([sys.executable, "-c", _PROBE, mode], capture_output=True, text=True,
                              timeout=timeout, env=env, cwd=str(_repo_root()))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"probe": mode, "error": f"{type(exc).__name__}: {exc}"[:300]}
    return parse_probe_output(mode, proc.stdout, proc.stderr)


def parse_probe_output(mode: str, stdout: str, stderr: str = "") -> dict:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(MARK):
            try:
                return json.loads(line[len(MARK):])
            except ValueError:
                break
    tail = (stderr or stdout or "").strip().splitlines()[-1:] or ["no output"]
    return {"probe": mode, "error": tail[0][:300]}


def measure_imports(runs: int = 3, probes: tuple[str, ...] = PROBES) -> dict:
    """Median import time and RSS per probe over ``runs`` fresh interpreters."""
    out: dict = {}
    for mode in probes:
        rows = [run_probe(mode) for _ in range(max(1, runs))]
        good = [r for r in rows if "error" not in r]
        if not good:
            out[mode] = {"error": rows[-1].get("error", "failed")}
            continue
        out[mode] = {
            "runs": len(good),
            "import_s": round(statistics.median(r["import_s"] for r in good), 3),
            "rss_mb": round(statistics.median(r["rss_mb"] for r in good), 1),
            "qt_loaded": good[-1].get("qt_loaded"),
        }
        if "desktop_ui_loaded" in good[-1]:
            out[mode]["desktop_ui_loaded"] = good[-1]["desktop_ui_loaded"]
    return out


def measure_eval() -> dict:
    from jarvis.eval.run_eval import evaluate
    result = evaluate()
    keys = ("cases", "recall_at_5", "mrr", "wrong_recall_rate", "correct_abstention_rate", "average_latency_ms")
    return {k: (round(result[k], 4) if isinstance(result[k], float) else result[k]) for k in keys}


def load_latency_records(directory: Path, days: int = 7, *, today: datetime | None = None) -> list[dict]:
    """Records from latency-YYYY-MM-DD.jsonl files of the last ``days`` days; bad lines are skipped."""
    today = today or datetime.now()
    wanted = {(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(max(1, days))}
    records: list[dict] = []
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("latency-*.jsonl")):
        if path.stem.removeprefix("latency-") not in wanted:
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("e2e_ms"), (int, float)):
                records.append(row)
    return records


def summarize_latency(records: list[dict]) -> dict:
    from jarvis.core.latency_trace import percentile, summarize
    out = summarize([float(r["e2e_ms"]) for r in records])
    for key in ("server_ms", "local_ms", "audible_est_ms"):
        values = [float(r[key]) for r in records if isinstance(r.get(key), (int, float))]
        out[f"{key}_p50"] = round(percentile(values, 50), 1) if values else None
    return out


def measure_latency(days: int = 7, directory: Path | None = None) -> dict:
    from jarvis.core.latency_trace import default_log_dir
    directory = directory or default_log_dir()
    out = summarize_latency(load_latency_records(directory, days))
    if out["n"] == 0:
        out["hint"] = "No records yet: start JARVIS with JARVIS_LATENCY_TRACE=1 and say ten short phrases."
    return out


def save_report(report: dict) -> Path:
    from jarvis.core.user_data import user_data_dir
    directory = user_data_dir() / "baselines"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"baseline-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jarvis.tools.baseline", description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=("imports", "eval", "latency", "all"))
    parser.add_argument("--runs", type=int, default=3, help="fresh interpreters per import probe (default 3)")
    parser.add_argument("--days", type=int, default=7, help="days of latency records to include (default 7)")
    parser.add_argument("--save", action="store_true", help="also write the report under <user data>/baselines/")
    args = parser.parse_args(argv)

    import platform
    report: dict = {"created_at": datetime.now().isoformat(timespec="seconds"),
                    "platform": f"{platform.system()} {platform.release()}",
                    "python": platform.python_version()}
    started = time.perf_counter()
    if args.what in ("imports", "all"):
        report["imports"] = measure_imports(args.runs)
    if args.what in ("eval", "all"):
        report["eval"] = measure_eval()
    if args.what in ("latency", "all"):
        report["latency"] = measure_latency(args.days)
    report["took_s"] = round(time.perf_counter() - started, 1)
    print(json.dumps(report, indent=2))
    if args.save:
        print(f"saved: {save_report(report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
