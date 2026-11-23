# Local uncensored fallback

When Gemini refuses or blocks a plain request, JARVIS can ask a **local** model
on the laptop instead. The model is usually one made with
[Heretic](https://github.com/p-e-w/heretic), which removes refusals from
open-weight models. JARVIS only talks to it through Ollama. No Heretic code is
included here, because Heretic is AGPL and JARVIS is Apache-2.0.

## What it covers

| Path | Falls back? |
|---|---|
| Gemini Live voice, question refused | ✅ answered locally, shown in the log and read with JARVIS's own TTS (`tts_engine`) |
| Gemini Live voice, **action** refused ("delete…", "install…", "send…") | ✅ the local model classifies it as an action, and it is started as an **autonomous task** (`AgentService.start`) |
| Agent task planner (`agent/integration.py`) | ✅ when the cloud planner refuses or is blocked |
| Computer-control planner (`computer_control/orchestrator/planner.py`) | ✅ same |
| Text chat through `text_brain` (`task="chat"`) | ✅ |
| Translate, compare and other task types | ❌ |

The planner and action paths (`uncensored_for_tools`) are **on by default** once a
model is set, because the owner asked for them. Turn them off with
`JARVIS_UNCENSORED_TOOLS=0` or `"uncensored_for_tools": false`.

### Risk the owner accepted

A model whose refusal training has been removed will also follow instructions
hidden in emails, web pages and files much more easily (prompt injection). A
small 4B model on CPU also plans less reliably than the cloud planners. What
still protects the PC does **not** depend on the model:

* owner verification, Privacy Lock and the Autonomous-task switch before any task starts
* planner tool allow-lists, and plan validation against the registered tools
* untrusted-content wrapping (`UntrustedContent`, `core/injection_guard.py`)
* `core/path_guard.py` (JARVIS's own code, credentials and autostart stay protected)
* security tiers / approvals, the action log, the "stop" word and the emergency stop

## Setup on the laptop (8 GB RAM, no GPU)

1. Install [Ollama](https://ollama.com) for Windows.
2. Pick a small Heretic GGUF on Hugging Face. Search for
   `Qwen3-4B-Instruct-2507 heretic GGUF` and use the `Q4_K_M` file (about
   2.5 GB). Larger models will be too slow on CPU.
3. Pull it:
   ```powershell
   ollama pull hf.co/<user>/<repo>:Q4_K_M
   ```
4. Tell JARVIS the model name: either add it to `config/api_keys.json`
   ```json
   "uncensored_model": "hf.co/<user>/<repo>:Q4_K_M"
   ```
   or set the environment variable `JARVIS_UNCENSORED_MODEL`.

On CPU, expect roughly 10–40 seconds for an answer. JARVIS writes
"Gemini declined; asking the local model…" in the log while it waits.

## Settings

| Variable / key | Default | Meaning |
|---|---|---|
| `uncensored_model` / `JARVIS_UNCENSORED_MODEL` | empty (feature off) | Ollama model name |
| `JARVIS_UNCENSORED_FALLBACK=0` | on when a model is set | Kill switch for everything |
| `uncensored_for_tools` / `JARVIS_UNCENSORED_TOOLS=0` | on | Planners + voice actions may use the local model |
| `JARVIS_UNCENSORED_SPEAK=0` | 1 | Show the local answer without reading it aloud |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama address |

"Stop" also cuts off a local answer that is being read out.

## How a refusal is detected

`core/uncensored_fallback.is_refusal()` looks for the usual phrases a model uses
when it declines on policy grounds ("I'm sorry, but I can't help with that",
"against my guidelines", ...). It only checks the beginning of the reply, and
for voice it only checks short replies (≤ 400 chars). Ordinary failures such as
"I can't open Spotify, it isn't installed" are not counted as refusals. If the
local model refuses too, nothing more happens.
