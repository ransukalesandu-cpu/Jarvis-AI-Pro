# Computer Control — Integration Roadmap

Sequential: Phase 0 → Project 1 → … → Project 8. Each project: inspect upstream →
read source → pick parts → license/dependency check → design → implement → tests →
security/performance checks → PR → CI green → merge → docs → next.
Upstream projects are sources of ideas; nothing is imported wholesale.

| # | Project | Upstream | License | Plan |
|---|---|---|---|---|
| 0 | Foundation | — | — | flag, policy, approval, estop, audit, untrusted, contract, runner, baseline, injection suite |
| 1 | Windows native control (+ Project 6 fallback input) | pywinauto/pywinauto | BSD-3 | `windows/` controller API, UIA backend (pywinauto, already a declared win32 dependency), fake backend for tests, guarded pyautogui fallback; Notepad/Calculator tests on windows-latest |
| 2 | Orchestrator (UFO²-inspired) | microsoft/UFO | MIT | host agent + app agents + task context + execution trace + recovery, on top of `agent/planner` / `dependency_graph`; every task a JobManager job |
| 3 | Browser automation | microsoft/playwright, browser-use/browser-use | Apache-2.0 / MIT | Browser controller on Playwright with the installed Edge/Chrome channel (no bundled Chromium); browser-use evaluated for ideas only |
| 4 | Visual understanding | simular-ai/Agent-S, bytedance/UI-TARS-desktop, microsoft/OmniParser | Apache-2.0 / Apache-2.0 / CC-BY-4.0 (model weights AGPL for icon detector) | perception engine with hybrid order accessibility → DOM/app API → OCR/visual → coordinates; hosted Gemini only, redaction + password masking first; no local vision model |
| 5 | Workflow learning | OpenAdaptAI/OpenAdapt | MIT | recorder → validator → versioned library on Supabase metadata (reusing `agent/workflow_library`); owner-approved, redacted, never trusted after one success |
| 6 | Fallback input | asweigart/pyautogui | BSD-3 | folded into Project 1 (owner decision 4) |
| 7 | MCP / Tool Registry | mediar-ai/terminator | MIT | every cc function a `ToolSpec` in the existing registry; MCP exposure evaluated against `core/mcp_client.py` |
| 8 | Benchmarks | xlang-ai/OSWorld, microsoft/WindowsAgentArena | Apache-2.0 / MIT | own synthetic suite (no VMs, no Docker, never destructive), numbers vs Phase 0 baseline |

License notes are from the upstream repositories' LICENSE files at evaluation time
and are re-checked when each project starts (recorded in PROJECT_AUDIT.md).

## Dependencies

No new runtime dependency in Phase 0. Projects reuse what `requirements.txt` already
declares: `pywinauto` (win32), `pyautogui`, `mss`, `pytesseract`, `psutil`, `playwright`,
`pillow`. Any new dependency is justified in PROJECT_AUDIT.md with a RAM measurement.
