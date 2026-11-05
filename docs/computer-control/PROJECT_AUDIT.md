# Computer Control — Project Audit

What already existed before Phase 0 (main @ 700f6e4), what it does, and how the engine
uses it. Read from source, not assumed.

## Existing computer-control code

| Module | What it does today | Gap / decision |
|---|---|---|
| `actions/computer_control.py` (`computer_control` tool) | pyautogui-based type/click/hotkey/screenshot helpers with `FAILSAFE`; uses `config/api_keys.json` for OS hints | no policy levels, no verification; kept as is (legacy tool), new engine tools are `cc_*` |
| `actions/desktop_automation.py` | launch apps, pyautogui input | same; Project 1 controller supersedes for new flows |
| `actions/ui_interaction.py` | pywinauto UIA lookup by exact accessible name, refuses ambiguous/high-impact buttons via confirm gate | good idea reused: exact-name match, refuse ambiguity |
| `actions/open_app.py` | alias table + launch per OS | reused by the Windows controller for app discovery aliases (Project 1) |
| `actions/browser_control.py` (1297 lines) | Playwright/webbrowser control | Project 3 evaluates; new Browser Controller reuses `core/browser_automation` safety rules |
| `core/browser_automation.py` | visible, bounded Playwright tools; never submits forms/purchases/downloads; private-IP guard | its allow-list rules are reused in Project 3 |
| `core/ui_automation.py` | screenshot → Gemini → one action loop | Project 4 replaces coordinate-first with the hybrid order |
| `actions/screen_ocr.py` | local pytesseract OCR | reused by the visual engine |
| `agent/computer_use.py` | controlled desktop actions, named targets resolved through `ScreenVision`, stop event, action cap, dry run, screen-bounds/failsafe-corner checks | design reused for the fallback input safeguards (Project 1/6) |
| `agent/accessibility.py` | read-only UIA/AT-SPI/AX lookup | reused as an accessibility source in Project 4 |
| `agent/screen_vision.py` | accessibility → OCR → vision element resolution | reused by the visual engine |
| `agent/policy.py` | READ/WRITE/CONSEQUENTIAL for autonomous steps; `SCREEN_ACTION` always consequential | engine policy is separate but mapped (LOW≈READ, MEDIUM≈WRITE, HIGH≈CONSEQUENTIAL); orchestrator steps pass both |
| `agent/planner.py`, `agent/dependency_graph.py`, `agent/executor.py` | task planning, dependency ordering | Project 2 builds on them |
| `agent/workflow_library.py` | Supabase-only, descriptive templates; never replays saved steps | Project 5 extends with validation/versioning, same storage |
| `core/pc_control.py` | generic PowerShell/winget/Explorer helpers with cancel_event | not exposed to the engine (no unrestricted shell for the AI) |
| `core/mcp_client.py`, `actions/mcp.py` | MCP client | Project 7 evaluates MCP exposure |

## Security layer

| Module | Relevant behaviour |
|---|---|
| `core/dispatcher.py` | tier 1 allow-list, everything else privileged; Privacy Lock blocks |
| `core/security.py` | `guard()`, tiers, HMAC audit ledger, untrusted provenance check |
| `core/full_access.py` | Full Access default ON (no confirmations); untrusted-content rules kept |
| `core/confirm.py` | non-blocking HUD banner confirmation; not suitable for a worker that needs a blocking yes/no → engine uses its own native prompt through the same Qt signal as `prompt_pin` |
| `security/auth_manager.py` | states, Privacy Lock, PIN (Argon2, lockout), owner access |
| `core/path_guard.py` | secret/code roots |

## Findings fixed in Phase 0

* `core/tool_catalog.py:166` had a silent `except Exception: continue`, failing the
  repository's own `test_no_module_uses_a_silent_broad_handler` on main → now routed
  through `failsoft.suppress`.
* `jarvis/tests/test_plan_trace.py` imported `Plan` unused → `ruff check jarvis` (the CI
  lint gate) failed on main → removed.

## License / dependency check (Phase 0)

No new dependency. `psutil` and `pillow` are already declared.

## Project 1 — Windows native control (pywinauto) + Project 6 fallback input (pyautogui)

**Upstream inspected:** pywinauto/pywinauto (BSD-3-Clause), asweigart/pyautogui (BSD-3-Clause).
Both already declared in `requirements.txt` (`pywinauto; sys_platform == "win32"`, `pyautogui`),
so no new dependency.

What was taken (ideas and APIs, no vendored code):

| upstream piece | used for |
|---|---|
| pywinauto `Desktop(backend="uia").windows()`, `element_info` (name, control_type, automation_id, class_name, runtime_id) | window + control discovery; refs are `<hwnd>:<runtime id>` |
| UIA patterns via wrappers: `invoke()`, `set_edit_text()`, `get_value()`, `select()`, `toggle()` / `get_toggle_state()` | accessibility-first interaction; `click_input()` (real mouse) only when no pattern works |
| UIA `CurrentIsPassword` | password-field detection; value never read |
| Win32 `HwndWrapper`: `minimize/maximize/restore/move_window/close/set_focus/is_minimized/is_maximized` | reliable window state and geometry |
| `menu_select("File->Save")` | menu paths |
| `keyboard.send_keys` syntax (`{VK_CONTROL down}`, `{ENTER}`, brace escaping) | hotkeys and literal text into a named window |
| pyautogui `FAILSAFE`, `size/position/moveTo/click/dragTo/scroll/write/hotkey` | fallback driver only |

Not taken: pywinauto's `Application.start/connect` timing helpers (replaced by an explicit,
interruptible wait-for-window in the controller), pyautogui `locateOnScreen` image search
(Project 4 handles visual location with the hybrid order).

Compatibility: pywinauto needs COM initialised per thread; the runner's worker threads call
`CoInitializeEx(COINIT_APARTMENTTHREADED)` once each. Windows 11 Notepad (store app) launches
through a stub process whose PID differs from the window's — the controller matches the new
window by PID **or** by process name/title among windows that did not exist before launch.

Existing modules: `actions/ui_interaction.py`'s exact-name, refuse-ambiguity rule is kept
(ambiguous matches return an error listing the candidates); `actions/open_app.py`'s
`_APP_ALIASES` table is reused for app-name resolution.
