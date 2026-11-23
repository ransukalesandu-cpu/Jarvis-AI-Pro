# Routines file (one phrase → many actions)

Voice-saved routines ("save this as work mode") record what JARVIS just did. The routines file is the
hand-written version: you list the steps and the phrases that start them.

Create `%LOCALAPPDATA%\jarvis\routines.yaml` (needs `pip install pyyaml`) or `routines.json`:

```yaml
morning:
  description: Start the day
  phrases: ["good morning", "morning mode"]
  steps:
    - {tool: open_app, args: {app_name: Outlook}}
    - {tool: phone_control, args: {action: mute_volume}}
    - {tool: weather_report, args: {}}
work mode:
  phrases: ["let's work"]
  steps:
    - {tool: open_app, args: {app_name: Visual Studio Code}}
    - {tool: spotify_control, args: {action: play, query: focus}}
```

- Saying or typing a phrase **exactly** ("Good morning", "Jarvis, good morning") starts the routine; so do
  "start work mode" / "run morning routine". A sentence that only mentions the phrase does not.
- Each step runs through the normal tool layer: the same security tiers, confirmations, action log and stop word.
- Works with Gemini Live and in the offline voice loop.
- JARVIS can list, show and run these, but never edits the file. Problems in the file are shown by
  "list my routines".
- Tool names and arguments are the same as in the action log ("show recent actions").
