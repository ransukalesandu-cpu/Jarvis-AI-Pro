# Adaptive Memory & Personalization

## Components
- `core/adaptive_memory.py`: local SQLite store, disabled by default, allow-listed low-risk categories, explicit confirmation per saved item, list/delete/clear controls. Raw conversations are not stored.
- `core/behavior_extraction.py`: uses the existing `HybridLLMRouter` with Gemini preferred to propose short facts from an individual message. Output is schema-validated and filtered. Extracted candidates are suggestions only; they are never auto-saved. Transient tone hints are returned separately and not persisted.
- `core/dynamic_prompt.py`: builds per-turn instructions from the base system prompt, ephemeral tone hint, and only user-confirmed memories. Current user instructions take precedence over stored preferences.

## Privacy defaults
- Memory is OFF by default and must be enabled explicitly.
- Do not store raw chats, secret strings, diagnoses, protected/sensitive traits, or long-term mood profiles.
- Emotion/tone interpretation is tentative and per-turn only; it is not a clinical assessment.
- User can list, delete individual memories, clear all memories, or disable memory.
- SQLite database path defaults to `~/.jarvis/memory.sqlite3`; set `JARVIS_MEMORY_DB` to override it.

## Usage sketch
```python
store = MemoryStore()
store.set_enabled(True)  # only after user opts in
engine = BehaviorExtractionEngine(store)
extracted = engine.extract_candidates(user_message)
# Show extracted["candidates"] to the user and save only facts they confirm:
# store.confirm_memory(candidate["category"], candidate["value"], candidate["confidence"])
prompt = DynamicPromptBuilder(store).build(base_system_prompt, extracted["tone_hint"])
response = existing_router.query(user_message, system_prompt=prompt)
```

## Scope
This is a callable foundation; it is not yet wired into JARVIS's Qt settings, voice command path, or every text/Live prompt. The default store is local SQLite; Supabase sync is not enabled. Before enabling cloud sync, add explicit opt-in, RLS, retention, and deletion synchronization. Run the unit tests and full audio/wake-word regression suite before merge.
