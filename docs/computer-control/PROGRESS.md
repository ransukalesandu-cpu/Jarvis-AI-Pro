# Computer Control — Progress

Statuses: NOT STARTED, RESEARCHING, IMPLEMENTING, TESTING, BLOCKED, VERIFIED, MERGED,
REPLACED, NOT APPLICABLE.

| # | Project | Status | PR | Merge commit |
|---|---|---|---|---|
| 0 | Foundation | TESTING | (this PR) | — |
| 1 | Windows native control (+6 fallback input) | NOT STARTED | — | — |
| 2 | Orchestrator (UFO²-inspired) | NOT STARTED | — | — |
| 3 | Browser automation | NOT STARTED | — | — |
| 4 | Visual understanding | NOT STARTED | — | — |
| 5 | Workflow learning | NOT STARTED | — | — |
| 6 | Fallback input | folded into Project 1 | — | — |
| 7 | MCP / Tool Registry | NOT STARTED | — | — |
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
