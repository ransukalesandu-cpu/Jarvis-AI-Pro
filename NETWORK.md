# Network calls

JARVIS sends **no telemetry**: no analytics, crash reporting, usage pings or
automatic update checks. Every outbound call that remains belongs to a feature
you use, and is listed below with a one-line reason.

* **Kill switch:** set `OFFLINE=1` (or `JARVIS_OFFLINE=1`) and every non-local
  DNS lookup and connection is refused at the socket layer
  (`jarvis/core/privacy.py`). LAN devices stay reachable unless
  `JARVIS_OFFLINE_LAN=0`. Features below fail with a normal "connection
  refused" error instead of hanging.
* **Telemetry opt-outs** (`DO_NOT_TRACK`, `HF_HUB_DISABLE_TELEMETRY`,
  `GRADIO_ANALYTICS_ENABLED`, `ANONYMIZED_TELEMETRY`, ...) are set as the
  `jarvis` package loads, before any SDK import. An explicit value you set wins.

Keep this file current: a pull request that adds a new outbound host must add
a line here.

## Desktop assistant (`jarvis/`)

| Destination | Feature (file) | Why |
|---|---|---|
| `generativelanguage.googleapis.com` (Gemini / Gemini Live) | primary voice + vision (`core/gemini.py`, `main.py`) | The realtime voice brain; JARVIS cannot speak without it unless a local LLM is configured. |
| `api.anthropic.com` | `ask_claude`, text fallback (`core/ai_providers.py`, `core/hybrid_llm_router.py`) | Optional reasoning provider, only when an Anthropic key is set. |
| `api.anthropic.com` (via the separately installed Aider CLI) | `aider_agent` (`actions/aider_agent.py`) | Claude edits the owner's local projects; only when the owner asks and an Anthropic key is set. Aider analytics and update checks are switched off. |
| `api.openai.com` | optional provider / fallback (`core/ai_providers.py`) | Only when an OpenAI key is set. |
| `api.groq.com` | optional fast fallback (`core/hybrid_llm_router.py`) | Only when a Groq key is set. |
| `127.0.0.1:11434` (Ollama) / LM Studio | local LLM (`core/llm_client.py`) | Local inference — stays on the machine. |
| `speech.platform.bing.com` (Edge TTS) | default TTS (`core/tts.py`) | Free cloud voice; switch to Kokoro for fully local TTS. |
| `huggingface.co` | Kokoro TTS / SpeechBrain Voice ID / optional Whisper STT first-run model download (`core/tts.py`, `core/voice_id.py`, `voice/local_stt.py`) | One-time model download; blocked in OFFLINE mode, cached afterwards. |
| `api.elevenlabs.io` | ElevenLabs TTS (`core/tts.py`) | Only when that TTS engine is selected. |
| `*.supabase.co` | personal cloud memory, multi-device hub (`core/supabase_cloud_provider.py`, `core/personal_cloud_memory.py`) | Only when `SUPABASE_URL` is configured. |
| DuckDuckGo / Bing / Google search | `web_search` (`actions/web_search.py`) | User-requested web search. |
| `newsfirst.lk`, `adaderana.lk` | news widgets / `web_search` news (`core/hud_workspace.py`) | User-opened news panel. |
| `api.open-meteo.com`, `geocoding-api.open-meteo.com` | weather (`actions/weather_report.py`) | User-requested weather. |
| `query1.finance.yahoo.com` | markets widget (`core/hud_workspace.py`) | User-opened markets panel. |
| `opensky-network.org`, `nominatim.openstreetmap.org`, `routing.openstreetmap.de`, `unpkg.com` (MapLibre) | Earth globe (`core/earth_globe.py`, `core/earth_globe.html`) | User-opened map: flights, geocoding, routes, map library. |
| `www.googleapis.com`, `oauth2.googleapis.com` | Gmail / Calendar / Drive plugins (`plugins/_google_core.py`) | Only after you connect a Google account. |
| `graph.instagram.com` | Instagram plugin (`plugins/instagram_account.py`) | Only when configured. |
| `api.twilio.com` | phone calls (`plugins/phone_call.py`) | Only when Twilio credentials are set. |
| YouTube | `youtube_video`, transcripts (`actions/youtube_video.py`) | User-requested video lookups. |
| Tuya cloud / MQTT broker | smart home, printers (`plugins/home_automation.py`, `plugins/printer_control.py`) | Only for devices you add. |
| Any site you ask it to open | browser automation (Playwright, `computer_control/`) | User-requested browsing. |
| `pypi.org`, `download.pytorch.org` | setup scripts (`Jarvis_Setup.bat`, `tools/windows_setup.py`) | Installing dependencies during setup only. |
| `generativelanguage.googleapis.com` (embeddings) | knowledge base semantic search (`knowledge/store.py`) | Only with `JARVIS_KB_EMBEDDINGS=1`; keyword search works offline. |
| any `http(s)` URL the owner names | knowledge base `add` of a web page (`knowledge/extract.py`) | Fetches the page once when the owner asks to index it. |
| `api.telegram.org` | Telegram channel (`channels/telegram.py`) | Only when `telegram_bot_token` is set; long polling, no inbound port. |
| your WebDAV server | backup upload (`backup/__init__.py`) | Only when a WebDAV URL is configured for backups; https only. |

The dashboard (`dashboard/server.py`) serves CryptoJS from the committed
`dashboard/static/crypto-js.min.js`; it no longer downloads it from a CDN.

## Next-gen web UI (`frontend/` → `jarvis/webui/dist`)

Runs inside QWebEngine from local files and talks to Python over QWebChannel.
No outbound calls.

## NextChat-based web app (`web/`)

| Destination | Why |
|---|---|
| The provider APIs you configure (OpenAI, Anthropic, Google, ...) | Chat requests, through the app's own proxy routes. |
| `sharegpt.com` | Only when you press "Share" on a conversation. |
| `api.github.com` | Only when you press "Check update" in Settings (no automatic check). |
| Google Analytics / Tag Manager | **Off.** Loaded only if you set `GA_ID` / `GTM_ID` yourself. |

Removed: Vercel Analytics, Vercel Speed Insights, the upstream NextChat
default Google Analytics ID, the Google Fonts fetch and the automatic GitHub
update check.
