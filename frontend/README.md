# JARVIS web UI (frontend)

React 19 + TypeScript + Vite + React Three Fiber, rendered inside `QWebEngineView` by `jarvis/webui`.

```
npm install
npm run dev      # browser preview; no backend, so the link stays "detached" and no data is shown
npm test         # vitest
npm run build    # tsc + vite build -> ../jarvis/webui/dist (committed; Windows users never need Node)
```

Preview inside the real host (Python + QWebChannel + real telemetry): `python -m jarvis.webui`.
Regenerate the head mesh from the legacy renderer: `python scripts/export_head_mesh.py`.

The page talks to Python only through `src/bridge/contract.ts` (mirrored in `jarvis/webui/contract.py`).
Nothing is mocked in production code: a value without a backend source shows `--` or "not reported".
