# JARVIS Personal Mode (Local Owner Opt-in)

Personal Mode reduces repetitive confirmation banners for selected **local** desktop actions. It is intended for a trusted, single-user installation where you control the PC and understand that desktop automation can interact with whichever application is currently focused.

## Enable on Windows

Open PowerShell and set the variable **before starting JARVIS**:

```powershell
$env:JARVIS_PERSONAL_MODE = '1'
cd C:\path\to\Jarvis-AI-Pro
.\.venv\Scripts\python.exe .\main.py
```

To keep the setting for future terminals, run this once and then fully restart JARVIS:

```powershell
[Environment]::SetEnvironmentVariable('JARVIS_PERSONAL_MODE', '1', 'User')
```

To turn Personal Mode off again:

```powershell
[Environment]::SetEnvironmentVariable('JARVIS_PERSONAL_MODE', $null, 'User')
```

For the current PowerShell window only, use `Remove-Item Env:JARVIS_PERSONAL_MODE -ErrorAction SilentlyContinue` before launching JARVIS. Environment-variable changes made in Windows Settings/PowerShell do not rewrite the environment of a JARVIS process that is already running; restart it after changing the setting.

## What changes

With `JARVIS_PERSONAL_MODE=1`, these selected actions run without the extra confirmation banner and remain audited/rate-limited:

- Direct local desktop input (click, type, key press, hotkey, paste, drag).
- Basic file operations (create, copy, move, rename, write) that are already permitted by the file tool's user-home and protected-path checks.
- Desktop wallpaper changes.

## What stays protected

Personal Mode does **not** disable the security layer. These actions still require the normal confirmation flow or existing checks:

- File deletion and bulk desktop organization.
- Sending emails/messages, Instagram publication, and phone calls.
- Generated-code tasks, development/installer operations, system shutdown, and high-impact repair/update actions.
- Unknown/unrecognized application launches.
- Actions triggered by untrusted web/email/file content without a fresh user request.
- Owner/Voice-ID checks when enabled, rate limits, protected-path checks, and the tamper-evident audit ledger.

## Important

The computer-control allowlist includes mouse and keyboard actions. Those actions operate on the currently focused application, so a click or keystroke can still submit a form or change something in a browser. Use Personal Mode only on a PC you own and control, keep JARVIS's remote dashboard private, and disable the mode when other people can use the machine. The setting is intentionally controlled through the local process environment, not through a voice command or tablet remote command.
