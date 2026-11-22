# Assistant profiles

P9 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`. Tool: `assistant_profiles`.

A profile is a focused role: its own instructions, an optional preferred text provider, an optional knowledge
base and an optional tool allow-list. **JARVIS's identity, voice, persona (JARVIS / Bihansa) and security never
change** — the profile only adds focus.

- Built-in: `coding` (prefers Claude), `writer` (prefers Claude), `designer`, `tutor`.
- "Switch to coding assistant" / "back to default" (`switch`), "which profile is on?" (`current`), `list`.
- "Create a Fiverr profile that helps with client work, uses my clients knowledge base and only web search and
  notes" (`create`, DANGEROUS: confirmation, because a saved profile steers later sessions); `delete` likewise.
- The active profile's instructions are added to the live system instruction (`assistants.prompt_block()`),
  one-shot text answers prefer its provider (`core/text_brain.py`, falling back to the normal ladder), and its
  knowledge base becomes the active one.
- A tool allow-list only **narrows** what JARVIS may call, enforced in `security.guard`; switching back, the
  emergency stop, task progress, knowledge and notes are always allowed.
- Stored in `<data>/assistants.json`.
