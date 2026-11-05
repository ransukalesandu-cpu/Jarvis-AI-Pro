# Skills and MCP servers

## Skills (`SKILL.md`)
A skill is a folder `<user data>/skills/<name>/SKILL.md` (Windows: `%LOCALAPPDATA%\jarvis\skills\`):

```
---
name: weekly-report
description: Build the Friday status report from my notes and calendar.
version: 1
---
1. Read this week's notes.
2. ...
```
Rules: `name` = folder name (lowercase letters, digits, `-`, `_`), `description` required (max 300 characters), body required, file ≤ 32 KB.
Only name + description are put in the prompt; JARVIS loads the body with `skills(action="use", name=...)` when a request matches.
A skill is **instructions only** — it never runs code; its steps use the normal tools and their confirmation tiers.
Voice: list / use / create / delete / enable / disable. Creating or deleting is DANGEROUS tier (needs your confirmation),
because a saved skill steers every later session. A skill in your folder overrides a built-in one of the same name.

## MCP servers
Create `<user data>/mcp_servers.json`:

```json
{"servers": {
  "notes": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Notes"],
            "env": {"SOME_KEY": "value"}, "enabled": true}
}}
```
Servers are stdio child processes started in the background at launch (or on first use). JARVIS discovers their tools and
calls them through the single `mcp` tool: `list`, `tools`, `describe`, `call`, `reload`, `restart`.

Safety: only you can edit this file (JARVIS cannot); a server gets a minimal environment plus the `env` you list (no API keys
from JARVIS); results are text-only, capped at 8000 characters and wrapped as untrusted external content; a `call` needs a
confirmation unless the server marks that tool read-only; three failures in a row stop retries until `restart`.
The old `core/mcp_hub.py` (a local-only registry that nothing used) was removed.
