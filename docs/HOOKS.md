# Lifecycle hooks

JARVIS can run your own code when something happens. Events: `startup`, `shutdown`,
`session_start`, `session_end`, `trigger_fired`, `trigger_failed`, `task_finished`,
`tool_error`, `privacy_lock`. Owner rules (`core/events.py`) can match the same events.

## Script hooks (you create them)
Put a file in `<user data>/hooks/<event>/` — on Windows `%LOCALAPPDATA%\jarvis\hooks\task_finished\notify.ps1`.
Supported: `.py`, `.ps1`, `.bat`, `.cmd`, `.sh`. The script receives JSON on stdin:
`{"event": "...", "payload": {...}, "at": 1767000000.0}` and the variable `JARVIS_HOOK_EVENT`.

Limits: 30 s per run, output capped at 64 KB, no shell, working directory is the hook folder,
minimal environment (no API keys). Symlinks and files starting with `_` or `.` are ignored.
Three failures in a row switch a hook off (you are told). Every run is written to the security ledger.
`JARVIS_DISABLE_HOOKS=1` turns all hooks off. JARVIS never writes into the hooks folder.

## Python hooks (in an action or plugin)
```python
def on_done(event, payload):
    ...
HOOKS = [{"event": "task_finished", "handler": on_done, "name": "my_hook"}]
```
Handlers run in a background thread with a 5 s limit; errors are isolated.

## Payloads
`task_finished` {task_id, state, message} · `trigger_fired` / `trigger_failed` {name, mode, detail} ·
`tool_error` {tool, risk, result} · `session_start` {model} · `session_end` {turns} · `startup` {ledger_ok}.
Payload text can contain web or tool output: treat it as data, never run it.
