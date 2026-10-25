# Smart Hybrid Browser Automation

## Design
This feature is an isolated foundation for browser-vs-chat intent routing. It does not replace the existing Gemini Live audio/session path or security/action dispatcher.

- `core/smart_intent_router.py`: asks the existing HybridLLMRouter with Gemini preferred to classify a request as CHAT or BROWSER. Invalid output/provider errors fail closed to CHAT.
- `core/browser_automation.py`: visible Chromium via Playwright, with only explicit navigate/search/click/read operations. HTTP(S) only; embedded URL credentials and hosts resolving to any private/non-public address are rejected on navigation and routed requests. Following a link navigates its validated href without invoking onclick handlers. Downloads are disabled.
- `core/smart_hybrid_assistant.py`: routes CHAT to the existing hybrid text router and supports explicit browser commands: `search the web for ...`, `open https://...`, and `click ...`.
- `tests/test_smart_hybrid_browser.py`: unit tests with mocked providers/browser plus URL validation.

## Install
Playwright is already listed in `JarvisAI/requirements.txt`. After installing project requirements, install Chromium:
`python -m playwright install chromium`

## Important limits
This first increment is a callable service layer, not yet wired into the Qt dashboard/voice command handler. Call `dispatch` from a worker thread, never an audio callback or GUI thread. It does not automatically submit forms, send messages, purchase items, download files, or execute arbitrary model-generated clicks. For consequential actions, add a confirmation UI before enabling them. Browser page content is untrusted and must not be allowed to override JARVIS system/security instructions.

## Run tests
From `JarvisAI/`:
`python -m unittest discover -s tests -p "test_smart_hybrid_browser.py"`

Full CI and existing voice/audio regressions must pass before merging. This feature requires network access and a configured LLM key for model-based intent routing; the whole system cannot be guaranteed 100% free or always available because provider quotas and terms can change.

DNS checks do not provide network isolation against DNS rebinding between validation and Chromium resolution. Use network isolation when deploying against untrusted sites; this foundation is not an SSRF sandbox.
