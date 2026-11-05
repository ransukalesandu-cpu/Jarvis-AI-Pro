# Tasks 7-8 audit: voice reliability, device nodes, chat/UX

Decision: **no code changes** in this pass. These areas depend on a real microphone, speaker,
Gemini Live session, and the Qt UI, none of which can be exercised in the build sandbox. Changing
the live voice path blind risks regressions the owner would only find by talking to Jarvis.

Already present (read in `jarvis/main.py`): session resumption handle kept across reconnects,
voluntary reconnect signal (`request_reconnect`, `keep_context`), quota fallback to a cheaper
model, reconnect-safe tool state.

Proposed next steps (need the owner on Windows to verify each):
1. Reconnect telemetry: count reconnects/min and surface in the HUD, to find real flakiness first.
2. Device nodes: reuse the MCP client (`docs/SKILLS_AND_MCP.md`); a second PC/phone exposes an MCP
   server and Jarvis calls it as tools, no new protocol needed.
3. Chat/UX polish and self-evaluation: split `main.py`, `hud_workspace.py`, `neural_viz.py` only after
   the owner approves, with screenshots as the test.
