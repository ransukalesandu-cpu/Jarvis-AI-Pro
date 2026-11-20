# ElevenLabs Dual Voice

The native PyQt desktop Live session supports an opt-in `elevenlabs_dual` provider mode. Gemini Live continues to handle the conversation, tools and incoming microphone audio, but returns text rather than generated speech. JARVIS synthesizes each completed response with ElevenLabs and sends decoded 24 kHz mono PCM through its existing speaker queue, preserving the normal output device, interruption and echo-control path. The default `gemini_live` mode is unchanged. Bihansa continues using her separately configured Gemini female voice; the dual male profiles apply only to JARVIS mode.

## Configuration

Pass these keys through the existing application settings/config loader (or
provide the API key as an environment variable):

- `tts_engine`: `elevenlabs_dual` for native desktop integration; `gemini_live` to restore native Gemini speech
- `ELEVENLABS_API_KEY`: API key (preferred secret source); alternatively
  `elevenlabs_api_key` in the existing protected config store
- `elevenlabs_cinematic_voice_id`: voice ID for system announcements
- `elevenlabs_natural_voice_id`: voice ID for normal conversation
- `tts_voice_mode`: `auto`, `cinematic`, or `natural`
- `tts_fallback_voice`: Edge TTS voice; defaults to `en-US-GuyNeural`
- `tts_stability`: 0.0–1.0; defaults to 0.5
- `tts_similarity`: 0.0–1.0; defaults to 0.75
- `tts_speed`: 0.7–1.2; defaults to 1.0

Never commit API keys or put them in frontend/QWebChannel state.

## Mode selection

- `cinematic`: always use the cinematic voice.
- `natural`: always use the natural voice.
- `auto`: deterministic phrase matching selects cinematic for explicit system
  alerts/status phrases; other utterances use the natural voice. The selected
  voice remains fixed for the entire utterance.

## Fallback and cost control

ElevenLabs synthesis errors, missing credentials, network errors and HTTP 429
quota responses fall back to the existing Microsoft Edge TTS engine. The
complete ElevenLabs audio response is obtained before playback, so a provider
failure does not start partial ElevenLabs playback before fallback. Playback
errors are not retried through another provider to avoid duplicate speech.

The fallback is Edge TTS, not Google Cloud TTS: it is already present in this
repository and does not require a paid Google Cloud TTS account. ElevenLabs
usage is subject to the current account plan/quota; this code does not promise
unlimited free generation or attempt to bypass limits.


## Native desktop configuration

The native settings are stored in the existing owner-local `config/api_keys.json`
through `jarvis.memory.config_manager.save_tts_settings()`. For example, from a
trusted local Python setup script:

```python
from jarvis.memory.config_manager import save_tts_settings

save_tts_settings({
    "tts_engine": "elevenlabs_dual",
    "tts_voice_mode": "auto",
    "elevenlabs_cinematic_voice_id": "YOUR_CINEMATIC_VOICE_ID",
    "elevenlabs_natural_voice_id": "YOUR_NATURAL_VOICE_ID",
})
```

Set `ELEVENLABS_API_KEY` in the local process environment (recommended), or
supply `elevenlabs_api_key` to `save_tts_settings()`. The key is never passed
to the browser UI or QWebChannel. Saving the provider reconnects into a fresh Live conversation because Gemini's response modality changes. An empty/missing key or voice ID selects Edge TTS.

In this native mode, synthesis occurs after Gemini completes a text response,
so the first spoken audio can start later than Gemini's streamed native audio.
The receiver remains asynchronous during network synthesis. If Privacy Lock or
the PIN gate becomes active, the synthesized response is discarded before it
reaches the speaker queue. A Windows microphone/speaker smoke test is still
required before treating this mode as production-ready.
