# Offline speech-to-text (dictation)

P11 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`. Tool: `dictation`. Module: `jarvis/voice/local_stt.py`.

- Install once: `pip install -r requirements-stt.txt` (faster-whisper). The model downloads once into
  `<data>/models/whisper` and then runs **offline on the CPU** (int8).
- Model: `JARVIS_STT_MODEL` = `small` (default, good on 16 GB RAM), `base` (lighter), `medium` (best accuracy).
- "Dictate" → records until you pause (max 2 minutes) and types the words into the focused app via the clipboard
  (your clipboard is restored). "Stop dictation" ends it early. `type_into_app=false` only returns the text.
- "Transcribe C:\Recordings\meeting.mp3" → text, saved as `meeting.txt` next to it (never overwrites) and listed
  in the file library.
- Gemini Live remains the realtime voice path; this does not change the live audio pipeline.
- Tiers: status/stop SAFE; dictate/transcribe_file SENSITIVE.
