# OSV findings in the vendored `web/` app

`web/` is a vendored copy of NextChat (Next.js + Tauri 1) that is not part of the JARVIS desktop UI. As of 2026-11-05 it carries about 260 open OSV findings (`web/yarn.lock` ~208, `web/src-tauri/Cargo.lock` ~52). None come from `frontend/` (the new React UI) or the Python requirements.

## Decision (owner, 2026-11-05)
Exclude `web/` from the **gating** OSV scan (`--x-exclude=web` in `.github/workflows/security-scan.yml`) and keep scanning it in a separate **report-only** job (`osv-scanner-web-report`, `fail-on-vuln: false`), so the findings stay visible and nothing is hidden.

## Why not just upgrade
Most findings only go away with major migrations that cannot be verified here (the app cannot be built or run in the review environment):

| Area | Needed for a full fix |
|---|---|
| Next.js | 14 → 15 |
| react-router | 6 → 7 |
| zod | 3 → 4 |
| uuid | 9 → 11, serialize-javascript 6 → 7, merge 1 → 2 |
| Tauri | 1 → 2 (also clears glib 0.15 and several unmaintained crates: adler, bincode, derivative, fxhash, instant, pin-utils, proc-macro-error, safemem, zbus_names, zvariant) |

Semver-compatible bumps (patch/minor: axios, dompurify, js-yaml, lodash, webpack, postcss, openssl, tokio, h2, tar, …) remain possible and are the first thing to do if `web/` is used.

## Revisit
If `web/` is used, do the semver-compatible bumps first, then plan the Next 15 / Tauri 2 migration and remove the exclusion. If it is not used, deleting `web/` removes every one of these findings.
