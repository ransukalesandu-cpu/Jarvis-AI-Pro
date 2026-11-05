# Computer Control — Security Model

Applies to everything under `jarvis/computer_control/`. Enforced in code
(`policy.py`, `approval.py`, `runner.py`, `untrusted.py`, `redaction.py`) and
covered by `jarvis/tests/test_computer_control_phase0.py` and
`jarvis/tests/test_computer_control_injection.py`.

## 1. Off by default

`JARVIS_COMPUTER_CONTROL=1` opts in. Without it no `cc_*` tool is offered to the
model (`available` returns False) and the runner answers `disabled`.
`JARVIS_COMPUTER_CONTROL_DRY_RUN=1` classifies, approves and logs but never executes.

## 2. Levels (decided from the action, never from the plan's wording)

| Level | Examples | Gate |
|---|---|---|
| LOW | open apps, list/inspect windows and controls, read public pages, view allowed files, screenshots/OCR | runs (owner session, no Privacy Lock) |
| MEDIUM | create/edit/move/copy files, type, click ordinary controls, app preferences, close windows | runs and is logged |
| HIGH | delete files, install/uninstall, system commands/settings, send messages, purchases, account/security changes, uploads, sensitive submissions, protected paths | **native owner approval every time** |

Escalation (only upward): unknown action → HIGH; protected path → HIGH; destructive
control label (Delete, Send, Pay, Sign out, …) → HIGH; typing into a shell/Run box or
shortcuts like Win+R / Ctrl+Shift+Esc / Shift+Delete → HIGH; launching a shell or an
installer → HIGH; non-http(s) URL → HIGH; arguments derived from untrusted content → +1
level. A plan may raise a level (`requested_level`) but never lower it.

## 3. Folders: default-allow with a small protected list (owner decision 5)

Every folder is usable without prompts except:

* JARVIS secrets and key material — `core/path_guard` secret roots (`jarvis/config`
  incl. `api_keys.json`, `pin_vault.dat`, `~/.ssh`, `~/.aws`, … the audit-key directory,
  `%LOCALAPPDATA%\jarvis`) — for reads **and** writes;
* writes into JARVIS's own install folder, shell start-up files and OS autostart
  folders (path_guard code roots);
* writes into Windows system directories: `%SYSTEMROOT%`/`%WINDIR%`, `Program Files`,
  `Program Files (x86)`, `ProgramData`, `$Recycle.Bin`, `System Volume Information`.

These are not refused outright here; they become HIGH and need approval.
**Owner: please confirm this list.**

## 4. Approval (owner decision 9)

* Native PyQt dialog (`qt_prompt.py`) posted to the Qt thread; never a web page or JS.
  `jarvis/webui` and `frontend/src` contain no reference to the approver (tested).
* `NativeApprover` checks AuthManager: Privacy Lock → deny silently; with an enrolled
  PIN the dialog asks for it and `AuthManager.verify_pin` decides (wrong PINs count
  towards the existing lockout); without a PIN the owner session must already be
  verified.
* No approver bound, prompt error, timeout (90 s) or decline → deny. Each HIGH action
  is asked separately; approval never carries over.
* Full Access mode (no confirmations for ordinary tools) does **not** waive HIGH approval.

## 5. Emergency stop (owner decision 6)

`estop.trigger()` is called by `_stop_everything` (the "Jarvis, stop" stop word),
`JarvisLive.interrupt` (HUD interrupt button / `_do_interrupt`), and the
`cc_emergency_stop` tool. `JobManager.request_cancel`/`cancel` set the job's
`cancel_event`, which every action of that job checks. Checks run between actions,
inside every wait and during approval; measured latency in PERFORMANCE_REPORT.md.

## 6. Password fields (owner decision 7 — interpretation to confirm)

Interpreted "password fields thiyaganna" as **protect password fields**:
* text typed into a password field (UIA `IsPassword`, DOM `type=password`, or
  `is_password` on the request) is replaced by `[password-field]` in the action log,
  audit, traces, workflows and approval details;
* screenshots that leave the process have password-field rectangles painted black
  (`redaction.mask_regions`) — enforced in the visual pipeline (Project 4);
* nothing typed into a password field is sent to any provider.

## 7. Untrusted content and prompt injection (owner decision 8)

Screenshots, OCR, web pages, documents, window text and tool output are wrapped as
`UntrustedContent`, fenced with `=== BEGIN/END EXTERNAL CONTENT` markers, with hidden
HTML, comments and zero-width characters stripped from what the model sees. Injection
markers (override instructions, fake owner/system authority, role tags, "already
approved", embedded tool calls, exfiltration requests) are flagged and written to the
security ledger. Enforcement does not rely on detection: a request whose origin is
content is refused unless LOW, never reaches the approval prompt, and the policy never
reads content text.

## 8. Audit

Every action (allowed, denied, dry-run, cancelled, failed) → `actions.jsonl` as
`cc.<action>` with redacted arguments. Policy denials and approval decisions →
HMAC-chained security ledger.

## 9. Not allowed, ever

Hidden access, credential theft, security bypass, an unrestricted shell for the AI,
destructive automatic retries, secrets in logs or commits.
