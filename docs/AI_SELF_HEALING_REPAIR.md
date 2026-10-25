# AI Self-Healing & Code Repair — Safety-First Design

## Purpose
Add an optional diagnostic assistant for Python exceptions. The repair analyzer must use the existing hybrid text router with **Groq as the preferred provider**, while retaining the router's configured fallback behavior for provider/quota/network failures.

## Implemented foundation
- `core/ai_error_repair.py` calls `HybridLLMRouter(preferred_provider="groq")`.
- Reads configured provider keys from the existing local `config/api_keys.json`; environment-based key lookup remains handled by the router.
- Redacts common secret patterns and bounds traceback/source size before sending diagnostic context.
- Excludes common credential files and oversized files from source context.
- Requests a concise diagnosis and a minimal unified diff proposal.
- Returns `applied: false` and `requires_review: true`; it does not write source files, execute model output, run shell commands, or change Git state.
- `JARVIS_REPAIR_GROQ_MODEL` can override the default Groq model name.

## Safety boundary
This is a diagnostic/proposal foundation, not fully automatic self-healing yet. It is not connected to a global exception hook or approval UI. Do not apply model output directly. Future integration must show a patch preview, require explicit owner approval, validate paths and patch size, apply in an isolated repair branch/worktree, and run bounded syntax/tests before offering a specific safe revert. Never auto-merge, push to main, run model-provided shell commands, or perform destructive automatic Git resets.

## Validation
Unit tests cover Groq-first routing, secret redaction, prompt bounds, and the non-auto-apply contract. Run from `JarvisAI/` with `python -m unittest discover -s tests -p "test_ai_error_repair.py"`. Full project CI/audio regression validation is still required before merge.
