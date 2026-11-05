# Roadmap

Updated by every task. Each task: Gate A (plan PR) → owner approval → Gate B (implement) → Gate C (verify, report).

| # | Task | Status |
|---|------|--------|
| 1 | Automation: cron + run history, lifecycle hooks, webhooks | Gate A approved. A1 (cron + history) in progress; A2 hooks next; A3 webhooks deferred |
| 2 | Unified skills registry (`SKILL.md`) + MCP client | not started |
| 3 | Browser snapshot / ref interaction | not started |
| 4 | Standing orders, sub-agents, resumable workflows | not started |
| 5 | Memory upgrade (Supabase + pgvector) | not started |
| 6 | Brain/router and agent-engine hardening | not started |
| 7 | Voice reliability, device nodes | not started |
| 8 | Chat/UX polish, research system, self-eval | not started |

Done so far: `jarvis/` package restructure, dead-code removal, PRs #224 #225 #228 merged.
Next exact action: finish PR A1 (cron expr, run history, run-now, task mode).
