# Notes

P6 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`. Tool: `notes`.

- Plain Markdown files in one folder (default `<data>/notes`). Point it at an **Obsidian vault** with
  "set my notes folder to D:\Vault" (or `JARVIS_NOTES_DIR`). Optional front matter keeps tags and the created time.
- Voice: "note that the client wants blue" (`create`), "add buy milk to my shopping note" (`append`;
  default note `Inbox`), "read my logo note", "search my notes for invoice", "list my work notes" (tag filter),
  "delete the old note" (moved to `.trash`, recoverable), "add my Ideas note to my design knowledge" (`to_knowledge`).
- Titles are made filesystem-safe; an existing note is never overwritten (`Title 2.md`).
- Tiers: read/search/list/folder SAFE, create/append/delete/to_knowledge SENSITIVE, set_folder DANGEROUS.
