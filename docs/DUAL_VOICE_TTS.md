# ElevenLabs Dual Voice

The desktop TTS engine supports an optional `dual` provider mode. It uses two
separately configured ElevenLabs voice IDs and one voice per complete utterance.

## Configuration

Pass these keys through the existing application settings/config loader (or
provide the API key as an environment variable):

- `tts_engine`: `dual`
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
