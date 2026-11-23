# Aider coding agent

JARVIS can edit your **existing** code projects by voice, using
[Aider](https://github.com/Aider-AI/aider) (Apache-2.0) with Claude as the brain.

| Tool | Use it for |
|---|---|
| `dev_agent` | a brand-new project from scratch |
| `code_helper` | one standalone file |
| `aider_agent` | changing an existing multi-file project anywhere on the PC |
| `aider_projects` | undo, recent changes, register a project name, status |

## Setup (once)

Aider is installed on its own, not into JARVIS's environment (its dependencies
would clash, and its Python API is not officially supported):

```powershell
python -m pip install aider-install
aider-install
```

Then make sure your **Anthropic API key** is set in JARVIS Settings (a Claude
Pro chat subscription is not an API key). Say "Aider status" to check.

Optional environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `JARVIS_AIDER_MODEL` | `anthropic/<Claude reasoning model from Settings>` | Any Aider model name |
| `JARVIS_AIDER_PATH` | `aider` on PATH, then `~/.local/bin` | Path to the aider executable |
| `JARVIS_AIDER_ROOTS` | Desktop, Documents, Projects, `D:\Projects`, ... | Extra folders (`;`-separated) to search for a project by name |

## Saying it

* "Fix the contact form in my portfolio project"
* "In D:\Projects\shop add a dark mode toggle, focus on src/App.tsx"
* "Register my client site project at D:\Work\client-site as client site"
* "Undo the last Aider change in portfolio" / "What did Aider change in shop?"

The job runs in the background; JARVIS tells you when it is done, with the
branch name and a summary of the changed files. Say "stop" to kill it.

## Safety rails

* Any folder is allowed **except** `core/path_guard.py`'s protected list
  (JARVIS's own install folder, credentials, OS start-up folders).
* Non-git folders get `git init`. If the project is on `main`/`master`, a branch
  `jarvis/aider-<time>` is created first. JARVIS never pushes.
* Aider runs with shell-command suggestions, auto-lint/auto-test commands, URL
  scraping and Playwright switched off on the command line, so a project's own
  `.aider.conf.yml` cannot make it run commands.
* Only the Anthropic key is passed to Aider; other secrets are stripped from its
  environment.
* "Undo" only reverts a commit this tool made (`git revert`, history kept).
* Security tiers: `aider_agent` is DANGEROUS (needs a verified owner in Normal
  mode; runs straight away in Full Access).
