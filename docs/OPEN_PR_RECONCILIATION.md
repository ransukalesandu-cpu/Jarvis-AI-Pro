# Open PR reconciliation

PR #86 consolidates the fixes and compatible remaining integrations. At the user’s request to merge all passing work, it also reconciles the histories of PRs #68, #72, #74, #75, #76, #78, #79, #80, #82, #83, #84 and #85. Their heads are recorded as merge parents while retaining the validated consolidated implementation described below. This resolves overlapping implementations and conflicts without reintroducing their historical failures or weaker voice authorization. Original branch histories are preserved.

| Original PR | Consolidated result |
| --- | --- |
| #68 | Current main already contains the safe PyQt/audio port from #73; retain its later audio and GUI fixes. |
| #72 | Android action foundation included; ADB fixture uses actual newline/tab separators; normalize null optional parameters and recognize activity launch errors. |
| #74 | Retain main's newer portrait/viseme renderer; add the appearance settings and reduced-motion controls through that renderer. |
| #75, #78 | Add local first-run owner PIN enrollment and reachable adaptive PIN fallback. Preserve current provider setup and post-cooldown Privacy Lock. Per the user's explicit security decision, speaker matches alone never grant access: require live speech and anti-spoof validation, with local PIN fallback. |
| #76 | Add mode selector, supported female voice preferences, persisted settings and appearance controls. Keep the separate JARVIS voice choice intact when switching back. Both HUDs share assistant-mode configuration. |
| #79, #80 | Retain the current optional HUD/portrait implementation and architecture document; preserve its existing viseme API. |
| #82 | Repair secret redaction and prompt contract; extend exclusion to environment/private-key source files, cover camelCase secrets and authorization schemes, and preserve the final exception when truncating tracebacks. |
| #83 | Repair Python syntax and restrict following links to their validated HTTP(S) href; avoid arbitrary element clicks and onclick side effects, and reject private DNS results/legacy loopback forms. |
| #84 | Include opt-in memory foundation; reuse credential redaction for quoted secrets before extraction. Extracted candidates still require user confirmation and are never automatically persisted. |
| #85 | Project feature landmarks in the fitted portrait rectangle, preserve the 82-node API, and add surface triangles across features. Isolate test preferences; keep both visualizers locked across audio-state updates and restore state after unlock. |

## Security contract change

Earlier owner-role tests and documentation allowed similarity-based voice authorization. The user explicitly selected the stricter rule: owner voice access and spoken confirmations require both an enrolled owner match and validated live-speech anti-spoof verification. The acoustic quality heuristic is not sufficient. There is no default anti-spoof detector; unavailable or failing checks deny voice authorization and use the local PIN/manual HUD path. PIN sessions and the existing Privacy Lock guarantees are preserved.

## Verification scope

Automated checks cover synthetic/mocked providers, ADB, anti-spoof decisions, local PIN hashing, opt-in memory, mode/voice restoration, Qt settings isolation, and offscreen mesh rendering. Physical devices and live provider/browser operations require separate device/service verification.
