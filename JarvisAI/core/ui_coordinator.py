"""UI boundary adapters shared by graphical and headless JARVIS runs.

The headless adapter implements the small, thread-safe UI contract expected by
JarvisLive without importing Qt. Confirmation is denied by default in headless
mode because no person is present to approve a consequential action.
"""

from __future__ import annotations


class HeadlessJarvisUI:
    """Headless UI adapter for JARVIS Lite Core running silently in background mode."""

    def __init__(self):
        self.muted = False
        self.current_file = None
        self.state = "INITIALIZING"

    def write_log(self, text: str) -> None:
        print(f"[CoreLog] {text}")

    def set_state(self, state: str) -> None:
        self.state = state
        print(f"[CoreState] {state}")

    def set_audio_level(self, level: float) -> None:
        pass

    def react_avatar_text(self, text: str) -> None:
        pass

    def push_visemes(self, frames, hop, at) -> None:
        pass

    def show_content(self, title: str, text: str) -> None:
        print(f"[CoreContent] {title}\n{text}")

    def show_confirm(self, action_id: str, prompt: str, callback) -> None:
        print(f"[CoreConfirm] Confirmation gated in headless mode for {action_id}: {prompt}")
        # In headless mode without interactive approval, deny dangerous actions by default
        if callback:
            callback(False)

    def prompt_pin(self) -> str | None:
        return None

    def hide_confirm(self) -> None:
        pass

    def start_camera_stream(self) -> None:
        pass

    def stop_camera_stream(self) -> None:
        pass

    def set_voice_id_enabled(self, enabled: bool) -> None:
        pass

    def notify_phone_connected(self) -> None:
        print("[CoreStatus] Phone connected")

    def hud_video_is_active(self) -> bool:
        return False

    def get_plugins(self) -> list:
        return []

    def get_plugin_settings(self) -> dict:
        return {}

    def request_say(self, text: str) -> None:
        print(f"[CoreSay] {text}")

    def wait_for_api_key(self, stop_event=None) -> bool:
        return True

    def prompt_reconfig(self) -> None:
        pass

    def request_close(self) -> None:
        pass
