import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
for path in (str(ROOT), str(ROOT / "JarvisAI")):
    if path not in sys.path:
        sys.path.insert(0, path)

from actions import phone_control as phone_action


class TestPhoneControlAction(unittest.TestCase):
    @patch.object(phone_action, "find_adb", return_value="adb")
    @patch.object(phone_action, "_run", return_value=(True, "List of devices attached\nphone-1\tdevice"))
    def test_status_reads_model_android_and_battery(self, mock_run, _mock_find):
        mock_run.side_effect = [
            (True, "List of devices attached\nphone-1\tdevice"),
            (True, "moto g75 5G"),
            (True, "16"),
            (True, "AC powered: false\nUSB powered: true\nstatus: 2\nlevel: 81"),
        ]
        result = phone_action.phone_control({"action": "status"})
        self.assertIn("moto g75 5G", result)
        self.assertIn("Android 16", result)
        self.assertIn("81%", result)
        self.assertIn("charging", result)

    @patch.object(phone_action, "find_adb", return_value="adb")
    @patch.object(phone_action, "_run", return_value=(True, "List of devices attached"))
    def test_no_device_returns_setup_help(self, _mock_run, _mock_find):
        result = phone_action.phone_control({"action": "home"})
        self.assertIn("No authorized Android device", result)

    @patch.object(phone_action, "find_adb", return_value="adb")
    @patch.object(phone_action, "_run", return_value=(
        True, "List of devices attached\nphone-1\tdevice\nphone-2\tdevice"
    ))
    def test_multiple_devices_are_not_silently_selected(self, _mock_run, _mock_find):
        result = phone_action.phone_control({"action": "home"})
        self.assertIn("More than one authorized ADB device", result)

    @patch.object(phone_action, "find_adb", return_value="adb")
    @patch.object(phone_action, "_run", return_value=(True, "List of devices attached\nphone-1\tdevice"))
    def test_open_app_uses_fixed_package_and_serial(self, mock_run, _mock_find):
        result = phone_action.phone_control({"action": "open_app", "app_name": "youtube"})
        self.assertIn("open command", result)
        self.assertEqual(mock_run.call_args.args[0], [
            "adb", "-s", "phone-1", "shell", "monkey", "-p",
            "com.google.android.youtube", "-c", "android.intent.category.LAUNCHER", "1",
        ])

    @patch.object(phone_action, "find_adb", return_value="adb")
    @patch.object(phone_action, "_run", return_value=(True, "List of devices attached\nphone-1\tdevice"))
    def test_unsupported_app_is_rejected_without_running_shell(self, mock_run, _mock_find):
        result = phone_action.phone_control({"action": "open_app", "app_name": "not-a-real-app"})
        self.assertIn("Unsupported app", result)
        self.assertEqual(mock_run.call_count, 1)  # only device discovery

    @patch.object(phone_action, "find_adb", return_value="adb")
    @patch.object(phone_action, "_run", return_value=(False, "device unauthorized"))
    def test_adb_failures_are_reported(self, _mock_run, _mock_find):
        result = phone_action.phone_control({"action": "home"})
        self.assertIn("device unauthorized", result)

    @patch.object(phone_action, "find_adb", return_value="adb")
    @patch.object(phone_action, "_run", return_value=(True, "List of devices attached\nphone-1\tdevice"))
    def test_null_device_parameter_uses_single_authorized_device(self, mock_run, _mock_find):
        result = phone_action.phone_control({"action": "home", "target_device": None})
        self.assertIn("Home command", result)
        self.assertEqual(mock_run.call_args.args[0], ['adb', '-s', 'phone-1', 'shell', 'input', 'keyevent', '3'])

    @patch.object(phone_action, "find_adb", return_value="adb")
    @patch.object(phone_action, "_run", side_effect=[
        (True, "List of devices attached\nphone-1\tdevice"),
        (True, "Starting: Intent\nError: Activity not found"),
    ])
    def test_activity_error_is_not_reported_as_success(self, _mock_run, _mock_find):
        result = phone_action.phone_control({"action": "open_dialer"})
        self.assertIn("failed", result)
        self.assertIn("Activity not found", result)


if __name__ == "__main__":
    unittest.main()
