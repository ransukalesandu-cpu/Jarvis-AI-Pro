# Clarification: Prompt Only for Sensitive Actions

This requirement supersedes any wording in the initial plan that could be read as requiring a password on every launch.

- First-ever launch only: require the owner to create and confirm a local PIN/password.
- Later launches, including after laptop restart: open JARVIS normally without a startup password prompt.
- At startup, the owner is not yet authenticated in the new process, but ordinary low-risk conversation and harmless commands should work.
- Before a sensitive command executes, if the current session has not authenticated the owner, pause the command and request local PIN/password verification. If cancelled or incorrect, do not execute the command.
- Successful verification can authorize the owner for the current app session. Restart, explicit lock, privacy lock, and configured session timeout clear that authorization.
- Apply the gate centrally at tool/action dispatch, including plugins and background/proactive tasks, not only in UI controls.
- Unknown or high-impact actions should require owner verification. Preserve existing per-action confirmation prompts too.
- Never restore owner-authenticated FULL_ACCESS from disk.
- Voice and face enrollment remain optional. Voice must fail closed without validated anti-spoof checks. Face must remain disabled unless a tested local implementation exists.
- Keep all changes on this draft PR branch; run tests and do not merge automatically.

This file records the user's clarified desired behavior. It is a specification, not proof that implementation is complete.
