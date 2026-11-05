# Jarvis AI — Web

The Jarvis AI web and desktop chat interface. It is built on
[NextChat](https://github.com/ChatGPTNextWeb/NextChat) (MIT license, see
[`LICENSE`](./LICENSE)) and includes all of its features:

- **Multi-provider chat**: OpenAI, Azure, Google Gemini, Anthropic Claude, DeepSeek,
  xAI, Moonshot, Alibaba, ByteDance, Baidu, Tencent, iFlytek, ChatGLM,
  SiliconFlow, 302.AI, and any OpenAI-compatible server
- **The `jarvis` model**: your JARVIS desktop app's own brain, served through an
  OpenAI-compatible API (see below)
- **Masks** (persona/prompt templates) and a **prompt library** (`/` in the input)
- **Plugins** and **MCP** (Model Context Protocol) tools, plus an MCP market
- **Artifacts**: preview and share generated HTML/SVG
- **Markdown** with LaTeX, Mermaid diagrams and code highlighting
- **Image input** (vision models) and image generation (DALL·E, Stability)
- **Realtime voice chat** and text-to-speech (OpenAI or Edge TTS)
- Automatic **history compression** for long chats
- **Export** chats as Markdown, image or JSON
- **Cloud sync** via WebDAV or Upstash
- **Access password** protection (`CODE`), PWA install, light/dark themes, 20+ UI languages
- **Desktop app** (Windows/macOS/Linux) via Tauri

## Connect it to JARVIS

1. Choose a long random secret and start JARVIS with it:

   ```bash
   JARVIS_WEB_API_KEY=change-me-to-a-long-random-secret python main.py
   ```

   Or add `"web_chat_api_key": "..."` to `jarvis/config/api_keys.json`. The
   JARVIS dashboard (port 8000) then serves `GET /v1/models` and
   `POST /v1/chat/completions`. Until a key is set, these return HTTP 503.

2. Configure this web UI (`web/.env.local`):

   ```bash
   BASE_URL=http://127.0.0.1:8000
   OPENAI_API_KEY=change-me-to-a-long-random-secret
   CUSTOM_MODELS=+jarvis@openai
   DEFAULT_MODEL=jarvis@openai
   ```

   You can also skip the env file. Open **Settings → Custom Endpoint**, choose
   OpenAI, set the endpoint to `http://127.0.0.1:8000` and the API key to your
   secret, then add `jarvis` under custom models.

The `jarvis` model handles text. Voice, vision, computer control, memory and
phone features stay in the JARVIS desktop app.

## Run

```bash
cd web
yarn install
yarn dev        # development server on http://localhost:3000
yarn build      # production build (standalone server)
yarn export     # static export, used by the desktop app
yarn app:build  # Tauri desktop app (needs Rust)
```

Docker: `docker build -t jarvis-web .` from inside `web/`.

For every other environment variable (provider keys, `CODE`, `HIDE_USER_API_KEY`,
`ENABLE_MCP`, `WHITE_WEBDAV_ENDPOINTS`, …) see [`.env.template`](./.env.template)
and the upstream documentation in [`UPSTREAM_README.md`](./UPSTREAM_README.md).

## Credits

Based on NextChat by Yidadaa and the ChatGPTNextWeb contributors, MIT licensed.
The Jarvis changes are rebranding, removing upstream's paid-service promotion,
disabling the upstream auto-updater, and adding the `jarvis` model integration.
