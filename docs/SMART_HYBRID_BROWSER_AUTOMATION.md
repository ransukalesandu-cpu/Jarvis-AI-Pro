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

## Agent integration (Part 2)
The autonomous task engine now exposes four typed browser steps to its existing model planner and voice/HUD task workflow:

- `browser_search`: search the public web for a bounded query.
- `browser_navigate`: open an absolute public HTTP(S) URL.
- `browser_read`: read the current page's visible text.
- `browser_follow_link`: follow a visible link by its accessible name.

The agent runs these steps in its background worker, not the Qt or audio callback thread. Every task still passes the existing Owner Authentication, Privacy Lock, per-step authorization recheck, task limits, and network policy. Browser output is labelled untrusted evidence. A separate visible Chromium context is used; JARVIS does not reuse personal browser profiles or cookies.

## Important limits
Browser automation is deliberately read-only in this increment. It cannot submit forms, click buttons, log in, send messages, purchase items, download files, or execute page scripts. Link following reads the link's href and navigates directly rather than invoking page click handlers. Consequential browser actions must be implemented as separate typed operations and remain behind the existing explicit approval gate; do not weaken the shared security layer.

DNS validation blocks localhost, private, link-local, and other non-public destinations, including routed requests. DNS rebinding between validation and browser resolution remains a documented limitation; this module is not a network sandbox. Use OS/container network isolation for stronger protection when browsing untrusted destinations.

## Run tests
From `JarvisAI/`:
`python -m unittest discover -s tests -p "test_smart_hybrid_browser.py"`

Full CI and existing voice/audio regressions must pass before merging. This feature requires network access and a configured LLM key for model-based intent routing; the whole system cannot be guaranteed 100% free or always available because provider quotas and terms can change.

DNS checks do not provide network isolation against DNS rebinding between validation and Chromium resolution. Use network isolation when deploying against untrusted sites; this foundation is not an SSRF sandbox.
