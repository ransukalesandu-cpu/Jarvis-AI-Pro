# ADR-0001: Web UI library choices against the next-generation UI prompt

- Status: accepted
- Date: 2026-11-23

## Context

The master UI prompt lists a preferred stack (Tailwind, Radix, shadcn/ui, GSAP, TanStack Query, Apache ECharts,
ESLint/Prettier, Playwright) but also says not to install libraries blindly and to check bundle size and whether each
one is needed. The web UI already ships a working React 19 + TypeScript + Vite + Zustand + React Three Fiber stack.

## Decision

| Library | Decision | Why |
| --- | --- | --- |
| React Three Fiber | Keep | Already the single scene manager; one render loop; disposal on unmount. No raw-Three.js second loop. |
| Tailwind / shadcn/ui | Not added | CSS custom properties in `styles/tokens.css` already give one theme source; rewriting every component's classes would be churn with no user-visible gain. |
| Radix UI | Not added now | Panels, toggles and the palette (`cmdk`) are already keyboard-reachable; add a Radix primitive only where a component needs it (e.g. a future menu or dialog). |
| GSAP | Not added | Motion covers UI transitions and the hologram eases inside `useFrame`; a second animation system on the same objects is what the prompt says to avoid. |
| TanStack Query | Not added | The bridge is push-based (host events into Zustand); there are no request/response fetches to cache. |
| Apache ECharts | Not added | Charts are small real-time sparklines (`ui/Spark.tsx`, SVG). ECharts would add ~1 MB to a page that runs next to the voice pipeline. Revisit if a page needs zooming, legends or long history. |
| WebGPU | Not used | WebGL 2 is the baseline in Qt WebEngine; the no-WebGL path is the classic HUD plus the renderer notice. |
| ESLint / Prettier / Playwright | Not yet | `tsc --strict`, Vitest and `webui-checks.yml` gate CI today. Playwright against QWebEngine is covered by `python -m jarvis.webui.selfcheck` instead. |

## Consequences

The bundle stays at about 1.6 MB raw (460 kB gzip) and loads from disk. Any of the libraries above can be added later
for a concrete need; this record should be updated when that happens.
