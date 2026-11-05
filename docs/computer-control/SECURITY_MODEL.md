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

## 10. Windows controller specifics (Project 1 / 6)

* **Policy sees the real target.** Before the policy runs, `cc_control` resolves the target
  window and control (read-only) and adds the window title (`app`) and the control's real
  accessible name (`label`). A control referenced only by `ref` or automation id therefore
  cannot hide a "Delete"/"Send" label, and typing or hotkeys into a window titled
  PowerShell/cmd/Terminal/Run/Registry Editor are HIGH even when the request did not name it.
* **Launching:** apps by name are LOW; launch arguments make it MEDIUM; launching by path,
  URL, protocol (`ms-settings:`), script/shortcut extension or a built-in system binary that runs
  code (mshta, wscript, rundll32, certutil, powershell, …) is HIGH.
* **Coordinates from the model are never trusted.** `cc_pointer` click/double-click/right-click/
  drag are HIGH (approval); a `source` of "owner"/"accessibility" in tool arguments is treated as
  "model", so the confidence and fingerprint checks always apply. Routine clicks go through
  `cc_control` (accessibility) or `cc_screen` (which locates the target itself).
* **Keys only reach the intended program.** `cc_pointer` type/hotkey: the policy sees the real
  foreground window title (unknown → HIGH). The UIA backend refuses to send keys when the
  foreground window does not belong to the target window's process.
* **Password detection fails closed:** if UIA cannot tell whether a field is a password field,
  its value is not read.
* **Enrichment only when the engine is on** and no stop is held.
* **No answering dialogs for the owner.** Closing a window with unsaved work reports the
  dialog text and buttons and stops; nothing is clicked automatically.
* **Only own processes are force-closed**, and `kill` is HIGH (approval).
* **Fallback input safeguards:** screen bounds, failsafe corners, max 6 inputs / 3 s and a
  minimum gap (click-storm guard), a fingerprint re-check of the target area (refuses if the
  screen changed since the target was located), coordinates from OCR/vision/model need
  confidence ≥ 0.8 **and** a fingerprint, text typed in 200-char chunks with a stop check
  between chunks, max 5000 chars.
* **Password fields:** `set_text` into a UIA password field marks the call `is_password`
  so the logged `text` becomes `[password-field]`; the value is never read back, listed or
  returned.

## 11. Orchestrator specifics (Project 2)

* Plans never change policy: every step still goes through the runner (policy, approval,
  audit, timeout). A plan's `requested_level` can only raise a level.
* Values taken from an earlier step's **result** (window titles, read text) are marked
  tainted, which raises the step one level (MEDIUM → HIGH → approval).
* `cc_task` cannot appear inside a plan (no recursion). Plans are capped at 25 steps.
* Recovery never retries denied, cancelled or HIGH-risk steps; at most 3 recoveries per task.
* The cloud planner receives a redacted objective and fenced, redacted context only.
* `cc_emergency_stop` and `cc_engine_status` are SAFE in `core/security.tier_for` so the
  brake is never behind a confirmation banner.

## 12. Browser specifics (Project 3)

* Local/private/credential URLs (`localhost`, RFC1918, `user:pw@`) are HIGH (approval); a
  redirect to such an address after navigation closes the page.
* Submitting a form that has password or payment fields, typing into card/CVV/IBAN/SSN/passport
  fields, uploads and any "Buy/Pay/Send/Post/Delete…" button are HIGH, decided from the real
  element behind the ref (the snapshot), not from the plan.
* Password values are never read back, listed, logged, put in traces or approval details.
  Cookies are never read. Screenshots mask password inputs.
* No automatic browser retries: after a re-render a ref may point at a different element.
