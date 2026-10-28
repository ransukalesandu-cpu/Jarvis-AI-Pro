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

import ast
import importlib
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _target_names(target):
    """Names bound by an assignment target, unpacking tuples and lists.

    `A, B = "a", "b"` defines two module-level names, and JARVIS uses that form
    for the risk tiers in core/security.py.
    """
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names = set()
        for element in target.elts:
            names |= _target_names(element)
        return names
    return set()

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


class TestInternalImportGraph:
    """Every `from <internal module> import <name>` must name something real.

    Ruff catches an unused import (F401) and an undefined name (F821), but it
    treats a module as a black box: if `foo.py` stops exporting `bar` while
    `baz.py` still does `from foo import bar`, nothing complains until `baz` is
    imported at runtime. Removing unused imports is exactly the kind of cleanup
    that creates that bug, and most of the UI modules have no test that imports
    them, so it would only surface when a user opens that window.

    This test walks the real import graph statically — no modules are imported,
    so it cannot be defeated by a missing GUI library or a camera.
    """

    @staticmethod
    def _module_index():
        """Map dotted module name -> source path for every first-party module."""
        index = {}
        for path in (REPO_ROOT / "JarvisAI").rglob("*.py"):
            parts = list(path.relative_to(REPO_ROOT / "JarvisAI").with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
                if not parts:
                    continue
            index[".".join(parts)] = path
        # The repository-root launcher module (main.py) as well.
        index.setdefault("jarvis_launcher", REPO_ROOT / "main.py")
        return index

    @staticmethod
    def _module_level_names(tree):
        """Names bound at module scope, descending into try/if/with blocks."""
        names = set()

        def walk(body):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        names.update(_target_names(target))
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        names.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name != "*":
                            names.add(alias.asname or alias.name)
                elif isinstance(node, (ast.Try, ast.If, ast.With)):
                    walk(node.body)
                    walk(getattr(node, "orelse", []) or [])
                    walk(getattr(node, "finalbody", []) or [])

        walk(tree.body)
        return names

    def test_internal_from_imports_resolve(self):
        index = self._module_index()
        problems = []
        for module_name, path in sorted(index.items()):
            if module_name == "jarvis_launcher":
                continue  # copies another module's globals by design
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as exc:  # pragma: no cover - compileall covers this
                problems.append(f"{path.name}: {exc}")
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level:
                    continue
                target = index.get(node.module or "")
                if target is None or target == path:
                    continue
                exported = self._module_level_names(
                    ast.parse(target.read_text(encoding="utf-8", errors="replace"))
                )
                # `from package import submodule` binds the submodule, which is
                # never mentioned in the package's __init__.py source.
                is_package = target.name == "__init__.py"
                for alias in node.names:
                    if alias.name == "*" or alias.name in exported:
                        continue
                    if is_package and f"{node.module}.{alias.name}" in index:
                        continue
                    problems.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                        f"`{node.module}` no longer defines `{alias.name}`"
                    )
        assert not problems, "Broken internal imports:\n" + "\n".join(problems)


class TestFailSoftDiscipline:
    """Silent handlers are how two panels broke without anyone noticing.

    `ruff S110/S112` enforces the mechanical half of this in CI. These tests keep
    the *recorder* itself honest: an approved handler must actually reach it, and
    the module must stay dependency-free enough to be imported from anywhere.
    """

    def test_failsoft_imports_only_the_standard_library(self):
        source = (REPO_ROOT / "JarvisAI" / "core" / "failsoft.py").read_text(
            encoding="utf-8"
        )
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= {"__future__", "collections", "dataclasses", "logging", "os", "sys", "threading", "time"}, imported

    def test_suppress_records_what_it_is_asked_to_swallow(self):
        from core import failsoft

        failsoft.reset()
        try:
            try:
                raise OSError("no camera")
            except OSError:
                failsoft.suppress("tests:probe_camera")
            rows = failsoft.summary()
        finally:
            failsoft.reset()

        assert rows and rows[0]["feature"] == "tests:probe_camera"
        assert rows[0]["exception_type"] == "OSError"

    _BROAD = {"Exception", "BaseException", "ExceptionGroup", "BaseExceptionGroup"}

    @classmethod
    def _is_broad(cls, handler) -> bool:
        """Mirror ruff S110/S112: only *broad* catches count as a silent handler.

        `except FileNotFoundError: pass` is a deliberate, specific decision and
        ruff leaves it alone; `except Exception: pass` is the pattern that hides
        bugs, and that is what this test refuses to accept.
        """
        if handler.type is None:
            return True  # bare `except:`

        def names(node):
            if isinstance(node, ast.Name):
                return {node.id}
            if isinstance(node, ast.Attribute):
                return {node.attr}
            if isinstance(node, ast.Tuple):
                found = set()
                for element in node.elts:
                    found |= names(element)
                return found
            return set()

        return bool(names(handler.type) & cls._BROAD)

    def test_no_module_uses_a_silent_broad_handler(self):
        """A local backstop for the lint rule, so the invariant is testable.

        Comment-only removal is not allowed to reintroduce `except Exception:
        pass`; the handler must route through core.failsoft.suppress().
        """
        offenders = []
        for path in sorted((REPO_ROOT / "JarvisAI").rglob("*.py")):
            if "tests" in path.parts or path.name == "failsoft.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:  # pragma: no cover - compileall covers this
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if not self._is_broad(node):
                    continue
                first = node.body[0] if node.body else None
                if isinstance(first, (ast.Pass, ast.Continue)):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{first.lineno}"
                    )
        assert not offenders, (
            "Use core.failsoft.suppress() instead of a silent broad handler:\n"
            + "\n".join(offenders)
        )
