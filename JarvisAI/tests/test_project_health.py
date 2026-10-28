"""Project-health guards: import hygiene, packaging, and dependency drift.

These tests do not exercise a feature; they protect the *shape* of the project
so a future refactor cannot silently reintroduce a class of bug that is very
hard to debug at runtime.

Background — the bug this file was born from
-------------------------------------------
Three action modules did ``from config import is_windows, ...``. ``config`` is a
generic name, and ``opencv-python`` ships ``cv2/config.py``, which it puts on
``sys.path`` while ``cv2`` imports. If anything imported ``cv2`` first (screen
OCR does), Python could resolve ``config`` to OpenCV's loader and the whole app
died with ``NameError: name 'LOADER_DIR' is not defined`` — a message that
points nowhere near the real cause.

The fix moved those helpers to ``core.host_env``. The tests below make sure the
ambiguous name is never used again, and that the legacy ``config`` import path
still works for anyone who wrote extensions against it.
"""

import importlib
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

def _poison_config_module():
    """Install a foreign module named `config`, like a wheel would."""
    previous = sys.modules.get("config")
    sys.modules["config"] = types.ModuleType("config")
    return previous


def _restore_config_module(previous):
    if previous is None:
        sys.modules.pop("config", None)
    else:
        sys.modules["config"] = previous


class TestHostEnvIsCollisionProof:
    def test_host_env_works_while_a_foreign_config_module_is_imported_first(self):
        """The exact failure mode: `config` is already someone else's module."""
        from core import host_env

        previous = _poison_config_module()
        try:
            importlib.reload(host_env)
            assert isinstance(host_env.is_windows(), bool)
            assert isinstance(host_env.get_config(), dict)
        finally:
            _restore_config_module(previous)
            importlib.reload(host_env)

    def test_no_first_party_module_imports_the_bare_config_package(self):
        """`from config import ...` is forbidden outside the legacy shim itself.

        OpenCV ships `cv2/config.py`, so the name is not ours to rely on. The
        scan is textual and intentionally strict: it also catches a newly added
        module that reintroduces the dependency.
        """
        offenders = []
        for path in (REPO_ROOT / "JarvisAI").rglob("*.py"):
            if path.parent.name == "config" or path.name == "__init__.py" and path.parent.name == "config":
                continue
            if "tests" in path.parts:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                stripped = line.strip()
                if stripped.startswith(("from config import", "from config.", "import config")):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {stripped}")
        assert not offenders, (
            "Import the OS/key helpers from core.host_env instead:\n"
            + "\n".join(offenders)
        )


class TestLegacyConfigPackage:
    def test_config_package_still_reexports_the_helpers(self):
        """Extensions written against `from config import is_windows` keep working."""
        import importlib.util

        previous = sys.modules.pop("config", None)
        try:
            spec = importlib.util.find_spec("config")
            origin = Path(spec.origin).resolve() if spec and spec.origin else None
            project_config = (REPO_ROOT / "JarvisAI" / "config" / "__init__.py")
            if origin != project_config:
                # A wheel's module already owns the `config` name in this
                # environment (OpenCV leaks its own directory onto sys.path when
                # its native module fails to load). Nothing to test here.
                pytest.skip(f"`config` resolves to {origin}, not the project package")

            legacy = importlib.import_module("config")
            from core import host_env

            assert legacy.get_os() == host_env.get_os()
            assert legacy.is_windows() == host_env.is_windows()
            assert legacy.get_config().keys() == host_env.get_config().keys()
        finally:
            sys.modules.pop("config", None)
            if previous is not None:
                sys.modules["config"] = previous


class TestPackaging:
    def test_requirements_files_do_not_drift(self):
        """setup.py installs JarvisAI/requirements.txt; packaging reads the root
        copy. Identical content means `pip install -r` and `pip install .` agree."""
        root = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        nested = (REPO_ROOT / "JarvisAI" / "requirements.txt").read_text(
            encoding="utf-8"
        )
        assert root == nested, (
            "requirements.txt and JarvisAI/requirements.txt differ — update both."
        )

    def test_developer_requirements_do_not_leak_into_runtime(self):
        runtime = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        for dev_only in ("pytest", "ruff", "pre-commit"):
            assert dev_only not in runtime, f"{dev_only} belongs in requirements-dev.txt"

    def test_pyproject_declares_the_supported_python_floor(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'requires-python = ">=3.11"' in pyproject
