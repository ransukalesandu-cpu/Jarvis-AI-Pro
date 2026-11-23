# Telegram channel

Talk to JARVIS from your phone when you are away from the PC — P2 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`.

## Setup (once)
1. In Telegram, open **@BotFather**, send `/newbot`, pick a name. Copy the token.
2. Put it in `config/api_keys.json`: `"telegram_bot_token": "123456789:AA..."`
   (or set `JARVIS_TELEGRAM_BOT_TOKEN`). Restart JARVIS — the log shows `[Telegram] channel started`.
3. Say **"pair Telegram"**. JARVIS shows a 6-digit code (valid 10 minutes, burned after 5 wrong tries).
4. Open your bot in Telegram and send `/pair 123456`. Done.

## Use
- Type anything: "find my invoice PDF on the laptop and send it to me", "what's on my calendar", "is the
  backup done". JARVIS runs it like a typed command and sends its written reply back.
- A confirmation needed on the PC is sent to you: reply **YES** or **NO**.
- `/stop` – emergency stop · `/status` · `/help` · `/unpair`.
- Voice: "send this to my Telegram", "send the report file to my phone" (`telegram` tool: `send`,
  `send_file`, `status`, `pair`, `unpair`).

## Security
- Only private chats that paired with a code are accepted; everything else is ignored and audited.
- Remote text uses the same gate as the web UI: refused while JARVIS is locked, waiting for a PIN, silent
  or in Guest Mode; text shaped like a PIN/password command is never accepted; rate limited (30/min).
- `pair` and `send_file` are DANGEROUS (confirmation); `send`/`unpair` SENSITIVE; `status` SAFE.
- Paired chats are stored in `<data>/channels/telegram.json` (owner-only file permissions).
- Uses long polling to `api.telegram.org`: no open port on your PC, works behind any router.
