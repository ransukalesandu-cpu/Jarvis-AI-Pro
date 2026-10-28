"""Tests for the Windows installer logic (``tools/windows_setup.py``).

The batch files are deliberately thin, so the behaviour that actually matters —
which interpreter is chosen, when a venv is rebuilt, whether a failure is ever
reported as success — is exercised here with a fake ``run`` callable. Nothing
in this file needs Windows, and nothing claims Windows was tested: the batch
files themselves are covered by static assertions only (see
``tests/test_launchers.py``).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import windows_setup as ws  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def completed(code: int = 0, stdout: str = "") -> types.SimpleNamespace:
    return types.SimpleNamespace(returncode=code, stdout=stdout, stderr="")


class FakeRun:
    """Records every command and answers with a queued rule.

    ``rules`` maps a predicate (the joined command) to a CompletedProcess-like
    object; the first matching rule wins and is not consumed, so repeated calls
    behave consistently. Unmatched commands succeed with empty output.
    """

    def __init__(self, rules=None):
        self.rules = list(rules or [])
        self.calls: list[list[str]] = []

    def __call__(self, args, *, cwd=None, timeout=None, capture=True):
        argv = [str(a) for a in args]
        self.calls.append(argv)
        joined = " ".join(argv)
        for needle, response in self.rules:
            if callable(needle):
                if needle(joined):
                    return response
            elif needle in joined:
                return response
        return completed(0, "")

    def ran(self, *needles: str) -> bool:
        return any(all(n in " ".join(call) for n in needles) for call in self.calls)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A stand-in project root with the files the installer insists on."""
    root = tmp_path / "Jarvis AI Pro"          # a space in the path on purpose
    root.mkdir()
    (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "setup.py").write_text("# installer\n", encoding="utf-8")
    (root / "requirements.txt").write_text("PyQt6\n", encoding="utf-8")
    (root / "requirements-voice-id.txt").write_text("torch\n", encoding="utf-8")
    (root / "config").mkdir()
    return root


def make_venv(root: Path) -> Path:
    """Create the pieces of a venv that ``venv_problem`` inspects."""
    python = ws.venv_python(root)          # Scripts/python.exe on Windows, bin/python elsewhere
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    return python


def healthy_run(version: str = "3.12") -> FakeRun:
    """A runner that reports a healthy .venv and satisfying imports."""
    return FakeRun([
        ("-m pip --version", completed(0, "pip 24.0")),
        ("-m pip check", completed(0, "No broken requirements found.")),
        ("print('%d.%d' % sys.version_info[:2])", completed(0, version)),
    ])


# ── interpreter parsing and selection ───────────────────────────────────────

PY_LAUNCHER_OUTPUT = """
Installed Pythons found by C:\\Windows\\py.exe Launcher for Windows
 -V:3.13 *        C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python313\\python.exe
 -V:3.12          C:\\Program Files\\Python312\\python.exe
 -V:3.9           C:\\Python39\\python.exe
"""


def test_parse_py_launcher_list_reads_versions_and_paths():
    rows = ws.parse_py_launcher_list(PY_LAUNCHER_OUTPUT)
    assert rows[0] == (r"C:\Users\me\AppData\Local\Programs\Python\Python313\python.exe", (3, 13))
    assert rows[1][1] == (3, 12)
    assert rows[2][1] == (3, 9)
    assert rows[1][0] == r"C:\Program Files\Python312\python.exe"   # space kept intact


def test_parse_py_launcher_list_ignores_junk():
    assert ws.parse_py_launcher_list("") == []
    assert ws.parse_py_launcher_list("no interpreters here") == []
    assert ws.parse_py_launcher_list(" -V:3.12 *\n") == []


def test_supported_range_matches_pyproject():
    assert ws.is_supported((3, 11))
    assert ws.is_supported((3, 12))
    assert ws.is_supported((3, 13))
    assert not ws.is_supported((3, 10))
    assert not ws.is_supported((3, 14))
    assert not ws.is_supported(None)


def test_select_interpreter_prefers_312_over_the_newest():
    candidates = [
        ws.Interpreter(["py", "-3.13"], (3, 13)),
        ws.Interpreter(["py", "-3.12"], (3, 12)),
        ws.Interpreter(["py", "-3.11"], (3, 11)),
    ]
    chosen = ws.select_interpreter(candidates)
    assert chosen is not None and chosen.version == (3, 12)


def test_select_interpreter_falls_back_to_oldest_supported_not_newest():
    candidates = [ws.Interpreter(["py", "-3.13"], (3, 13)), ws.Interpreter(["py", "-3.11"], (3, 11))]
    assert ws.select_interpreter(candidates).version == (3, 11)


def test_select_interpreter_uses_newer_only_when_nothing_supported_exists():
    chosen = ws.select_interpreter([ws.Interpreter(["py", "-3.14"], (3, 14)),
                                    ws.Interpreter(["py", "-3.9"], (3, 9))])
    assert chosen is not None and chosen.version == (3, 14)


def test_select_interpreter_returns_none_for_unsupported_only():
    assert ws.select_interpreter([ws.Interpreter(["py", "-3.9"], (3, 9))]) is None
    assert ws.select_interpreter([]) is None


def test_find_interpreters_drops_versions_that_do_not_answer(monkeypatch):
    """A path the launcher lists but that no longer runs must not be offered."""
    monkeypatch.setattr(ws, "_IS_WINDOWS", True)
    run = FakeRun([
        ("py -0p", completed(0, "-V:3.12 * C:\\Python312\\python.exe\n")),
        (lambda cmd: " -c " in cmd and "print('%d.%d'" in cmd, completed(1, "")),
    ])
    assert ws.find_interpreters(run) == []


def test_find_interpreters_confirms_a_listed_path_before_offering_it(monkeypatch):
    monkeypatch.setattr(ws, "_IS_WINDOWS", True)
    run = FakeRun([
        ("py -0p", completed(0, "-V:3.12 * C:\\Python312\\python.exe\n")),
        # Only the path the launcher listed answers; nothing else may match.
        (lambda cmd: cmd.startswith("C:\\Python312\\python.exe") and " -c " in cmd,
         completed(0, "3.12")),
    ])
    found = ws.find_interpreters(run)
    assert [item.command for item in found] == [[r"C:\Python312\python.exe"]]
    assert found[0].version == (3, 12)


def test_find_interpreters_survives_a_missing_py_launcher(monkeypatch):
    """A machine without the py launcher must still be usable via PATH."""
    monkeypatch.setattr(ws, "_IS_WINDOWS", True)

    class LauncherMissing(FakeRun):
        def __call__(self, args, **kwargs):
            if [str(a) for a in args][:2] == ["py", "-0p"]:
                raise OSError("no launcher")
            return super().__call__(args, **kwargs)

    run = LauncherMissing([("python -c", completed(0, "3.11"))])
    found = ws.find_interpreters(run)
    assert {item.version for item in found} == {(3, 11)}
    assert all(item.version for item in found)        # nothing unusable leaks through


def test_interpreter_from_path_reports_a_path_that_is_not_python(tmp_path):
    run = FakeRun([("print('%d.%d' % sys.version_info[:2])", completed(1, ""))])
    with pytest.raises(ws.SetupError):
        ws.interpreter_from_path(r"C:\nope\python.exe", run=run)


def test_interpreter_from_path_accepts_a_working_path():
    run = FakeRun([("print('%d.%d' % sys.version_info[:2])", completed(0, "3.12"))])
    assert ws.interpreter_from_path(r"C:\Python312\python.exe", run=run).version == (3, 12)


# ── virtual environment handling ────────────────────────────────────────────

def test_venv_problem_reports_missing(project):
    assert ws.venv_problem(project, run=healthy_run()) == "missing"


def test_venv_problem_accepts_a_healthy_venv(project):
    make_venv(project)
    assert ws.venv_problem(project, run=healthy_run()) is None


def test_venv_problem_rejects_an_old_venv(project):
    make_venv(project)
    problem = ws.venv_problem(project, run=healthy_run("3.10"))
    assert problem is not None and "3.10" in problem


def test_venv_problem_rejects_a_newer_venv(project):
    make_venv(project)
    problem = ws.venv_problem(project, run=healthy_run("3.14"))
    assert problem is not None and "3.14" in problem


def test_venv_problem_rejects_a_python_that_cannot_run(project):
    make_venv(project)
    run = FakeRun([("print('%d.%d' % sys.version_info[:2])", completed(1, "boom"))])
    assert ws.venv_problem(project, run=run) == "its interpreter does not run"


def test_venv_problem_rejects_a_venv_with_broken_pip(project):
    make_venv(project)
    run = FakeRun([
        ("-m pip --version", completed(1, "No module named pip")),
        ("print('%d.%d' % sys.version_info[:2])", completed(0, "3.12")),
    ])
    assert "pip" in (ws.venv_problem(project, run=run) or "")


def test_backup_venv_renames_instead_of_deleting(project):
    make_venv(project)
    marker = project / ".venv" / "user-installed-model.bin"
    marker.write_bytes(b"keep me")

    moved = ws.backup_venv(project, now="20260101-120000")

    assert moved is not None
    assert moved.name == ".venv.broken-20260101-120000"
    assert (moved / "user-installed-model.bin").read_bytes() == b"keep me"
    assert not (project / ".venv").exists()


def test_backup_venv_does_not_overwrite_an_earlier_backup(project):
    make_venv(project)
    first = ws.backup_venv(project, now="20260101-120000")
    make_venv(project)
    second = ws.backup_venv(project, now="20260101-120000")
    assert first is not None and second is not None
    assert first != second and second.name.endswith("-1")


def test_backup_venv_is_a_no_op_without_a_venv(project):
    assert ws.backup_venv(project) is None


def test_ensure_venv_reuses_a_healthy_environment(project):
    make_venv(project)
    run = healthy_run()
    python, notes = ws.ensure_venv(project, run=run)
    assert notes == ["Using the existing .venv."]
    assert not run.ran("-m venv")                       # nothing was rebuilt


def test_ensure_venv_refuses_to_recreate_when_not_allowed(project):
    make_venv(project)
    with pytest.raises(ws.SetupError):
        ws.ensure_venv(project, run=healthy_run("3.10"), allow_recreate=False)
    assert (project / ".venv").exists()          # untouched


def test_ensure_venv_builds_a_new_one_and_says_so(project):
    run = FakeRun([("print('%d.%d' % sys.version_info[:2])", completed(0, "3.12"))])

    def fake_create(base, interpreter, run=None):
        return make_venv(base)

    import tools.windows_setup as module
    original = module.create_venv
    module.create_venv = fake_create
    try:
        python, notes = ws.ensure_venv(project, run=run,
                                       interpreter=ws.Interpreter(["py", "-3.12"], (3, 12)))
    finally:
        module.create_venv = original

    assert python.exists()
    assert any("No .venv yet" in note for note in notes)
    assert any("3.12" in note for note in notes)


def test_ensure_venv_without_any_supported_python_explains_what_to_install(project):
    run = FakeRun([("print('%d.%d' % sys.version_info[:2])", completed(0, "3.9"))])
    with pytest.raises(ws.SetupError) as excinfo:
        ws.ensure_venv(project, run=run)
    message = str(excinfo.value)
    assert "3.11" in message and "3.12" in message and "python.org" in message


def test_create_venv_reports_failure_instead_of_pretending(project):
    run = FakeRun([("-m venv", completed(1, "Error: permission denied"))])
    with pytest.raises(ws.SetupError) as excinfo:
        ws.create_venv(project, ws.Interpreter(["py", "-3.12"], (3, 12)), run=run)
    assert "permission denied" in str(excinfo.value)


def test_create_venv_reports_a_venv_without_an_interpreter(project):
    with pytest.raises(ws.SetupError):
        ws.create_venv(project, ws.Interpreter(["py", "-3.12"], (3, 12)), run=FakeRun())


# ── dependency installation ─────────────────────────────────────────────────

def test_pip_install_retries_a_transient_network_error_once(project):
    calls = {"n": 0}

    def flaky(args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return completed(1, "WARNING: Retrying (Retry(total=0)): Connection broken")
        return completed(0, "Successfully installed")

    assert ws.pip_install(Path("python.exe"), ["install", "x"], cwd=project, run=flaky) is True
    assert calls["n"] == 2


def test_pip_install_does_not_retry_a_resolver_conflict(project):
    calls = {"n": 0}

    def conflict(args, **_kwargs):
        calls["n"] += 1
        return completed(1, "ERROR: ResolutionImpossible: conflicting dependencies")

    assert ws.pip_install(Path("python.exe"), ["install", "x"], cwd=project, run=conflict) is False
    assert calls["n"] == 1                                # no pointless second attempt


def test_pip_install_gives_up_after_the_attempt_limit(project):
    calls = {"n": 0}

    def always_network(args, **_kwargs):
        calls["n"] += 1
        return completed(1, "ReadTimeoutError: The read operation timed out")

    assert ws.pip_install(Path("python.exe"), ["install", "x"], cwd=project,
                          run=always_network, attempts=2) is False
    assert calls["n"] == 2                                # bounded, never infinite


def test_pip_install_passes_the_venv_python_explicitly(project):
    run = FakeRun()
    ws.pip_install(Path(r"C:\proj\.venv\Scripts\python.exe"), ["install", "-r", "requirements.txt"],
                   cwd=project, run=run)
    assert run.calls[0][0] == r"C:\proj\.venv\Scripts\python.exe"
    assert "-m" in run.calls[0] and "pip" in run.calls[0]


def test_install_dependencies_runs_the_existing_setup_script(project):
    run = FakeRun()
    ws.install_dependencies(Path("python.exe"), project, run=run)
    assert run.ran("setup.py")


def test_install_dependencies_failure_raises(project):
    run = FakeRun([("setup.py", completed(1, "ERROR: Could not build wheels for torch"))])
    with pytest.raises(ws.SetupError) as excinfo:
        ws.install_dependencies(Path("python.exe"), project, run=run)
    assert "failed" in str(excinfo.value).lower()


def test_install_dependencies_needs_the_setup_script(tmp_path):
    with pytest.raises(ws.SetupError):
        ws.install_dependencies(Path("python.exe"), tmp_path, run=FakeRun())


def test_optional_voice_id_install_is_opt_in_and_never_fatal(project):
    run = FakeRun([("-r", completed(1, "ERROR: network unreachable"))])
    assert ws.install_optional_voice_id(Path("python.exe"), project, run=run) is False
    assert run.ran("requirements-voice-id.txt")


def test_optional_voice_id_skips_when_the_manifest_is_absent(project):
    (project / "requirements-voice-id.txt").unlink()
    run = FakeRun()
    assert ws.install_optional_voice_id(Path("python.exe"), project, run=run) is False
    assert not run.ran("tools/windows_setup.py") and run.calls == []


# ── install() end to end with a fake runner ────────────────────────────────

def test_install_stops_when_pip_fails(project, monkeypatch):
    """A failed pip step must never look like success."""
    monkeypatch.setattr(ws, "ensure_venv", lambda *a, **k: (make_venv(project), ["Using the existing .venv."]))
    monkeypatch.setattr(ws, "_required_imports_ok", lambda *a, **k: False)
    monkeypatch.setattr(ws, "pip_install", lambda *a, **k: False)
    monkeypatch.setattr(ws, "verify", lambda *a, **k: pytest.fail("verify must not run after a pip failure"))

    with pytest.raises(ws.SetupError):
        ws.install(project, run=FakeRun())


def test_install_failure_becomes_exit_code_1_at_the_cli(project, monkeypatch):
    monkeypatch.setattr(ws, "project_dir", lambda: project)
    monkeypatch.setattr(ws, "ensure_venv",
                        lambda *a, **k: (_ for _ in ()).throw(ws.SetupError("pip failed")))
    assert ws.main(["install"]) == 1


def test_install_returns_zero_when_verification_passes(project, monkeypatch):
    python = make_venv(project)
    monkeypatch.setattr(ws, "ensure_venv", lambda *a, **k: (python, ["Using the existing .venv."]))
    monkeypatch.setattr(ws, "_required_imports_ok", lambda *a, **k: True)
    monkeypatch.setattr(ws, "verify", lambda *a, **k: [ws.Check("Interpreter", "pass", "3.12")])
    assert ws.install(project, run=FakeRun()) == 0


def test_install_skips_the_download_when_the_venv_already_works(project, monkeypatch):
    python = make_venv(project)
    monkeypatch.setattr(ws, "ensure_venv", lambda *a, **k: (python, ["Using the existing .venv."]))
    monkeypatch.setattr(ws, "_required_imports_ok", lambda *a, **k: True)
    monkeypatch.setattr(ws, "verify", lambda *a, **k: [])
    called = {"pip": 0, "deps": 0}
    monkeypatch.setattr(ws, "pip_install", lambda *a, **k: called.__setitem__("pip", called["pip"] + 1) or True)
    monkeypatch.setattr(ws, "install_dependencies", lambda *a, **k: called.__setitem__("deps", called["deps"] + 1))

    assert ws.install(project, run=FakeRun()) == 0
    assert called == {"pip": 0, "deps": 0}


def test_install_force_reinstalls_dependencies(project, monkeypatch):
    python = make_venv(project)
    monkeypatch.setattr(ws, "ensure_venv", lambda *a, **k: (python, ["Using the existing .venv."]))
    monkeypatch.setattr(ws, "_required_imports_ok", lambda *a, **k: True)
    monkeypatch.setattr(ws, "verify", lambda *a, **k: [])
    monkeypatch.setattr(ws, "pip_install", lambda *a, **k: True)
    called = {"deps": 0}
    monkeypatch.setattr(ws, "install_dependencies",
                        lambda *a, **k: called.__setitem__("deps", called["deps"] + 1))

    assert ws.install(project, run=FakeRun(), force=True) == 0
    assert called["deps"] == 1


def test_install_offers_voice_id_only_when_selected(project, monkeypatch):
    python = make_venv(project)
    monkeypatch.setattr(ws, "ensure_venv", lambda *a, **k: (python, ["Using the existing .venv."]))
    monkeypatch.setattr(ws, "_required_imports_ok", lambda *a, **k: True)
    monkeypatch.setattr(ws, "pip_install", lambda *a, **k: True)
    monkeypatch.setattr(ws, "install_dependencies", lambda *a, **k: None)
    monkeypatch.setattr(ws, "verify", lambda *a, **k: [])
    seen = []
    monkeypatch.setattr(ws, "install_optional_voice_id",
                        lambda *a, **k: seen.append("voice-id") or True)

    ws.install(project, run=FakeRun())
    assert seen == []
    ws.install(project, run=FakeRun(), with_voice_id=True)
    assert seen == ["voice-id"]


# ── verify() ────────────────────────────────────────────────────────────────

def test_verify_fails_clearly_without_a_venv(project):
    checks = ws.verify(project, run=healthy_run())
    by_name = {c.name: c for c in checks}
    assert by_name["Interpreter"].status == "fail"
    assert "Install / Repair" in by_name["Interpreter"].detail
    assert by_name["Dependencies"].status == "skip"        # honest, not "pass"
    assert by_name["Application imports"].status == "skip"
    assert by_name["Entry point"].status == "pass"


def test_verify_passes_a_healthy_install(project):
    make_venv(project)
    (project / "config" / "api_keys.json").write_text(json.dumps({"gemini_api_key": "k"}), encoding="utf-8")
    checks = ws.verify(project, run=healthy_run())
    by_name = {c.name: c for c in checks}
    assert by_name["Interpreter"].status == "pass"
    assert by_name["Dependencies"].status == "pass"
    assert by_name["Required packages"].status == "pass"
    assert by_name["Entry point"].status == "pass"
    assert by_name["Configuration"].status == "pass"
    assert not [c for c in checks if c.status == "fail"]


def test_verify_fails_when_a_required_import_is_missing(project):
    make_venv(project)
    run = healthy_run()
    run.rules.append(("import sounddevice", completed(1, "ModuleNotFoundError: No module named 'sounddevice'")))
    checks = ws.verify(project, run=run)
    required = next(c for c in checks if c.name == "Required packages")
    assert required.status == "fail"
    assert "sounddevice" in required.detail


def test_verify_fails_when_an_app_module_is_broken(project):
    make_venv(project)
    run = healthy_run()
    run.rules.append(("import ui.hud_main", completed(1, "ImportError: cannot import name 'x'")))
    checks = ws.verify(project, run=run)
    app = next(c for c in checks if c.name == "Application imports")
    assert app.status == "fail"
    assert "hologram HUD" in app.detail


def test_verify_fails_when_pip_check_reports_broken_requirements(project):
    make_venv(project)
    run = healthy_run()
    run.rules.insert(0, ("-m pip check", completed(1, "pyqt6 6.7.0 requires PyQt6-Qt6, which is not installed.")))
    dependencies = next(c for c in ws.verify(project, run=run) if c.name == "Dependencies")
    assert dependencies.status == "fail"


def test_verify_marks_pip_check_alone_as_insufficient(project):
    """pip check passing must not be the only signal (imports are checked too)."""
    make_venv(project)
    run = healthy_run()
    run.rules.append(("import numpy", completed(1, "ModuleNotFoundError")))
    checks = {c.name: c for c in ws.verify(project, run=run)}
    assert checks["Dependencies"].status == "pass"
    assert checks["Required packages"].status == "fail"


def test_verify_reports_missing_config_without_secrets(project):
    make_venv(project)
    checks = ws.verify(project, run=healthy_run())
    config = next(c for c in checks if c.name == "Configuration")
    assert config.status == "skip"
    assert "api_keys.json" in config.detail


def test_verify_never_prints_secret_values(project):
    make_venv(project)
    secret = "AIzaSySUPERSECRETVALUE123"
    (project / "config" / "api_keys.json").write_text(
        json.dumps({"gemini_api_key": secret, "supabase_key": "service-role-key-xyz"}), encoding="utf-8")
    output = ws.format_checks(ws.verify(project, run=healthy_run()))
    assert secret not in output
    assert "service-role-key-xyz" not in output


def test_verify_reports_unreadable_config_as_a_problem(project):
    make_venv(project)
    (project / "config" / "api_keys.json").write_text("{not json", encoding="utf-8")
    config = next(c for c in ws.verify(project, run=healthy_run()) if c.name == "Configuration")
    assert config.status == "skip"
    assert "JSON" in config.detail


def test_verify_reports_optional_features_without_failing(project):
    make_venv(project)
    run = healthy_run()
    for module in ("cv2", "pytesseract", "torch", "speechbrain", "openwakeword", "playwright"):
        run.rules.append((f"import {module}", completed(1, "ModuleNotFoundError")))
    checks = ws.verify(project, run=run)
    optional = next(c for c in checks if c.name == "Optional features")
    assert optional.status == "skip"                    # allowed, not a failure
    assert not [c for c in checks if c.status == "fail"]


def test_verify_lists_available_optional_features(project):
    make_venv(project)
    checks = ws.verify(project, run=healthy_run())
    optional = next(c for c in checks if c.name == "Optional features")
    assert optional.status == "pass"
    assert "playwright" in optional.detail


def test_verify_marks_ocr_unavailable_without_the_tesseract_engine(project, monkeypatch):
    make_venv(project)
    monkeypatch.setattr(ws.shutil, "which", lambda name: None)
    checks = ws.verify(project, run=healthy_run())
    optional = next(c for c in checks if c.name == "Optional features")
    assert "Tesseract engine" in optional.detail
    assert "OCR bridge" not in optional.detail.split("unavailable")[0]


def test_verify_skips_project_tests_unless_requested(project):
    make_venv(project)
    checks = ws.verify(project, run=healthy_run())
    assert next(c for c in checks if c.name == "Project tests").status == "skip"


def test_verify_runs_the_fast_tests_when_asked(project):
    make_venv(project)
    run = healthy_run()
    run.rules.append(("pytest -q tests/test_project_health.py", completed(1, "1 failed")))
    checks = ws.verify(project, run=run, run_tests=True)
    assert next(c for c in checks if c.name == "Project tests").status == "fail"


def test_verify_always_states_what_it_cannot_test(project):
    make_venv(project)
    checks = ws.verify(project, run=healthy_run())
    service = next(c for c in checks if c.name == "Gemini Live / Supabase")
    assert service.status == "skip"


def test_format_checks_prints_a_summary_line():
    text = ws.format_checks([ws.Check("A", "pass"), ws.Check("B", "fail", "nope"), ws.Check("C", "skip")])
    assert "[PASS] A" in text and "[FAIL] B — nope" in text
    assert "1 passed, 1 failed, 1 skipped" in text


def test_check_as_dict_is_json_serialisable():
    payload = json.dumps([ws.Check("A", "pass", "b").as_dict()])
    assert json.loads(payload) == [{"name": "A", "status": "pass", "detail": "b"}]


# ── launch() ───────────────────────────────────────────────────────────────

def test_launch_propagates_the_app_exit_code(project, monkeypatch):
    make_venv(project)
    monkeypatch.setattr(ws.subprocess, "run", lambda *a, **k: completed(3))
    assert ws.launch(project, run=healthy_run()) == 3


def test_launch_uses_the_venv_python_real_entry_point_and_cwd(project, monkeypatch):
    python = make_venv(project)
    seen = {}

    def fake_run(command, cwd=None, **kwargs):
        seen["command"] = command
        seen["cwd"] = cwd
        return completed(0)

    monkeypatch.setattr(ws.subprocess, "run", fake_run)
    assert ws.launch(project, run=healthy_run()) == 0
    assert seen["command"][0] == str(python)
    assert seen["command"][1] == str(project / "main.py")
    assert "--hologram-hud" in seen["command"]
    assert Path(seen["cwd"]) == project.resolve() or Path(seen["cwd"]) == project


def test_launch_refuses_to_start_without_a_venv(project):
    assert ws.launch(project, run=healthy_run()) == 2


def test_launch_refuses_to_start_when_main_py_is_missing(project):
    make_venv(project)
    (project / "main.py").unlink()
    assert ws.launch(project, run=healthy_run()) == 2


def test_launch_reports_a_python_that_cannot_be_started(project, monkeypatch):
    make_venv(project)

    def boom(*a, **k):
        raise OSError("The system cannot find the file specified")

    monkeypatch.setattr(ws.subprocess, "run", boom)
    assert ws.launch(project, run=healthy_run()) == 2


# ── CLI behaviour (exit codes the batch menu relies on) ─────────────────────

def test_status_exit_codes(project, monkeypatch):
    monkeypatch.setattr(ws, "project_dir", lambda: project)
    assert ws.main(["status"]) == 1                      # nothing installed
    make_venv(project)
    monkeypatch.setattr(ws, "venv_problem", lambda *a, **k: None)
    assert ws.main(["status"]) == 0


def test_verify_cli_returns_one_on_failure_and_zero_when_clean(project, monkeypatch):
    monkeypatch.setattr(ws, "project_dir", lambda: project)
    assert ws.main(["verify"]) == 1
    monkeypatch.setattr(ws, "verify", lambda *a, **k: [ws.Check("A", "pass")])
    assert ws.main(["verify"]) == 0


def test_verify_cli_json_output(project, monkeypatch, capsys):
    monkeypatch.setattr(ws, "project_dir", lambda: project)
    monkeypatch.setattr(ws, "verify", lambda *a, **k: [ws.Check("A", "skip", "b")])
    assert ws.main(["verify", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["name"] == "A"


def test_install_cli_reports_setup_errors_as_exit_code_1(project, monkeypatch):
    monkeypatch.setattr(ws, "project_dir", lambda: project)

    def explode(*a, **k):
        raise ws.SetupError("No supported Python (3.11–3.13) was found.")

    monkeypatch.setattr(ws, "install", explode)
    assert ws.main(["install"]) == 1


def test_install_cli_passes_an_explicit_interpreter(project, monkeypatch):
    monkeypatch.setattr(ws, "project_dir", lambda: project)
    monkeypatch.setattr(ws, "interpreter_from_path",
                        lambda path, run=None: ws.Interpreter([path], (3, 12)))
    captured = {}

    def fake_install(*a, **k):
        captured.update(k)
        return 0

    monkeypatch.setattr(ws, "install", fake_install)
    assert ws.main(["install", "--python", r"C:\Python312\python.exe", "--with-voice-id", "--force"]) == 0
    assert captured["interpreter"].command == [r"C:\Python312\python.exe"]
    assert captured["with_voice_id"] is True
    assert captured["force"] is True


def test_cli_requires_a_command():
    with pytest.raises(SystemExit):
        ws.main([])


def test_project_dir_points_at_the_folder_above_tools():
    assert ws.project_dir().name == "JarvisAI"
    assert (ws.project_dir() / "main.py").exists()


def test_paths_with_spaces_survive_quoting(project):
    """Every constructed command keeps a spaced path as one argument."""
    python = make_venv(project)
    run = FakeRun()
    ws.pip_install(python, ["install", "-r", str(project / "requirements.txt")],
                   cwd=project, run=run)
    assert len(str(project).split()) > 1             # sanity: the path really has a space
    argv = run.calls[0]
    assert " " in argv[0] and " " in argv[argv.index("-r") + 1]
    assert len(argv) == 7                            # the manifest stayed one argument
