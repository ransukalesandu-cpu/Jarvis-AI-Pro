"""Module 4: on-request vision, isolated camera capture, background jobs, media."""
from __future__ import annotations

import asyncio
import io
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

JARVIS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for p in (JARVIS_DIR, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from jarvis.core import camera_snapshot, jobs, media_generation  # noqa: E402
from jarvis.core.capture import Frame  # noqa: E402


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(buf, format="JPEG")
    return buf.getvalue()


class SeeToolsTests(unittest.TestCase):
    def tearDown(self):
        from jarvis.core import security
        security.mark_user_turn_started()

    def test_see_screen_sends_one_frame(self):
        from jarvis.actions import vision_tools
        shown = []
        frame = Frame(jpeg=_jpeg(), width=64, height=48)
        with patch.object(vision_tools, "grab_screen", return_value=frame) as grab:
            out = vision_tools.see_screen({"question": "what is on my screen?", "window": "Notepad"},
                                          show_image=lambda *a: shown.append(a))
        grab.assert_called_once_with("Notepad", monitor=1)
        self.assertEqual(shown[0][1:], ("image/jpeg", "what is on my screen?", "screen"))
        self.assertIn("Captured one screen frame", out)

    def test_see_camera_sends_one_frame(self):
        from jarvis.actions import vision_tools
        shown = []
        with patch.object(vision_tools, "capture_frame", return_value=_jpeg()):
            vision_tools.see_camera({}, show_image=lambda *a: shown.append(a))
        self.assertEqual(shown[0][2:], ("What do you see?", "camera"))


class CameraIsolationTests(unittest.TestCase):
    def test_child_process_result_is_returned(self):
        fake = subprocess.CompletedProcess([], 0, stdout=_jpeg(), stderr=b"")
        with patch.object(camera_snapshot.subprocess, "run", return_value=fake) as run:
            data = camera_snapshot.capture_frame(index=0)
        self.assertTrue(data.startswith(b"\xff\xd8"))
        self.assertIn("jarvis.core.camera_snapshot", run.call_args.args[0])

    def test_child_failure_reason_is_reported(self):
        fake = subprocess.CompletedProcess([], 2, stdout=b"", stderr=b"camera 0 could not be opened\n")
        with patch.object(camera_snapshot.subprocess, "run", return_value=fake):
            with self.assertRaisesRegex(RuntimeError, "could not be opened"):
                camera_snapshot.capture_frame(index=0)

    def test_main_process_never_imports_opencv(self):
        sys.modules.pop("cv2", None)
        try:
            camera_snapshot.capture_frame(index=0, timeout=60)
        except RuntimeError:
            pass        # no webcam in CI; the point is where cv2 was loaded
        self.assertNotIn("cv2", sys.modules)


class VisionIntoLiveSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        from jarvis.core import security
        security.mark_user_turn_started()

    async def test_frame_follows_the_tool_result_into_the_session(self):
        import live_replay
        host = live_replay.build_host()
        sent = []

        async def send_client_content(**kwargs):
            sent.append(kwargs)
        host.session = SimpleNamespace(send_client_content=send_client_content)
        host._vision_cam_active = False
        frame = Frame(jpeg=_jpeg(), width=64, height=48)
        with patch("jarvis.actions.vision_tools.grab_screen", return_value=frame), \
             patch("jarvis.core.security.guard", side_effect=lambda _n, _a, run: run()), \
             patch("jarvis.core.action_log.log_path", return_value=Path(tempfile.mkdtemp()) / "a.jsonl"):
            resp = await host._execute_tool(SimpleNamespace(id="1", name="see_screen",
                                                            args={"question": "what is this?"}))
            self.assertIn("Captured", resp.response["result"])
            self.assertTrue(await host._flush_pending_vision())
        parts = sent[0]["turns"]["parts"]
        self.assertEqual(parts[0]["inline_data"]["mime_type"], "image/jpeg")
        self.assertIn("SCREEN CAPTURE", parts[1]["text"])
        self.assertIn("what is this?", parts[1]["text"])


class JobAndMediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        jobs.reset_job_manager_for_tests(None)
        media_generation.reset_for_tests()
        self.out = Path(tempfile.mkdtemp())

    async def test_generate_media_runs_in_background_and_announces(self):
        import live_replay
        host = live_replay.build_host()
        host.__dict__.pop("_announcements", None)
        with patch("jarvis.core.media_generation.default_output_dir", return_value=self.out), \
             patch("jarvis.core.pc_control.open_target"), \
             patch("jarvis.core.security.guard", side_effect=lambda _n, _a, run: run()), \
             patch("jarvis.core.action_log.log_path", return_value=self.out / "a.jsonl"):
            started = time.monotonic()
            resp = await host._execute_tool(SimpleNamespace(
                id="1", name="generate_media",
                args={"kind": "ad", "prompt": "coffee mug", "headline": "Morning Hero",
                      "tagline": "The mug that gets you going"}))
            self.assertLess(time.monotonic() - started, 1.0)      # did not block
            self.assertIn("Started background job", resp.response["result"])
            for _ in range(100):
                if host.__dict__.get("_announcements"):
                    break
                await asyncio.sleep(0.05)
        self.assertIn("Made ad with poster", host._announcements[0])
        self.assertEqual(len(list(self.out.glob("ad-*.jpg"))), 1)

    async def test_start_job_and_job_status(self):
        import live_replay
        from jarvis.actions.jobs_tools import job_status
        host = live_replay.build_host()
        host._loop = asyncio.get_running_loop()
        with patch("jarvis.core.security.guard", side_effect=lambda _n, _a, run: run()), \
             patch("jarvis.core.action_log.log_path", return_value=self.out / "a.jsonl"):
            job_id = await asyncio.to_thread(host._start_background_sync, "system_info",
                                             {"what": "memory"})
            for _ in range(100):
                job = jobs.get_job_manager().get(job_id)
                if job and job.status != "running":
                    break
                await asyncio.sleep(0.05)
        self.assertEqual(job.status, "done")
        self.assertIn("total_gb", job.result)
        self.assertIn(job_id, job_status({}))

    async def test_no_provider_for_video_is_explained(self):
        from jarvis.actions.generate_media import generate_media
        self.assertIn("No video generation provider", generate_media({"kind": "video"}))


if __name__ == "__main__":
    unittest.main()
