"""Exercise Android command construction with synthetic ADB responses."""
import base64
import subprocess
import unittest
from unittest.mock import patch

from services.phone_controller import AndroidPhoneController


class PhoneControllerTests(unittest.TestCase):
    def setUp(self):
        with patch.object(AndroidPhoneController, "_ensure_connection", return_value=True):
            self.phone = AndroidPhoneController("192.0.2.10")

    def test_battery_does_not_treat_power_source_labels_as_charging(self):
        for status, charging in ((2, True), (3, False), (4, False), (5, True)):
            with self.subTest(status=status), patch.object(
                self.phone, "_run_adb", return_value=(
                    "AC powered: false\nUSB powered: false\nWireless powered: false\n"
                    f"status: {status}\nlevel: 73\n"
                )
            ):
                self.assertEqual(self.phone.get_battery(), {"level": 73, "is_charging": charging})

    def test_camera_uses_camera_intent_instead_of_invalid_component(self):
        with patch.object(self.phone, "_run_adb", return_value="Starting: Intent") as run:
            self.phone.open_app("camera")
        run.assert_called_once_with([
            "shell", "am", "start", "-a", "android.media.action.STILL_IMAGE_CAMERA"
        ])

    def test_screenshot_uses_selected_device_and_preserves_png_bytes(self):
        png = b"\x89PNG\r\n\x1a\nsynthetic-image"
        with patch("services.phone_controller.subprocess.run", return_value=(
            subprocess.CompletedProcess([], 0, stdout=png, stderr=b"")
        )) as run:
            image = self.phone.take_screenshot_b64()
        self.assertEqual(base64.b64decode(image), png)
        self.assertEqual(run.call_args.args[0], [
            "adb", "-s", "192.0.2.10:5555", "exec-out", "screencap", "-p"
        ])
