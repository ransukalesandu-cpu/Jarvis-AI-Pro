# Security V2 — Test report

All figures below are from commands actually run in the developer sandbox (Linux, Python 3.12, `QT_QPA_PLATFORM=offscreen`). Nothing was run on Windows.

| Run | Command | Result |
|---|---|---|
| Final, 3 consecutive full runs | `python3 -m pytest -q -p no:cacheprovider jarvis/tests` | 1363 passed / 1371 passed / 1371 passed, 4 skipped each (the first run predates the Phase 6 test file) |
| Lint | `ruff check jarvis` | All checks passed |
| Import budget | `python3 -X importtime -c "import jarvis.main"` | ~0.71–0.76 s |

New Security V2 tests: Phase 1 identity/policy 20, Phase 2 owners 22, Phase 3 Guest 22, Phase 4 settings + SQL static checks 13, Phase 5 UI 9, Phase 6 hardening 8.

## What the tests do not prove
- The SQL file was only checked as text (RLS, grants, columns, 7-day clause). It was **never executed** against Postgres.
- UI tests are headless; nothing was rendered on a real display.
- Voice ID tests use fake verifiers; real accuracy is unmeasured.
- The GitHub workflows (`security-scan.yml`, the extra Windows test list) have **not run**.

## Flaky test
One unexplained failure appeared once in four earlier full runs. Three further full runs on this branch all passed, so it was **not reproduced and not identified**. If it recurs, run `python -m pytest -q -x --tb=short` and capture the first failing test name; I did not guess a cause.
