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
