"""The hashed lockfiles must keep satisfying requirements*.txt (scripts/check_lockfile.py)."""
from __future__ import annotations

from jarvis.scripts import check_lockfile as cl

HASH = "--hash=sha256:" + "a" * 64


def test_repository_lockfiles_satisfy_the_requirements():
    problems = cl.check()
    assert problems == [], "\n".join(problems) + f"\n\nRegenerate with:\n{cl.REGENERATE}"


def _repo(tmp_path, requirements: str, lock: str, dev: str = "", dev_lock: str | None = None):
    (tmp_path / "requirements.txt").write_text(requirements, encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text(dev, encoding="utf-8")
    (tmp_path / "requirements.lock").write_text(lock, encoding="utf-8")
    (tmp_path / "requirements-dev.lock").write_text(lock if dev_lock is None else dev_lock, encoding="utf-8")
    return tmp_path


def test_a_consistent_lock_passes(tmp_path):
    root = _repo(tmp_path,
                 "# comment\nFoo-Bar[extra]>=1,<2  # why\nwinonly; sys_platform == \"win32\"\n",
                 f"foo-bar==1.4 \\\n    {HASH}\n    # via -r requirements.txt\n"
                 f"winonly==3.0 ; sys_platform == 'win32' \\\n    {HASH} \\\n    {HASH}\n")
    assert cl.check(root) == []


def test_drift_is_reported(tmp_path):
    root = _repo(tmp_path, "foo>=2\nmissing>=1\n", f"foo==1.0 \\\n    {HASH}\n")
    problems = cl.check(root)
    assert any("foo==1.0 does not satisfy foo>=2" in p for p in problems)
    assert any("missing (from requirements.txt) is not in the lock" in p for p in problems)


def test_pins_without_hashes_or_ranges_are_reported(tmp_path):
    root = _repo(tmp_path, "foo>=1\nbar>=1\n", "foo==1.0\nbar>=1.0 \\\n    " + HASH + "\n")
    problems = cl.check(root)
    assert any("no sha256 hashes for 'foo==1.0'" in p for p in problems)
    assert any("bar is not pinned with ==" in p for p in problems)


def test_dev_requirements_are_checked_against_the_dev_lock(tmp_path):
    root = _repo(tmp_path, "foo>=1\n", f"foo==1.0 \\\n    {HASH}\n", dev="pytest>=8\n")
    assert any("requirements-dev.lock: pytest" in p for p in cl.check(root))


def test_missing_lockfile(tmp_path):
    (tmp_path / "requirements.txt").write_text("foo\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("", encoding="utf-8")
    assert "requirements.lock is missing" in cl.check(tmp_path)
