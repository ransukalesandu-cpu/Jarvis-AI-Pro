"""Where the worker-node system meets the rest of JARVIS: MCP config, tools, tiers, UI, phone."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jarvis.core import hooks, mcp_client, security, ui_state
from jarvis.core.tool_catalog import PLANNER_EXCLUDED
from jarvis.webui import contract
from jarvis.webui.nodes_feed import NodesFeed


def _write(tmp_path, servers):
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps({"servers": servers}))
    return path


def test_worker_role_parsing(tmp_path):
    ok, bad = mcp_client.load_config(_write(tmp_path, {
        "forge": {"url": "https://forge.example/mcp", "bearer_env": "FORGE_TOKEN", "role": "worker"},
        "pc2": {"url": "https://pc2.example/mcp", "bearer_env": "PC2"},
        "noauth": {"url": "https://x.example/mcp", "role": "worker"},
        "weird": {"url": "https://x.example/mcp", "bearer_env": "X", "role": "admin"},
    }))
    assert ok["forge"].role == "worker" and ok["pc2"].role == ""
    assert set(bad) == {"noauth", "weird"}


def test_workers_are_never_generic_mcp_tools(tmp_path):
    path = _write(tmp_path, {"forge": {"url": "https://forge.example/mcp", "bearer_env": "T", "role": "worker"}})
    manager = mcp_client.McpManager(path)
    assert manager.status() == []
    with pytest.raises(mcp_client.McpError):
        manager.call("forge", "job_submit", {"request": "{}"})
    assert manager.index_text() == ""


def test_tiers_planner_and_hooks():
    assert security.tier_for("node_status", {}) == security.TIER_SAFE
    assert security.tier_for("node_test", {}) == security.TIER_SENSITIVE
    assert "node_test" in PLANNER_EXCLUDED
    for event in ("node_online", "node_offline", "node_job_finished"):
        assert event in hooks.EVENTS


def test_node_tools_without_configuration(monkeypatch, tmp_path):
    from jarvis.actions import node_jobs
    from jarvis.core.nodes import jobs as jobs_module
    from jarvis.core.nodes import registry as registry_module
    from jarvis.core.nodes.registry import NodeRegistry
    registry_module.reset_registry_for_tests(NodeRegistry(config_loader=lambda: {}, emit=lambda e, p: None))
    jobs_module.reset_remote_jobs_for_tests(jobs_module.RemoteJobs(registry_module.get_registry(), path=tmp_path / "s.json"))
    try:
        assert "No dedicated node is configured" in node_jobs.node_status({})
        assert node_jobs.node_test({"seconds": 5}).startswith("I didn't send the test: no dedicated node is configured")
        assert "0 to 600" in node_jobs.node_test({"seconds": 9999})
        names = {t["name"]: t for t in node_jobs.TOOLS}
        assert names["node_test"]["long_running"] and names["node_status"]["risk"] == "read"
        assert {h["event"] for h in node_jobs.HOOKS} == {"startup", "shutdown"}
    finally:
        registry_module.reset_registry_for_tests(None)
        jobs_module.reset_remote_jobs_for_tests(None)


ROW = {"name": "forge", "status": "online", "cpu": 10.0, "ramFreeMb": 4000.0, "running": 1.0, "queued": 0.0,
       "lastOkAt": 1_700_000_000_000}


def test_nodes_event_contract():
    assert json.loads(contract.encode_event("nodes.updated", nodes=[ROW]))["nodes"][0]["name"] == "forge"
    offline = {**ROW, "status": "offline", "cpu": None, "ramFreeMb": None, "running": None, "queued": None, "lastOkAt": None}
    assert contract.encode_event("nodes.updated", nodes=[offline]) is not None
    assert contract.encode_event("nodes.updated", nodes=[{**ROW, "url": "https://forge/mcp"}]) is None
    assert contract.encode_event("nodes.updated", nodes=[{**ROW, "status": "pwned"}]) is None
    assert contract.encode_event("nodes.updated", nodes=[{**ROW, "cpu": 300}]) is None
    assert contract.encode_event("nodes.updated", nodes=[ROW] * 9) is None


def test_nodes_feed_publishes_only_safe_fields():
    snapshot = [{"name": "forge", "status": "unconfigured", "node_id": "forge", "software": "1.0.0",
                 "capabilities": ["assistant.orchestrate"], "last_ok": None,
                 "error": "set the FORGE_TOKEN environment variable", "cpu_percent": None,
                 "ram_available_mb": None, "running_jobs": None, "queued_jobs": None}]
    listeners = []
    registry = SimpleNamespace(snapshot=lambda: snapshot, add_listener=lambda fn: listeners.append(fn) or (lambda: None))
    bus = ui_state.StateBus()
    NodesFeed(registry, bus)
    rows = bus.get(ui_state.NODES)
    assert rows == (("forge", "unconfigured", None, None, None, None, None),)
    assert "FORGE_TOKEN" not in repr(rows)


def test_dashboard_nodes_endpoint_is_owner_only_and_minimal():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from jarvis.dashboard.server import DashboardServer
    from jarvis.core.nodes import registry as registry_module
    from jarvis.core.nodes.registry import NodeRegistry
    reg = NodeRegistry(config_loader=lambda: {}, emit=lambda e, p: None)
    reg.snapshot = lambda: [{"name": "forge", "status": "online", "node_id": "forge", "software": "1.0.0",
                             "capabilities": [], "last_ok": 1.0, "error": "secret-ish detail",
                             "cpu_percent": 5.0, "ram_available_mb": 900.0, "running_jobs": 0, "queued_jobs": 0}]
    registry_module.reset_registry_for_tests(reg)
    try:
        dash = DashboardServer()
        client = TestClient(dash.app)
        assert client.get("/api/nodes").status_code == 401
        owner = SimpleNamespace(is_owner_access_allowed=lambda: True, is_silent=lambda: False,
                                is_privacy_lock_active=lambda: False)
        with patch.object(dash, "_token_valid", return_value=True), \
                patch("jarvis.dashboard.server._get_auth_manager_for_dashboard", return_value=owner):
            body = client.get("/api/nodes", headers={"Authorization": "Bearer x"}).json()
        assert body["nodes"][0]["status"] == "online"
        assert "error" not in body["nodes"][0] and "secret-ish" not in json.dumps(body)
        locked = SimpleNamespace(is_owner_access_allowed=lambda: True, is_silent=lambda: False,
                                 is_privacy_lock_active=lambda: True)
        with patch.object(dash, "_token_valid", return_value=True), \
                patch("jarvis.dashboard.server._get_auth_manager_for_dashboard", return_value=locked):
            assert client.get("/api/nodes", headers={"Authorization": "Bearer x"}).status_code == 423
        guest = SimpleNamespace(is_owner_access_allowed=lambda: False, is_silent=lambda: False,
                                is_privacy_lock_active=lambda: False)
        with patch.object(dash, "_token_valid", return_value=True), \
                patch("jarvis.dashboard.server._get_auth_manager_for_dashboard", return_value=guest):
            assert client.get("/api/nodes", headers={"Authorization": "Bearer x"}).status_code == 401
    finally:
        registry_module.reset_registry_for_tests(None)
