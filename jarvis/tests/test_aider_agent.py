"""aider_agent: project resolution, git safety rails, safe flags, undo, cancel.

A fake ``aider`` script stands in for the real CLI, so these run in CI without
installing Aider or calling Claude.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from jarvis.actions import aider_agent as aa

pytestmark = [
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
    pytest.mark.skipif(os.name == "nt", reason="fake aider is a POSIX script"),
]

FAKE_AIDER = textwrap.dedent('''\
    #!{python}
    import os, subprocess, sys, time
    args = sys.argv[1:]
    open("args.txt", "w").write("\\n".join(args))
    msg = args[args.index("--message") + 1]
    if msg == "sleep":
        time.sleep(60)
    if msg == "nothing":
        print("I have no changes to make.")
        sys.exit(0)
    with open("app.py", "a") as f:
        f.write("# " + msg + "\\n")
    subprocess.run(["git", "add", "app.py"], check=True)
    subprocess.run(["git", "commit", "-qm", "aider: " + msg], check=True)
    print("Applied edit to app.py")
''')


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    fake = tmp_path / "bin" / "aider"
    fake.parent.mkdir()
    fake.write_text(FAKE_AIDER.format(python=sys.executable))
    fake.chmod(0o755)
    monkeypatch.setenv("JARVIS_AIDER_PATH", str(fake))
    monkeypatch.setattr(aa, "get_provider_api_key", lambda provider: "sk-test")
    monkeypatch.setattr(aa.path_guard, "protected_reason", lambda path, write=True: None)

    proj = tmp_path / "work" / "My Portfolio"
    proj.mkdir(parents=True)
    (proj / "app.py").write_text("print('hi')\n")
    _git(proj, "init", "-q", "-b", "main")
    _git(proj, "add", ".")
    _git(proj, "commit", "-qm", "init")
    monkeypatch.setenv("JARVIS_AIDER_ROOTS", str(tmp_path / "work"))
    return proj


def test_resolves_by_folder_name_and_path(env):
    assert aa.resolve_project("my-portfolio") == env.resolve()
    assert aa.resolve_project(str(env)) == env.resolve()
    assert aa.resolve_project("does not exist") is None


def test_registered_name_wins(env, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert "Registered" in aa.aider_projects({"action": "add_project", "name": "shop", "path": str(other)})
    assert aa.resolve_project("Shop") == other.resolve()


def test_code_runs_on_new_branch_never_main(env):
    out = aa.aider_agent({"task": "add a footer", "project": "my portfolio"})
    assert "1 commit(s)" in out and "jarvis/aider-" in out
    assert _git(env, "rev-parse", "--abbrev-ref", "HEAD").startswith("jarvis/aider-")
    assert _git(env, "log", "-1", "--format=%s", "main") == "init"


def test_safe_flags_and_env(env):
    aa.aider_agent({"task": "x", "project": str(env)})
    args = (env / "args.txt").read_text().splitlines()
    for flag in ("--yes-always", "--no-suggest-shell-commands", "--no-auto-test",
                 "--no-auto-lint", "--no-detect-urls", "--analytics-disable"):
        assert flag in args
    assert args[args.index("--model") + 1].startswith("anthropic/")
    e = aa.child_env("k")
    assert e["ANTHROPIC_API_KEY"] == "k"
    assert not any(k for k in e if "TOKEN" in k.upper() or k.upper().startswith("GEMINI"))


def test_files_outside_project_refused(env):
    out = aa.aider_agent({"task": "x", "project": str(env), "files": "../secret.txt"})
    assert "outside the project" in out


def test_protected_path_refused(env, monkeypatch):
    monkeypatch.setattr(aa.path_guard, "protected_reason", lambda path, write=True: "it is part of Jarvis")
    assert "can't let Aider edit" in aa.aider_agent({"task": "x", "project": str(env)})


def test_no_change_reports_aider_output(env):
    out = aa.aider_agent({"task": "nothing", "project": str(env)})
    assert "No files were changed" in out and "no changes to make" in out


def test_undo_only_reverts_own_commits(env):
    aa.aider_agent({"task": "add a footer", "project": str(env)})
    assert "Reverted" in aa.aider_projects({"action": "undo", "project": str(env)})
    assert "# add a footer" not in (env / "app.py").read_text()
    # HEAD is now the revert commit, which this tool did not make through Aider
    assert "won't revert" in aa.aider_projects({"action": "undo", "project": str(env)})


def test_changes_lists_aider_commits(env):
    aa.aider_agent({"task": "add a footer", "project": str(env)})
    assert "aider: add a footer" in aa.aider_projects({"action": "changes", "project": str(env)})


def test_cancel_kills_aider(env):
    ev = threading.Event()
    threading.Timer(0.5, ev.set).start()
    out = aa.aider_agent({"task": "sleep", "project": str(env)}, cancel_event=ev)
    assert out.startswith("Stopped Aider")


def test_missing_aider_explains_install(env, monkeypatch):
    monkeypatch.setenv("JARVIS_AIDER_PATH", str(Path(env) / "nope"))
    assert "aider-install" in aa.aider_agent({"task": "x", "project": str(env)})


def test_non_git_folder_gets_initialised(env, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app.py").write_text("x = 1\n")
    out = aa.aider_agent({"task": "y", "project": str(plain)})
    assert "Started a git repository" in out
    assert (plain / ".git").is_dir()


def test_tools_discoverable():
    names = {t["name"] for t in aa.TOOLS}
    assert names == {"aider_agent", "aider_projects"}
    assert aa.TOOL_CODE["long_running"] is True


def test_security_tiers():
    from jarvis.core import security
    assert security.tier_for("aider_agent", {"task": "x"}) == security.TIER_DANGEROUS
    assert security.tier_for("aider_projects", {"action": "status"}) == security.TIER_SAFE
    assert security.tier_for("aider_projects", {"action": "changes"}) == security.TIER_SAFE
    assert security.tier_for("aider_projects", {"action": "undo"}) == security.TIER_SENSITIVE
    assert security.tier_for("aider_projects", {"action": "add_project"}) == security.TIER_DANGEROUS
