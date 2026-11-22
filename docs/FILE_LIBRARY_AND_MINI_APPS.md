# File library and Mini Apps

P10 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`.

## File library (`file_library`)
An index of files JARVIS made or received: translations, backups, generated images (`Pictures\JARVIS` is
scanned), downloads and exports. Features call `library.register(path, kind)`.
- "Show my recent files", "find the Sinhala contract translation" (`list` / `search`, filter by kind:
  translation, backup, media, download, export, document).
- "Open it" (`open`), "send the logo to my phone" (`send_to_phone` via the paired Telegram chat — DANGEROUS,
  so it asks first; from Telegram you can answer YES).
- `forget_missing` drops entries whose files were deleted. Stored in `<data>/library.json` (last 2000).

## Mini Apps (`mini_app`)
Web tools opened in **their own app window** (Edge/Chrome `--app` mode) with a **separate login profile per app**
(`<data>/miniapps/<name>`), so client accounts stay apart from your main browser.
- Built-in: figma, canva, fiverr, chatgpt, claude, gemini, github.
- "Open Figma", "add Notion as a mini app: https://www.notion.so" (`add`, https only, DANGEROUS), `remove`, `list`.
- Without Edge/Chrome the system browser opens the URL instead.
