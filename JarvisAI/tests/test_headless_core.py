"""Tests for Headless Core execution and Dashboard Server AI File Ingestion."""
import unittest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
import main
from dashboard.server import DashboardServer


class HeadlessCoreAndIngestionTests(unittest.TestCase):
    def test_headless_ui_interface_adapter(self):
        ui = main.HeadlessJarvisUI()
        self.assertEqual(ui.state, "INITIALIZING")
        ui.set_state("LISTENING")
        self.assertEqual(ui.state, "LISTENING")

        # Test callback handles without raising exceptions
        ui.write_log("Headless test log")
        ui.set_audio_level(0.5)
        ui.react_avatar_text("Hello")
        ui.push_visemes([], 0.02, 0.0)
        ui.show_content("Title", "Body")

        approved = None
        def confirm_cb(val):
            nonlocal approved
            approved = val

        ui.show_confirm("test_action", "Prompt", confirm_cb)
        self.assertFalse(approved)
        self.assertFalse(ui.hud_video_is_active())
        self.assertEqual(ui.get_plugins(), [])
        self.assertEqual(ui.get_plugin_settings(), {})

    def test_headless_flag_uses_daemon_path(self):
        import JarvisAI.main as jmain
        with (
            patch.object(jmain.sys, "argv", ["main.py", "--headless"]),
            patch.object(jmain, "JarvisLive") as live_cls,
            patch.object(jmain.asyncio, "run") as run_async,
        ):
            jmain.main()
            live_cls.assert_called_once()
            run_async.assert_called_once()

    def test_dashboard_upload_endpoint_and_ai_ingestion(self):
        server = DashboardServer()
        client = TestClient(server.app)

        token = "test_auth_token"
        server._remember_token(token, "TESTKEY")

        with patch("dashboard.server._get_auth_manager_for_dashboard") as get_auth_manager:
            manager = MagicMock()
            manager.is_owner_access_allowed.return_value = True
            manager.is_silent.return_value = False
            manager.is_privacy_lock_active.return_value = False
            manager.needs_pin.return_value = False
            get_auth_manager.return_value = manager
            with tempfile.TemporaryDirectory() as tmpdir:
                server._uploads_dir = Path(tmpdir)

                # 1. Test unauthorized upload
                res_unauth = client.post("/api/upload", files={"file": ("sample_doc.txt", b"data", "text/plain")})
                self.assertEqual(res_unauth.status_code, 401)

                # 2. Test owner-authorized upload with mocked file_processor
                with patch("actions.file_processor.file_processor", return_value="Summary of sample_doc.txt"):
                    res = client.post(
                        "/api/upload",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"file": ("sample_doc.txt", b"Document content for AI ingestion test.", "text/plain")},
                    )
                    self.assertEqual(res.status_code, 200)
                    json_resp = res.json()
                    self.assertTrue(json_resp.get("ok"))
                    self.assertTrue(json_resp.get("ai_ingested"))
                    self.assertEqual(json_resp.get("summary"), "Summary of sample_doc.txt")

                # 3. Test private file listing requires owner access
                res_files = client.get("/api/files", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(res_files.status_code, 200)
                file_names = [f["name"] for f in res_files.json().get("files", [])]
                self.assertIn("sample_doc.txt", file_names)


if __name__ == "__main__":
    unittest.main()
