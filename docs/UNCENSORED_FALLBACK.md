# Local uncensored fallback

When Gemini refuses or blocks a plain request, JARVIS can ask a **local** model
on the laptop instead. The model is usually one made with
[Heretic](https://github.com/p-e-w/heretic), which removes refusals from
open-weight models. JARVIS only talks to it through Ollama. No Heretic code is
included here, because Heretic is AGPL and JARVIS is Apache-2.0.

## What it covers

| Path | Falls back? |
|---|---|
| Gemini Live voice: a short spoken refusal of what you just said | ✅ answered locally, shown in the log and read with JARVIS's own TTS (`tts_engine`) |
| Text chat through `text_brain` (`task="chat"`, e.g. Quick Assistant) | ✅ when the cloud reply is a refusal or every provider failed/blocked |
| Translate, compare, summaries and other task types | ❌ |
| Tool calling, the computer-control planner, the agent planner | ❌ never |

A model with its refusal training removed also says yes to instructions hidden
in emails and web pages much more easily. In Full Access those planners act on
the PC without confirmation, so they never use this model.

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
| `JARVIS_UNCENSORED_FALLBACK=0` | on when a model is set | Kill switch |
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
