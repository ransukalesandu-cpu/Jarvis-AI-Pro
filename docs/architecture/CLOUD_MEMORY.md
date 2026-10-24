# Jarvis AI Pro — Cloud Memory & Database Architecture

**Status:** Proposed architecture decision; implementation is not yet enabled.

## Goal

Keep Jarvis AI Pro's application core and computer-control capabilities on the user's PC, while storing long-term user memory and conversation context in a managed cloud database. Do not require a local SQLite/JSON database or a locally hosted heavy database service for persistent memory.

## Architecture

- **Local Jarvis Core:** Voice and audio pipeline, hologram/UI, PC and file actions, local AuthManager, ActionDispatcher, and Privacy Lock remain local and authoritative.
- **Memory Client:** A small local module communicates with the managed database over authenticated HTTPS. It should not expose database credentials in the client.
- **Managed Cloud Database:** Stores user-approved memory items, preferences, summaries, and conversation metadata/history as configured. Choose the provider and schema before implementation.
- **AI Context Builder:** Retrieves only the relevant memory needed for a request, limits context size, and passes it to the selected AI provider only when needed and permitted.
- **Optional AI API:** The database and AI model provider are separate choices. No Render/Railway custom backend is required solely to store memory if the selected managed database supports secure client access policies.

## Memory behavior

1. Save useful long-term facts and preferences separately from raw conversation history.
2. Keep recent conversation context bounded; summarize older conversations instead of sending the entire history on every request.
3. Support reading, updating, exporting, and deleting the user's saved memory.
4. Allow memory to be disabled and provide a clear offline/unavailable fallback when the internet or cloud database is unavailable.
5. Avoid storing duplicate or unnecessary information; define retention limits for raw chat history.

## Security and privacy requirements

- Use per-user authentication and strict row-level access policies so one user cannot read another user's data.
- Keep service-role/admin secrets on a trusted server or provider secret store; never commit secrets to GitHub or embed privileged keys in the desktop client.
- Use HTTPS in transit and provider-supported encryption at rest.
- Never store owner PINs/passwords, API keys, raw voice biometrics, or authentication tokens as memory.
- Do not upload local file contents, private documents, or microphone recordings by default. Retrieve local files only through the local security/action gate and send minimal content only with explicit permission.
- Cloud AI output must never bypass local AuthManager, ActionDispatcher, privileged-action confirmations, or Privacy Lock.
- Treat database content as untrusted input; it must not be allowed to inject instructions that override system/security policy.

## Failure and offline behavior

- Cloud-memory errors/timeouts must not crash voice interaction or local PC controls.
- Use short timeouts, bounded retries, and a clear indication when memory could not be fetched/saved.
- Do not silently claim that a memory was saved when the cloud write failed.
- Local security and permitted local actions continue to work without the cloud database; cloud-only memory features may be unavailable offline.
- Do not create a local persistent SQLite/JSON fallback unless the architecture is explicitly revised. Temporary in-memory context is acceptable.

## Implementation outline

1. Select a managed database/provider with a suitable free tier, authentication, access policies, and backup/export options.
2. Define a minimal schema for user preferences, durable memory items, conversation summaries, and optional conversation history.
3. Add a provider-neutral memory interface (for example, MemoryStore) and a managed-database adapter.
4. Add authenticated CRUD operations, access-policy tests, retention/deletion controls, and failure/offline tests.
5. Integrate memory retrieval into context building without changing the existing Gemini Live voice path initially.
6. Run CI/regression tests and verify cloud access rules before enabling it for real user data.

## Not in scope yet

- No cloud database provider has been selected.
- No database project, schema, credentials, or production data has been created.
- No runtime code has been changed by this architecture document.
- Render, Railway, and Hugging Face Spaces are not required by this decision.
