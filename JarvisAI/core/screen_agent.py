"""
Jarvis AI Pro - Multimodal Screen Grounding & OS Agent
Captures the active screen, resolves UI coordinates via Gemini Vision,
and requests security clearance before performing automated mouse/keyboard actions.
"""

import base64
import io
import json
import logging
import os
from typing import Callable, Dict, Any, Optional

try:
    import pyautogui
    from PIL import Image, ImageGrab
except ImportError:
    pyautogui = None
    ImageGrab = None

logger = logging.getLogger("Jarvis.ScreenAgent")


class ScreenAgent:
    def __init__(self, security_check_cb: Optional[Callable[[str, str], bool]] = None):
        """
        :param security_check_cb: Links directly to Jarvis's security confirmation dialog.
        """
        self.security_check = security_check_cb

    def capture_screen_base64(self) -> str:
        """Captures the primary monitor and converts to base64 JPEG."""
        if not ImageGrab:
            raise RuntimeError("Pillow (PIL) is not installed. Run 'pip install Pillow'")
        
        screenshot = ImageGrab.grab()
        buffered = io.BytesIO()
        screenshot.save(buffered, format="JPEG", quality=80)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def locate_and_click(self, user_instruction: str) -> Dict[str, Any]:
        """
        Asks Gemini Vision to locate the element described in `user_instruction`,
        returns coordinates, prompts for security clearance, and executes the click.
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"status": "error", "message": "GEMINI_API_KEY is not configured."}

        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            screen_b64 = self.capture_screen_base64()

            system_instruction = (
                "You are an OS visual grounding system. Analyze the screenshot and user intent.\n"
                "Return a JSON object with keys: {\"found\": bool, \"x_pct\": float, \"y_pct\": float, \"reason\": string}.\n"
                "Coordinates must be normalized from 0.0 to 1.0 (percentage of width and height)."
            )

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    {"inline_data": {"mime_type": "image/jpeg", "data": screen_b64}},
                    f"Action: Find the coordinate to perform this task: {user_instruction}"
                ],
                config={
                    "system_instruction": system_instruction,
                    "response_mime_type": "application/json"
                }
            )

            data = json.loads(response.text)
            if not data.get("found"):
                return {"status": "not_found", "message": data.get("reason", "Element not located.")}

            # Convert percentage coordinates to real screen pixels
            screen_w, screen_h = pyautogui.size()
            target_x = int(data["x_pct"] * screen_w)
            target_y = int(data["y_pct"] * screen_h)

            action_desc = f"Click target at ({target_x}, {target_y}) for task: '{user_instruction}'"

            # Execute Security Confirmation
            if self.security_check and not self.security_check("Screen Action", action_desc):
                logger.warning("[SCREEN-AGENT] Action rejected by user security confirmation.")
                return {"status": "denied", "message": "User declined the screen automation action."}

            pyautogui.moveTo(target_x, target_y, duration=0.4)
            pyautogui.click()

            return {
                "status": "success",
                "x": target_x,
                "y": target_y,
                "details": data.get("reason")
            }

        except Exception as e:
            logger.error(f"[SCREEN-AGENT] Execution error: {e}")
            return {"status": "error", "message": str(e)}
