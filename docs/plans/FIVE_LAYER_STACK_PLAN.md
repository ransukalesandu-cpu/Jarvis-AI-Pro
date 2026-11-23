# Five-layer stack upgrade plan

Source: the owner's 5-layer open-source list (voice input, brain, laptop control,
phone control, voice output, plus "one command" routines). This plan maps each
suggestion against what JARVIS already has and proposes only the real gaps.

Status: **plan only — waiting for the owner's approval before any code.**

## 1. Gap analysis

| Layer | Suggested | Already in JARVIS | Verdict |
|---|---|---|---|
| Wake word | openWakeWord | `core/wake_word.py` ("Hey Jarvis", openWakeWord) + double-clap wake | Done |
| STT | whisper.cpp / faster-whisper / Vosk | `voice/local_stt.py` (faster-whisper, CPU int8) — dictation only | **Gap: not used as a voice path** |
| Brain | Ollama | `core/hybrid_llm_router.py`, `core/text_brain.py` (ollama provider) | Done |
| Tools | MCP servers | `core/mcp_client.py` (stdio + HTTP nodes), `SKILL.md` skills | Done (client). Serving JARVIS tools *as* an MCP server is deliberately blocked (`test_no_mcp_server_exposes_the_tools`) — kept |
| Orchestration | LangGraph | `agent/planner.py`, parallel engine, registry-aware planning | Done — skip |
| Laptop control | PyAutoGUI / AHK / Open Interpreter | Computer Control Engine (UIA, files, windows, guarded input) | Done |
| Browser | browser-use | `computer_control/browser` (Playwright + DOM refs) | Done — skip (would add a second LLM loop and heavy deps) |
| Screen parsing | OmniParser / Agent-S | `computer_control/visual/perception.py` (UIA → DOM → OCR → Gemini vision) | Done — OmniParser needs a GPU and contradicts "no local vision model" |
| Phone control | uiautomator2 / scrcpy / Appium / KDE Connect | `laptop_agent/devices/android.py` (ADB: screenshot, tap x/y, swipe, type, keys, apps, files) | **Gaps: element-level control, live screen view, away-from-home reach** |
| Voice output | Piper / Kokoro | `core/tts.py` (Kokoro, edge-tts, ElevenLabs) | **Small gap: Piper as a low-RAM engine** |
| One command | n8n / skills registry | Recorded workflows (`computer_control/workflows`), skills | **Gap: owner-written routines across devices** |
| Offline | — | `OFFLINE=1` kill switch (`core/privacy.py`) | **Gap: with OFFLINE=1 Gemini Live can't run, so JARVIS has no voice** |

## 2. Proposed PRs (stacked, one per item)

### PR 1 — Offline voice loop (`feature/offline-voice-loop`)
Fallback voice path when Gemini Live is unavailable (no network, quota, `OFFLINE=1`, or `JARVIS_VOICE=local`):
wake word → VAD-cut utterance → faster-whisper → `text_brain` (cloud brain if reachable, else Ollama) → local TTS.
- Reuses existing wake detector, `local_stt`, router and TTS; no new heavy deps.
- Tools: same registry; tool calls go through the existing policy/approval/security tiers (Voice ID still gates Full Access).
- Auto-switch back to Gemini Live when it becomes reachable again.
- Tests: mocked STT/LLM/TTS pipeline, OFFLINE boot test.

### PR 2 — Piper TTS engine (`feature/piper-tts`)
Optional `PiperTTS` engine in `core/tts.py` (`piper-tts` package, voice model under `<data>/models/piper`).
Lighter and faster than Kokoro on CPU; selectable in Settings, used by the offline loop when chosen.
Uses the maintained `OHF-Voice/piper1-gpl` package (the old `rhasspy/piper` repo is archived).
Note: piper1-gpl is GPL-3.0 — installed as an optional runtime dependency, not vendored, so the repo stays Apache-2.0.

### PR 3 — Android element-level control (`feature/android-ui-tree`)
Today the phone is driven by coordinates. Add UI-tree actions:
- `ui_tree` (compact list of visible elements: text, content-desc, resource-id, bounds, clickable),
  `tap_element(text|desc|id)`, `wait_for(text, timeout)`, `scroll_to(text)`, `set_text(id, value)`.
- Backend: plain `adb shell uiautomator dump` (no extra dep); uses **uiautomator2** automatically when installed (faster, more reliable).
- Planner prefers element actions; screenshot + tap x/y stays as fallback.
- Password fields stay masked; tree text is wrapped as untrusted content.

### PR 4 — Phone live screen (`feature/phone-screen-view`)
- `phone_screen(action="show")` launches **scrcpy** on the laptop (mirror + mouse/keyboard control) for the chosen device; `hide` closes it.
- Web UI "Phone" floating window: low-FPS screencap preview (on demand only, stops when closed).
- Setup check + install hint in `windows_setup.py` (scrcpy zip, adb already required).

### PR 5 — Phone reach from anywhere (`feature/adb-over-tailscale`)
- `AndroidManager` accepts Tailscale (100.64.0.0/10) addresses for wireless devices and keeps reconnecting them.
- Docs: Tailscale on laptop + phone + Oracle hub, wireless-debugging port pinning, what breaks when the phone reboots.
- Hub relays phone commands to the laptop agent when the owner is away (existing relay), so "find file X on the laptop and send it to my phone" works off-LAN.
- Limitation stated plainly: ADB wireless debugging turns off after a phone reboot; the planned companion app (Phase 3) removes that.

### PR 6 — Routines (`feature/routines`)
Owner-written `<data>/routines.yaml`:
```yaml
morning:
  phrases: ["good morning", "morning mode"]
  steps:
    - {tool: cc_app, args: {op: launch, name: Outlook}}
    - {tool: phone, args: {action: press_key, key: mute}}
    - {tool: news, args: {action: brief}}
```
- The LLM matches a spoken phrase to a routine; steps run in order through the normal policy/approval/e-stop pipeline.
- Voice: list / run / dry-run. Editing the file is owner-only (JARVIS can't write it), same rule as `mcp_servers.json`.
- Web UI: routines list with run button.

## 3. Not adopted (and why)
LangGraph, n8n, Appium, Home Assistant core (the `home_automation` plugin exists), KDE Connect (LAN-only, overlaps ADB),
Vosk/whisper.cpp (faster-whisper is already in), browser-use, OmniParser, Agent-S / self-operating-computer / Open Interpreter / Leon / Willow
(study material only — their ideas are already covered by the Computer Control Engine).

## 4. Decisions needed from the owner
1. Keep the rule that JARVIS tools are **not** served over MCP to outside clients? (Recommended: keep.)
2. Order: PR 1 → 3 → 5 → 4 → 6 → 2 (phone first after offline voice)? Or a different order?
3. Merge each PR when CI is green without waiting (as for the Cherry Studio work)?

All Windows-only behaviour (audio devices, scrcpy, real phone) is untested here and goes on the owner's Windows smoke test list.
