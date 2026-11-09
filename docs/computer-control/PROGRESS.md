# Computer Control — Progress

Statuses: NOT STARTED, RESEARCHING, IMPLEMENTING, TESTING, BLOCKED, VERIFIED, MERGED,
REPLACED, NOT APPLICABLE.

| # | Project | Status | PR | Merge commit |
|---|---|---|---|---|
| 0 | Foundation | MERGED | [#277](https://github.com/ransukalesandu-cpu/Jarvis-AI-Pro/pull/277) | e14d32e |
| 1 | Windows native control (+6 fallback input) | MERGED | [#278](https://github.com/ransukalesandu-cpu/Jarvis-AI-Pro/pull/278) | c82ece7 |
| 2 | Orchestrator (UFO²-inspired) | MERGED | [#279](https://github.com/ransukalesandu-cpu/Jarvis-AI-Pro/pull/279) | 32bfc21 |
| 3 | Browser automation | MERGED | [#280](https://github.com/ransukalesandu-cpu/Jarvis-AI-Pro/pull/280) | b8eb691 |
| 4 | Visual understanding | MERGED | [#281](https://github.com/ransukalesandu-cpu/Jarvis-AI-Pro/pull/281) | dbb05b9 |
| 5 | Workflow learning | MERGED | [#282](https://github.com/ransukalesandu-cpu/Jarvis-AI-Pro/pull/282) | 569d831 |
| 6 | Fallback input | MERGED (folded into Project 1) | see Project 1 | — |
| 7 | MCP / Tool Registry | TESTING | (this PR) | — |
| 8 | Benchmarks | NOT STARTED | — | — |

## Phase 0 — Foundation

* **Completed:** `jarvis/computer_control/` (flags, policy, approval + native Qt prompt,
  estop wired to `_stop_everything` and `JarvisLive.interrupt`, audit, redaction,
  untrusted content, ToolSpec contract → existing action registry, runner, monitoring,
  baseline bench), `actions/computer_control_engine.py` (`cc_engine_status`,
  `cc_emergency_stop`), 133 new tests incl. the injection suite, docs.
* **Tests:** 1660 passed / 0 failed (sandbox); ruff clean.
* **Performance:** engine +0.5 MB RSS over the app modules, 0 % idle CPU, runner
  p50 0.235 ms, stop latency p50 0.67 ms (PERFORMANCE_REPORT.md).
* **Security findings:** none open. Two pre-existing main failures fixed (failsoft
  discipline, lint).
* **Limitations:** Windows dialog/stop-word/interrupt behaviour pending owner validation.
* **Owner decisions to confirm:** password-field interpretation; protected-paths list.

* **CI:** checks, windows-ui-smoke, lint, semgrep, osv green on 9d0d32d. CodeRabbit review:
  8 findings, all fixed in 9d0d32d (Privacy Lock re-check after prompt, plain-text dialog,
  handler `TimeoutError`, exception-text redaction, stop-latency benchmark validity, test
  coverage, two doc corrections); one nit (benchmark order) answered, not changed.

## Project 1 — Windows native control (+ Project 6 fallback input)

* **Completed:** `jarvis/computer_control/windows/` — `model.py` (apps, processes, windows,
  elements, queries), `backend.py` (protocol + selection, `UnavailableBackend` off Windows),
  `uia.py` (pywinauto UIA + Win32 geometry, per-thread COM init, password detection,
  send_keys escaping), `fake.py` (in-memory desktop: Notepad, Calculator, login form,
  settings app, save dialog), `fallback_input.py` (guarded pyautogui driver: bounds,
  failsafe corners, click-storm guard, screen-change fingerprint, confidence threshold,
  chunked typing), `controller.py` (unified API with verification), `tools.py`
  (`cc_app`, `cc_window`, `cc_control`, `cc_pointer` with per-op policy levels and a
  read-only enrichment step so the policy sees the real window title and control name).
* **Tests:** 42 fake-backend tests + 3 real Notepad tests on windows-latest.
* **Limitations:** see TESTING_REPORT.md "pending manual validation" (Store apps, owner's
  installed apps, real pointer input, multi-monitor/DPI).

## Project 2 — Orchestrator (UFO²-inspired)

* **Completed:** `orchestrator/` — `plan.py` (validated steps, dependency order via
  `agent/dependency_graph`, `{{N.data.x}}` references), `planner.py` (local heuristic planner +
  redacted cloud planner through HybridLLMRouter), `agents.py` (agent registry), `host.py` (Host
  Agent: shared context, trace with redacted args, bounded recovery, file/window/text verification,
  honest report), `jobs.py` (`cc_task` as a JobManager job, StateBus `computer_control` status, HUD
  `CC:` log lines). Runner results now carry post-call redacted args (a password field found during
  the call is masked in traces).
* **Tests:** 25 orchestrator tests.
* **Limitations:** web-UI panel for live cc status not built (status shows in the Jobs window and
  the HUD log); cloud planning needs the owner's key.

## Project 3 — Browser automation

* **Completed:** `browser/` (backend protocol, fake browser, Playwright backend on the installed
  Edge/Chrome with a JARVIS profile on one dedicated thread, controller with verification, `cc_browser`
  tool with element-aware policy enrichment), browser agent in the Host Agent, heuristic planning of
  "search for …" / "go to …" / "open Chrome".
* **Tests:** 22 browser tests.
* **Limitations:** real Edge/Chrome runs are pending owner validation; frames/shadow DOM not
  covered by the snapshot (as in `core/page_snapshot`).

## Project 4 — Visual understanding

* **Completed:** `visual/perception.py` (hybrid accessibility → DOM → OCR → hosted vision, masking,
  fingerprints), `cc_screen` (locate, click by the safest path, describe, read, verify), visual agent.
* **Tests:** 13 visual tests. No local vision model; 0 captures when accessibility/DOM suffice.
* **Limitations:** hosted vision and Tesseract on the owner's PC pending validation.

## Project 5 — Workflow learning

* **Completed:** `workflows/` (draft from verified tasks, password parameters, versions, bounded local
  store, Supabase metadata sync, validation, replay, trust after 3 verified runs), `cc_workflow`.
* **Tests:** 10 workflow tests.
* **Limitations:** Supabase sync pending owner validation with cloud memory configured.

## Project 7 — MCP / Tool Registry

* **Completed:** all 11 tools verified in the real action registry and Tool Catalog, MCP descriptor /
  JSON-Schema adapter (listing only), `cc_file` with Recycle-Bin deletes and no silent overwrite.
* **Tests:** 10 registry/file tests. MCP server exposure: NOT APPLICABLE (security; owner decision).
