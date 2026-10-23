"""Voice-driven desktop UI interaction.

Uses Windows UI Automation (pywinauto) to find a visible control by its exact
accessible name. It deliberately refuses ambiguous matches and high-impact
buttons unless the existing confirmation gate approves. On other platforms it
supports explicit coordinate clicks via PyAutoGUI only.
"""
from __future__ import annotations

import re
import platform

from core import confirm as confirm_gate

_HIGH_IMPACT = re.compile(
    r"\b(delete|remove|erase|purchase|buy|pay|send|submit|publish|post|"
    r"shutdown|restart|format|reset|uninstall|transfer|confirm|allow|grant)\b",
    re.IGNORECASE,
)


def _clean_label(value) -> str:
    label = str(value or "").strip()
    if not label or len(label) > 100 or any(ord(c) < 32 for c in label):
        return ""
    return label


def _click_named_control(label: str) -> str:
    if platform.system() != "Windows":
        return (
            "Accessible-name button clicking is currently implemented for Windows UI Automation. "
            "On this OS, use the app's keyboard shortcut or provide explicit screen coordinates."
        )
    try:
        from pywinauto import Desktop
    except ImportError:
        return (
            "Windows UI Automation dependency is missing. Install pywinauto in the same Python "
            "environment running JARVIS, then restart JARVIS."
        )
    try:
        desktop = Desktop(backend="uia")
        matches = []
        for window in desktop.windows():
            try:
                if not window.is_visible():
                    continue
                for control in window.descendants():
                    try:
                        if not control.is_visible() or not control.is_enabled():
                            continue
                        name = (control.window_text() or "").strip()
                        if name.casefold() == label.casefold():
                            ctype = control.element_info.control_type
                            if ctype in {"Button", "Hyperlink", "TabItem", "MenuItem", "CheckBox", "RadioButton"}:
                                matches.append((window, control, ctype))
                    except Exception:
                        continue
            except Exception:
                continue
        if not matches:
            return f"No visible enabled button/control named '{label}' was found. Nothing was clicked."
        if len(matches) != 1:
            locations = ", ".join(dict.fromkeys(m[0].window_text() or "unnamed window" for m in matches[:5]))
            return (
                f"Found {len(matches)} controls named '{label}' across multiple locations ({locations}). "
                "Nothing was clicked; specify the app/window to disambiguate."
            )
        window, control, ctype = matches[0]

        def perform() -> str:
            try:
                # invoke() activates the semantic control without relying on coordinates.
                control.invoke()
            except Exception:
                control.click_input()
            return f"Clicked '{label}' ({ctype}) in '{window.window_text() or 'active window'}'."

        if _HIGH_IMPACT.search(label):
            return confirm_gate.request(
                key="ui-click-high-impact",
                title=f"Click '{label}'?",
                detail=(
                    f"JARVIS found a control named '{label}' in "
                    f"'{window.window_text() or 'an app'}'. This label may trigger a sensitive "
                    "or irreversible action. Confirm on the JARVIS screen before it is clicked."
                ),
                run=perform,
            )
        return perform()
    except Exception as exc:
        return f"Could not inspect or click desktop controls: {type(exc).__name__}: {exc}"


def _click_coordinates(x, y) -> str:
    try:
        x, y = int(x), int(y)
    except (TypeError, ValueError):
        return "For coordinate click, provide integer x and y values."
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        width, height = pyautogui.size()
        if not (0 <= x < width and 0 <= y < height):
            return f"Coordinates are outside the current screen ({width}x{height}). Nothing was clicked."
        pyautogui.click(x, y)
        return f"Clicked screen position x={x}, y={y}."
    except ImportError:
        return "PyAutoGUI is not installed in the Python environment running JARVIS."
    except Exception as exc:
        return f"Coordinate click failed: {type(exc).__name__}: {exc}"


def _ocr_action(label: str, click: bool) -> str:
    from actions.screen_ocr import read_screen_words, find_text_matches
    try:
        words = read_screen_words()
        matches = find_text_matches(label, words)
    except Exception as exc:
        return str(exc)
    if not matches:
        sample = ", ".join(w["text"] for w in words[:25])
        return f"OCR could not find visible text '{label}'. Visible text sample: {sample or 'none detected'}."
    if len(matches) != 1:
        positions = ", ".join(f"({m['x']}, {m['y']})" for m in matches[:5])
        return f"Found '{label}' in {len(matches)} screen locations: {positions}. Nothing was clicked; specify which one."
    match = matches[0]
    if not click:
        return (
            f"OCR found '{match['text']}' near x={match['x']}, y={match['y']} "
            f"with {match['confidence']:.0f}% confidence. This is detected text, not guaranteed button semantics."
        )
    if match["confidence"] < 55:
        return f"OCR confidence for '{label}' is too low ({match['confidence']:.0f}%). Nothing was clicked."

    def perform() -> str:
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.click(match["x"], match["y"])
            return (
                f"Clicked near OCR-detected text '{match['text']}' at x={match['x']}, y={match['y']}. "
                "The click targets the text centre; custom layouts may need manual adjustment."
            )
        except ImportError:
            return "PyAutoGUI is not installed in JARVIS's Python environment."
        except Exception as exc:
            return f"OCR click failed: {type(exc).__name__}: {exc}"

    if _HIGH_IMPACT.search(label):
        return confirm_gate.request(
            key="ui-ocr-click-high-impact",
            title=f"Click near '{label}'?",
            detail=(
                f"Local OCR found '{match['text']}' at x={match['x']}, y={match['y']} "
                f"with {match['confidence']:.0f}% confidence. This may be a sensitive action. "
                "Confirm on the JARVIS screen before clicking."
            ),
            run=perform,
        )
    return perform()


def ui_interaction(parameters: dict, **_kwargs) -> str:
    operation = str(parameters.get("operation", "click_button")).strip().lower()
    if operation in ("click_button", "find_text", "click_visual"):
        label = _clean_label(parameters.get("label"))
        if not label:
            return "Say the exact visible button/control name or text. Nothing was clicked."
        if operation == "find_text":
            return _ocr_action(label, click=False)
        if operation == "click_visual":
            return _ocr_action(label, click=True)
        return _click_named_control(label)
    if operation == "click_coordinates":
        return _click_coordinates(parameters.get("x"), parameters.get("y"))
    if operation == "describe":
        try:
            import pyautogui
            size = pyautogui.size()
            return (
                f"Screen size is {size.width}x{size.height}. Windows UI Automation can find accessible controls; "
                "local OCR can find visible text when Tesseract is installed."
            )
        except ImportError:
            return "PyAutoGUI is not installed, so screen dimensions cannot be read."
    return "Choose click_button, click_coordinates, find_text, click_visual, or describe."


TOOL = {
    "name": "ui_interaction",
    "description": (
        "Interact with visible app buttons and controls from voice requests. Prefer click_button "
        "with the exact accessible name, e.g. 'Settings', 'Save', or 'Bluetooth'. On Windows this "
        "uses UI Automation, requires a unique visible enabled control, and reports ambiguity rather "
        "than clicking a guess. Custom-drawn controls can use find_text for local OCR detection or click_visual to click unique visible text. OCR requires pytesseract plus the separately installed Tesseract OCR engine; screenshots are processed locally. Sensitive labels such as Delete, Send, Submit, Purchase, Reset, or "
        "Allow require the user's confirmation. For other operating systems use click_coordinates "
        "only when the user explicitly gives screen coordinates. Use computer_settings action "
        "open_settings to open system settings; use this tool to click controls inside apps. "
        "Never guess a button name or use this tool to bypass an app's own security prompt."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {
                "type": "STRING",
                "enum": ["click_button", "click_coordinates", "find_text", "click_visual", "describe"],
            },
            "label": {
                "type": "STRING",
                "description": "Exact visible accessible name or OCR-visible text of a button/control.",
            },
            "x": {"type": "INTEGER", "description": "Screen X coordinate, only for explicit coordinate requests."},
            "y": {"type": "INTEGER", "description": "Screen Y coordinate, only for explicit coordinate requests."},
        },
        "required": ["operation"],
    },
    "handler": ui_interaction,
}
