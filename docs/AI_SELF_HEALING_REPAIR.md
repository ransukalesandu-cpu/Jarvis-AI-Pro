# AI Self-Healing & Code Repair — Safety-First Design

## Purpose

Add an optional diagnostic assistant that uses the existing Google Gemini SDK/API configuration to explain Python exceptions and propose a repair. This is not allowed to silently rewrite running application files.

## Required workflow

1. Capture exception type, message, traceback, current Git branch/HEAD, and a small bounded excerpt from relevant source frames.
2. Redact likely secrets (API keys, bearer tokens, passwords, environment values) and limit prompt size before any external API request.
3. Send only the diagnostic context needed to Gemini. Ask for a concise root-cause explanation and a unified diff limited to the named file(s), not an entire replacement repository.
4. Store the suggestion as a reviewable patch under a dedicated diagnostics/repair staging directory. Never apply a model response directly.
5. Validate patch syntax and paths. Reject absolute paths, parent traversal, unexpected file types, oversized patches, edits to secrets/config, dependency lockfiles, CI workflows, or security/auth/audio-critical files unless the user explicitly approves a reviewed patch.
6. Apply only after explicit user approval, on a dedicated repair branch or isolated Git worktree. Never use `git reset --hard`, `git checkout -- .`, or destructive commands to discard user work.
7. Run safe checks in a subprocess with timeouts: compile changed Python files, then targeted tests, then the relevant test suite. Do not run model-generated shell commands.
8. If checks fail, keep the patch isolated and report the failure. Offer a revert of only the repair commit/branch after confirming no user changes would be lost. Do not automatically overwrite the working tree.
9. Record an audit log: timestamp, error summary, model name, proposed files, patch hash, approval decision, and test results. Never log API keys or full secret-bearing environment variables.
10. Add rate limits/cooldowns and a manual disable switch so repeated errors cannot trigger an API loop or incur unexpected usage.

## Git safety rules

- If the worktree is clean, create a dedicated branch and a checkpoint commit only when there are staged, reviewed changes to checkpoint; do not create meaningless empty commits.
- If the worktree is dirty, do not stash, reset, or switch branches automatically. Ask the user to commit/stash manually or use a separate worktree based on a known commit.
- Keep repairs in a branch/PR. Never push directly to `main` or auto-merge.
- Rollback must target the specific repair commit, only after inspecting the diff and confirming it is safe to revert.

## Gemini behavior

- Use the repository's existing `google-genai` dependency and existing secure API-key loading pattern; do not introduce a second SDK or hard-code credentials.
- Use a configurable supported model name; handle quota, network, and unavailable-model errors gracefully.
- The model output is untrusted. Treat it as a suggestion, not executable authority.
- Do not upload entire files by default. Send a bounded relevant snippet and redacted traceback.
- Never send secrets, private user data, tokens, or complete environment/config files.

## UI / integration

- Keep diagnostics off the audio callback and real-time voice receive path. API requests and tests must run in a background worker.
- Add a setting for enable/disable and a button/action to “Analyze error” / “Prepare repair suggestion”.
- Show the diagnosis, affected files, patch preview, validation/test results, and an explicit Apply/Reject choice.
- Keep existing JARVIS audio, wake-word, UI, and assistant behavior unchanged when disabled.
- Add a clear status when the free API quota is exhausted; do not silently retry in a loop.

## Acceptance criteria

- No file changes occur without explicit user approval.
- No destructive Git operation is run automatically.
- Secrets are redacted before Gemini calls and are never written to logs.
- Malformed or unsafe patches are rejected.
- Model output cannot execute commands or arbitrary Python.
- Compile/test commands have timeouts and run only on an isolated repair branch/worktree.
- Unit tests cover redaction, path traversal rejection, patch-size limits, API failures, and rollback safety.
- Existing test suite and audio/wake-word regression tests pass.
- Implementation is delivered as a separate PR and is not auto-merged.
