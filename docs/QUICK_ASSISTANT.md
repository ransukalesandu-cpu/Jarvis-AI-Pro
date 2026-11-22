# Quick Assistant

P5 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`. Act on text selected in **any** app.

## Hotkey (Windows)
Select text anywhere and press **Ctrl+Shift+J**. JARVIS reads the selection, says in one sentence what it is
and offers to explain, summarize, translate, fix the grammar or draft a reply. Change the chord with
`JARVIS_QUICK_HOTKEY` (e.g. `ctrl+alt+q`, `alt+f9`) or turn it off with `JARVIS_QUICK_HOTKEY=off`.

## Voice / tool `quick_action`
| Say | Call |
|---|---|
| "Explain what I selected" | `action=explain, source=selection` |
| "Translate the selected text to Sinhala" | `action=translate, language=Sinhala` |
| "Fix the grammar of what I selected and replace it" | `action=fix_grammar, replace=true` |
| "Summarize what I copied" | `source=clipboard` |
| "Draft a professional reply to this" | `action=reply` / `professional` |

## How it works and why it is safe
- The selection is read with a clipboard round-trip (Ctrl+C) and your previous clipboard is restored.
- Windows password boxes and browser password fields refuse Ctrl+C, so passwords are never read.
- Selected text is wrapped as untrusted content, and the turn stays marked as having seen untrusted text, so
  instructions hidden in a web page or email cannot trigger dangerous tools.
- Answers come from the hybrid text brain (`core/text_brain.py`). Tier: SENSITIVE.
