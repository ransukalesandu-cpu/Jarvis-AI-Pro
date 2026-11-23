# Offline voice loop

When Gemini Live is not available (no internet, quota, `OFFLINE=1`) JARVIS keeps listening and talking with local parts:

```
microphone → "Hey Jarvis" (if wake word is on) → speech cut (energy VAD)
→ faster-whisper (local) → typed-command path → Brain Engine (cloud brain, or local Ollama)
→ local voice (Kokoro, or edge-tts when the network works)
```

- Starts by itself 8 s after Live goes down, and immediately in `OFFLINE=1` mode. Stops as soon as Live reconnects.
- Every spoken request goes through the same gates as a typed command: privacy lock, PIN, wake/sleep, agent commands, security tiers.
- The microphone is ignored while JARVIS is speaking, so it never answers its own voice.

## Setup (Windows)

```
pip install -r requirements-stt.txt     # faster-whisper (offline speech-to-text)
pip install "kokoro>=0.9" soundfile     # offline voice (optional; edge-tts is used when online)
ollama pull llama3.2:3b                 # optional: a local brain for no-internet use
```

## Settings

| Env var | Values | Default |
|---|---|---|
| `JARVIS_OFFLINE_VOICE` | `auto`, `off` | `auto` |
| `JARVIS_OFFLINE_TTS` | `kokoro`, `edgetts` | first one installed |
| `JARVIS_STT_MODEL` | `base`, `small`, `medium` | `small` |

## Limits
- No barge-in while the offline voice is speaking (say "stop" after it finishes, or press the stop button).
- Tool use in the fallback is limited to what the Brain Engine fallback allows (read-only tools).
- Not yet tested on Windows hardware: add to the smoke-test checklist.
