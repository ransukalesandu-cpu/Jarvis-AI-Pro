"""Static guarantees for the hologram page: local-only, no dynamic code, packaged, JS tests pass."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "hologram"
JS_FILES = [p for p in ROOT.rglob("*.js") if "vendor" not in p.parts] + list(ROOT.rglob("*.mjs"))
PROJECT = Path(__file__).resolve().parents[2]


def test_page_has_a_strict_content_security_policy():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    m = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', html)
    assert m, "index.html must declare a CSP"
    csp = m.group(1)
    assert "default-src 'none'" in csp
    assert "script-src 'self'" in csp
    assert "unsafe-eval" not in csp
    assert "connect-src" not in csp or "connect-src 'none'" in csp
    assert "http:" not in csp and "https:" not in csp


def test_no_remote_urls_or_dynamic_code_in_first_party_js():
    for path in JS_FILES:
        text = path.read_text(encoding="utf-8")
        code = re.sub(r"//.*", "", text)
        assert not re.search(r"https?://", code), f"{path.name} references a remote URL"
        for banned in ("eval(", "new Function", "innerHTML", "document.write", "importScripts", "fetch(",
                       "XMLHttpRequest", "WebSocket", "localStorage", "sendBeacon", "window.open"):
            assert banned not in code, f"{path.name} uses {banned}"


def test_all_relative_imports_resolve():
    for path in JS_FILES:
        for rel in re.findall(r"from\s+'(\.[^']+)'", path.read_text(encoding="utf-8")):
            assert (path.parent / rel).resolve().exists(), f"{path.name}: missing {rel}"


def test_vendored_three_is_present_with_license():
    assert (ROOT / "vendor" / "three.module.min.js").stat().st_size > 100_000
    licenses = list((ROOT / "vendor").glob("*LICENSE*"))
    assert licenses, "vendored library needs its license file"


def test_hologram_files_are_in_the_package_data():
    text = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    for pattern in ("hologram/**/*.html", "hologram/**/*.js", "hologram/**/*.css"):
        assert pattern in text


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_javascript_logic_tests_pass():
    files = sorted(str(p) for p in (ROOT / "tests_js").glob("*.test.mjs"))
    assert files
    result = subprocess.run(["node", "--test", *files], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-1000:]
