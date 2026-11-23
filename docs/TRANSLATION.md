# Translation

P4 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`. Tool: `translate`.

| Say | Action |
|---|---|
| "Translate 'good morning' to Sinhala" | `text` |
| "Translate what I copied to English" | `clipboard` (result is copied back) |
| "Translate C:\Docs\contract.docx to Sinhala" | `file` |
| "Show my recent translations" | `history` |

- Uses the hybrid text brain (`core/text_brain.py`: your preferred provider, then the configured fallbacks,
  then local Ollama), task `translate`, so a task route can pick the best model for it.
- Sinhala output is written in Sinhala script with English technical terms kept.
- Documents: DOCX and PPTX keep paragraphs, tables and the first run's formatting of each paragraph; PDF is
  translated to a new DOCX; TXT/MD/HTML/code to text. The result is saved next to the original as
  `<name> (<language>).<ext>` and never overwrites anything.
- Long texts are split into ~3500-character chunks; many short segments (DOCX/PPTX) are batched with
  markers, falling back to one call per segment if a model breaks the markers.
- History: last 200 translations (first 500 characters each) in `<data>/translate/history.jsonl`.
- Tiers: `text`, `history` SAFE; `clipboard`, `file` SENSITIVE.
