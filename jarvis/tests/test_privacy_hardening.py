"""Tests for the telemetry / secrets / OFFLINE hardening pass."""
from __future__ import annotations

import os
import re
import socket
import stat
import sys
from pathlib import Path

import pytest

from jarvis.core import gemini, local_env, privacy, secure_file

ROOT = Path(__file__).resolve().parents[2]


# ── telemetry opt-outs ───────────────────────────────────────────────────────

def test_telemetry_opt_outs_are_set_on_import():
    for key in ("DO_NOT_TRACK", "HF_HUB_DISABLE_TELEMETRY", "GRADIO_ANALYTICS_ENABLED", "ANONYMIZED_TELEMETRY"):
        assert key in os.environ


def test_owner_value_wins_over_default(monkeypatch):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "True")
    privacy.apply()
    assert os.environ["GRADIO_ANALYTICS_ENABLED"] == "True"


# ── OFFLINE kill switch ──────────────────────────────────────────────────────

@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setenv("OFFLINE", "1")
    monkeypatch.delenv("JARVIS_OFFLINE_LAN", raising=False)
    privacy.install_offline_guard()
    yield
    privacy.uninstall_offline_guard()


@pytest.mark.parametrize("host,allowed", [
    ("127.0.0.1", True), ("::1", True), ("localhost", True), (None, True),
    ("192.168.1.20", True), ("10.0.0.5", True), ("fe80::1%eth0", True), ("tablet.local", True),
    ("8.8.8.8", False), ("generativelanguage.googleapis.com", False), ("2001:4860:4860::8888", False),
])
def test_is_allowed_host(monkeypatch, host, allowed):
    monkeypatch.delenv("JARVIS_OFFLINE_LAN", raising=False)
    assert privacy.is_allowed_host(host) is allowed


def test_lan_can_be_blocked_too(monkeypatch):
    monkeypatch.setenv("JARVIS_OFFLINE_LAN", "0")
    assert privacy.is_allowed_host("192.168.1.20") is False
    assert privacy.is_allowed_host("127.0.0.1") is True


def test_offline_blocks_dns_and_connect(offline):
    with pytest.raises(privacy.OfflineBlocked):
        socket.getaddrinfo("example.com", 443)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            sock.connect(("1.1.1.1", 443))
    finally:
        sock.close()


def test_offline_still_allows_loopback(offline):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(server.getsockname())
    finally:
        client.close()
        server.close()


def test_offline_error_is_an_oserror_so_features_degrade(offline):
    import urllib.error
    import urllib.request
    with pytest.raises((urllib.error.URLError, OSError)):
        urllib.request.urlopen("https://example.com", timeout=2)


def test_guard_not_installed_without_flag(monkeypatch):
    privacy.uninstall_offline_guard()
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.delenv("JARVIS_OFFLINE", raising=False)
    privacy.apply()
    assert not privacy.guard_installed()


# ── secrets: env-first Gemini key ────────────────────────────────────────────

def test_gemini_key_prefers_environment(monkeypatch, tmp_path):
    cfg = tmp_path / "api_keys.json"
    cfg.write_text('{"gemini_api_key": "from-file"}', encoding="utf-8")
    monkeypatch.setattr(gemini, "_KEY_FILE", cfg)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert gemini.api_key(refresh=True) == "from-env"
    monkeypatch.delenv("GEMINI_API_KEY")
    assert gemini.api_key(refresh=True) == "from-file"
    monkeypatch.setenv("GOOGLE_API_KEY", "alias")
    assert gemini.api_key(refresh=True) == "alias"


def test_main_loader_accepts_env_key(monkeypatch, tmp_path):
    from jarvis import main as jmain
    monkeypatch.setattr(jmain, "API_CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setenv("GEMINI_API_KEY", "env-only")
    assert jmain._get_api_key() == "env-only"


# ── secrets: owner-only credential files ─────────────────────────────────────

@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_write_private_text_is_owner_only(tmp_path):
    old = os.umask(0)
    try:
        target = tmp_path / "config" / "api_keys.json"
        secure_file.write_private_text(target, '{"k": "v"}')
    finally:
        os.umask(old)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_text(encoding="utf-8") == '{"k": "v"}'
    assert not (target.parent / "api_keys.json.tmp").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_restrict_permissions_tightens_world_readable(tmp_path):
    f = tmp_path / "google_token.json"
    f.write_text("{}", encoding="utf-8")
    os.chmod(f, 0o644)
    assert secure_file.restrict_permissions(f) is True
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_provider_settings_writes_owner_only(monkeypatch, tmp_path):
    from jarvis.core import provider_settings as ps
    monkeypatch.setattr(ps, "_CONFIG", tmp_path / "api_keys.json")
    ps._write({"openai_api_key": "x"})
    assert stat.S_IMODE((tmp_path / "api_keys.json").stat().st_mode) == 0o600


# ── local .env loader ────────────────────────────────────────────────────────

def test_local_env_parse_and_precedence(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nexport JARVIS_T_A=one\nJARVIS_T_B=\"two words\"\nJARVIS_T_C=three # note\nJARVIS_T_D=\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_T_A", "real-env")
    for k in ("JARVIS_T_B", "JARVIS_T_C", "JARVIS_T_D"):
        monkeypatch.delenv(k, raising=False)
    applied = local_env.load([env])
    assert os.environ["JARVIS_T_A"] == "real-env"
    assert os.environ["JARVIS_T_B"] == "two words"
    assert os.environ["JARVIS_T_C"] == "three"
    assert "JARVIS_T_D" not in os.environ
    assert set(applied) == {"JARVIS_T_B", "JARVIS_T_C"}
    for k in applied:
        monkeypatch.delenv(k)


# ── repository hygiene ───────────────────────────────────────────────────────

def test_dashboard_never_fetches_crypto_js_from_cdn():
    src = (ROOT / "jarvis" / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert "cdnjs.cloudflare.com" not in src
    assert "urlretrieve" not in src
    assert (ROOT / "jarvis" / "dashboard" / "static" / "crypto-js.min.js").is_file()


def test_web_app_has_no_default_analytics():
    web = ROOT / "web" / "app"
    if not web.is_dir():
        pytest.skip("web/ not present")
    constant = (web / "constant.ts").read_text(encoding="utf-8")
    assert re.search(r'DEFAULT_GA_ID\s*=\s*""', constant)
    assert "G-89WN60ZK2E" not in constant
    assert "@vercel/analytics" not in (web / "page.tsx").read_text(encoding="utf-8")
    assert "SpeedInsights" not in (web / "layout.tsx").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in (web / "components" / "home.tsx").read_text(encoding="utf-8")


def test_gitignore_covers_credential_files():
    import subprocess
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    paths = [".env", ".env.local", "jarvis/.env", "jarvis/config/api_keys.json",
             "jarvis/config/google_token.json", "config/google_credentials.json", "certs/server.key"]
    out = subprocess.run(["git", "check-ignore", *paths], cwd=ROOT, capture_output=True, text=True)
    assert sorted(out.stdout.split()) == sorted(paths)
    keep = subprocess.run(["git", "check-ignore", ".env.example", "jarvis/.env.example"],
                          cwd=ROOT, capture_output=True, text=True)
    assert keep.stdout.strip() == ""


def test_network_md_documents_kill_switch():
    text = (ROOT / "NETWORK.md").read_text(encoding="utf-8")
    assert "OFFLINE=1" in text and "telemetry" in text.lower()


def test_offline_boot_imports_core_modules():
    """A fresh interpreter with OFFLINE=1 boots the key-loading modules with the guard active."""
    import subprocess
    code = (
        "import socket, jarvis\n"
        "from jarvis.core import privacy\n"
        "assert privacy.guard_installed()\n"
        "import jarvis.core.provider_settings, jarvis.core.provider_fallback\n"
        "import jarvis.core.smart_intent_router, jarvis.webui.provider_info\n"
        "try:\n"
        "    socket.getaddrinfo('example.com', 443)\n"
        "except privacy.OfflineBlocked:\n"
        "    print('blocked')\n"
    )
    env = {**os.environ, "OFFLINE": "1", "PYTHONPATH": str(ROOT)}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("blocked")
