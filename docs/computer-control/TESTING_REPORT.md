# Computer Control — Testing Report

Commands: `python -m pytest -q` (whole suite), `ruff check jarvis` (CI lint gate).
Linux results are from the sandbox and the `checks` CI job; Windows-only behaviour
runs in the `windows-ui-smoke` job where possible and is otherwise listed as
**pending manual validation by the owner**.

## Phase 0

| suite | file | tests | result |
|---|---|---|---|
| flag, dry run, policy, approval, estop, runner, audit, contract | `jarvis/tests/test_computer_control_phase0.py` | 88 (1 Windows-only, skipped on Linux) | pass (Linux); Windows-only test runs in `windows-ui-smoke` |
| prompt injection (mandatory) | `jarvis/tests/test_computer_control_injection.py` | 45 | pass |
| whole repository | `python -m pytest -q` | 1660 passed, 5 skipped, 0 failed | pass (sandbox, Python 3.13) |
| lint | `ruff check jarvis` | 0 findings | pass |

Before Phase 0, main @ 700f6e4 had 1 failing test
(`test_project_health::test_no_module_uses_a_silent_broad_handler`) and 1 lint error
(`test_plan_trace.py` unused import); both fixed in the Phase 0 PR.

### What the injection suite proves

13 attack texts across screenshot, OCR, web page (visible text, `display:none`, HTML
comment, `hidden` attribute, zero-width characters), document and tool-output
(embedded tool-call JSON) sources:

* every one is flagged and fenced (`=== BEGIN EXTERNAL CONTENT`), hidden parts removed;
* 4 benign texts are not flagged (false-positive guard);
* policy verdicts for delete/click/read/send are identical before and after reading
  the content;
* a deliberately naive agent that turns every instruction into an action gets every
  action `denied`, nothing executes, and the approval prompt is never shown — even
  with an approver that would approve anything;
* content claiming "already approved" cannot get a HIGH action run;
* arguments derived from content (`tainted`) raise MEDIUM to HIGH (approval needed);
* flagged content is written to the security ledger.

### Measured in tests

* Emergency stop interrupts a running action in < 0.5 s (asserted; measured p50
  0.67 ms in the benchmark).
* A hung handler is abandoned at its timeout (0.2 s timeout returns in < 1 s).

## Pending manual validation by the owner (Windows desktop)

| item | why CI cannot prove it |
|---|---|
| Native approval dialog appears over the HUD, PIN accepted/declined | needs an interactive Qt desktop |
| "Jarvis, stop" during a real computer-control action | needs microphone + live session |
| HUD interrupt button stops an action | needs the real window |
| Live app RSS/CPU before/after (`bench baseline --pid`) | needs the owner's running app |

## Project 1 — Windows native control (+ Project 6 fallback input)

| suite | file | tests | where |
|---|---|---|---|
| controller on the fake desktop (apps, windows, controls, dialogs, password fields), fallback-input safeguards, tools through the runner (levels, enrichment, approval, audit redaction, stop), backend selection, send_keys escaping | `jarvis/tests/test_computer_control_windows.py` | 42 | Linux `checks` + `windows-ui-smoke` |
| real pywinauto backend: app/window discovery, Notepad launch → type → Ctrl+S → file content verified → move/resize → minimize/restore → inspect → close; missing control reported | `jarvis/tests/test_computer_control_windows_real.py` | 3 | `windows-ui-smoke` (windows-latest); skipped on Linux |

The real-desktop tests only touch the Notepad instances they start, on a temporary
file, and force-close those PIDs in teardown.

### Pending manual validation by the owner (Windows 10/11 desktop)

| item | why CI cannot prove it |
|---|---|
| Windows 11 Store Notepad / Calculator (UWP) | windows-latest runs Windows Server (classic Notepad, no Store Calculator) |
| Apps installed on the owner's PC (Chrome, VS Code, Office) via Start-menu discovery | runner has a different app set |
| Fallback pointer input on a real screen (pyautogui + mss fingerprint) | CI has no interactive pointer verification |
| Multi-monitor / high-DPI window geometry | runner has one virtual display |
| Typing/hotkeys into a window (SendInput) | the runner has no interactive input desktop; CI saves via the Win32 menu (WM_COMMAND) instead |

The real-Notepad suite (launch → set_text → File->Save → file content verified → move/resize → minimize/restore → inspect → close) **passed on windows-latest** at 96ea340.

Whole repository after Project 1 (sandbox): 1702 passed, 8 skipped, 0 failed; ruff clean.

## Project 2 — Orchestrator

| suite | file | tests |
|---|---|---|
| plan validation (unknown tools, cycles, references, ordering), heuristic and model planners (redaction, bad output, no recursion, no key), Host Agent (multi-app task, honest failure, unmet expectation, recovery ×2, no retry of denied HIGH, taint, file verification, emergency stop mid-task, progress), agent registry, cc_task as a JobManager job (status on StateBus, cancel via `request_cancel`, planning failure) | `jarvis/tests/test_computer_control_orchestrator.py` | 24 |

Pending owner validation: a real multi-app task on the owner's PC through voice
("Jarvis, open Notepad and type …"), the Jobs window showing `cc_task` with Cancel, the
HUD log `CC:` lines, and a cloud-planned task with the owner's Gemini key.

## Project 3 — Browser automation

| suite | file | tests |
|---|---|---|
| controller on the fake browser (navigate/verify, URL rules, search, tabs, fenced page text with hidden-HTML injection, fresh-snapshot refs, password never read, login state, expectations, download/upload verification, masked screenshot, no browser installed), `cc_browser` policy (private URL approval, checkout/card fields HIGH, login submit approval with password redaction, upload HIGH, page text never a command), tasks (open Chrome and search; browser + desktop agents in one task) | `jarvis/tests/test_computer_control_browser.py` | 22 |

Pending owner validation: real Edge/Chrome launch through Playwright's installed channel, the
JARVIS profile keeping a sign-in, a real download into `Downloads\JARVIS`, masked screenshot.

## Project 4 — Visual understanding

| suite | file | tests |
|---|---|---|
| hybrid order (accessibility first with no capture, DOM second, OCR third with fingerprint, vision last with password masking verified on the uploaded pixels), no vision when disallowed/unconfigured, vision reply fenced, OCR fallback, verify text; `cc_screen` click via control (no coordinates), via OCR (guarded coordinates), low-confidence vision refused, destructive target HIGH | `jarvis/tests/test_computer_control_visual.py` | 13 |

Pending owner validation: hosted Gemini vision on the owner's screen (key + network), Tesseract
installed on the owner's PC, masking on a real login window, multi-monitor offsets.

## Project 5 — Workflows

| suite | file | tests |
|---|---|---|
| draft only from successful tasks, password → parameter, versions, trust after 3 verified runs and reset on a layout change, validation (missing params, removed tools), run-time password never written, save needs approval, untrusted run needs approval / trusted does not, list/show/validate/delete, not plannable | `jarvis/tests/test_computer_control_workflows.py` | 10 |

Pending owner validation: Supabase metadata sync with the owner's cloud memory configured.
