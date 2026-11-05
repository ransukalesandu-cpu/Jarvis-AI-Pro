"""Self-check for the web UI on *this* machine: ``python -m jarvis.webui.selfcheck``.

Opens the web UI in a real window for a few seconds and reports, in plain words, whether the things that cannot be
tested in CI work here: the page loaded and the backend link came up, live data is arriving, WebGL is available and
whether it is hardware or software rendering, and how smoothly the page animates. It reads nothing private and
sends nothing anywhere; the report is printed and saved as ``webui_selfcheck.txt`` in the current folder.

Exit code: 0 when nothing FAILED (warnings are allowed), 1 otherwise, 2 when the UI bundle is missing.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

SOFTWARE_RENDERERS = ("swiftshader", "llvmpipe", "softpipe", "microsoft basic render", "software")


@dataclass
class Facts:
    dist_ready: bool = False
    hello: bool = False               # page connected and host.hello was sent
    webgl: str | None = None          # None = no WebGL, otherwise "webgl2" / "webgl"
    renderer: str = ""
    canvas_ok: bool = False
    live_data: bool = False           # a CPU reading is on screen
    fps: float | None = None          # page animation frames per second, measured over ~2 s


def evaluate(f: Facts) -> list[tuple[str, str, str]]:
    """(level, check, plain-words detail) with level PASS / WARN / FAIL."""
    out: list[tuple[str, str, str]] = []
    add = lambda lvl, name, detail: out.append((lvl, name, detail))  # noqa: E731
    add("PASS" if f.dist_ready else "FAIL", "UI bundle", "found" if f.dist_ready else "jarvis/webui/dist is missing; build it with: cd frontend && npm install && npm run build")
    add("PASS" if f.hello else "FAIL", "Backend link", "the page connected to Python" if f.hello else "the page never connected; the classic HUD would be used instead")
    add("PASS" if f.live_data else "WARN", "Live data", "CPU/RAM readings are arriving" if f.live_data else "no readings seen yet (try a longer --seconds)")
    if f.webgl is None:
        add("FAIL", "WebGL", "not available: the hologram cannot draw; the classic HUD is the right choice on this machine")
    else:
        software = any(s in f.renderer.lower() for s in SOFTWARE_RENDERERS)
        detail = f"{f.webgl}, renderer: {f.renderer or 'unknown'}"
        add("WARN" if software else "PASS", "WebGL", detail + (" (SOFTWARE rendering: it will work but be slow; check your graphics driver)" if software else ""))
    add("PASS" if f.canvas_ok else "FAIL", "Hologram canvas", "present and sized" if f.canvas_ok else "the hologram canvas is missing or has no size")
    if f.fps is None:
        add("WARN", "Smoothness", "could not be measured")
    elif f.fps >= 45:
        add("PASS", "Smoothness", f"{f.fps:.0f} frames per second")
    elif f.fps >= 20:
        add("WARN", "Smoothness", f"{f.fps:.0f} frames per second (usable; the Performance tier can be lowered in Settings)")
    else:
        add("FAIL", "Smoothness", f"{f.fps:.0f} frames per second: too slow for the web UI on this machine")
    return out


def render(results: list[tuple[str, str, str]]) -> str:
    lines = [f"[{lvl}] {name}: {detail}" for lvl, name, detail in results]
    fails = sum(1 for r in results if r[0] == "FAIL")
    warns = sum(1 for r in results if r[0] == "WARN")
    lines.append("")
    lines.append("RESULT: " + ("OK" if fails == 0 and warns == 0 else "OK with warnings" if fails == 0 else "NOT READY") + f" ({fails} failed, {warns} warnings)")
    return "\n".join(lines)


_PROBE_JS = """
(() => {
  const out = {webgl: null, renderer: '', canvas: false, live: false};
  try {
    const c = document.createElement('canvas');
    let gl = c.getContext('webgl2'); out.webgl = gl ? 'webgl2' : null;
    if (!gl) { gl = c.getContext('webgl'); out.webgl = gl ? 'webgl' : null; }
    if (gl) { const e = gl.getExtension('WEBGL_debug_renderer_info'); out.renderer = String(e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)); }
  } catch (e) { out.webgl = null; }
  const stage = document.querySelector('.stage canvas');
  out.canvas = !!stage && stage.clientWidth > 50 && stage.clientHeight > 50;
  out.live = /CPU\\s*\\d+%/.test(document.body.textContent);
  return JSON.stringify(out);
})()
"""
# Qt's runJavaScript does not wait for a Promise, so the measurement runs in the page and is read back afterwards.
_FPS_START_JS = "window.__fps = null; (() => { let n = 0; const t0 = performance.now(); const f = () => { n++; const dt = performance.now() - t0; if (dt < 2000) requestAnimationFrame(f); else window.__fps = n / (dt / 1000); }; requestAnimationFrame(f); })(); true"
_FPS_READ_JS = "window.__fps"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(prog="python -m jarvis.webui.selfcheck")
    ap.add_argument("--seconds", type=float, default=8.0, help="how long to let the page settle before measuring")
    ap.add_argument("--no-report", action="store_true", help="do not write webui_selfcheck.txt")
    args = ap.parse_args(argv)

    from . import dist_ready

    facts = Facts(dist_ready=dist_ready())
    if not facts.dist_ready:
        print(render(evaluate(facts)))
        return 2
    from PyQt6.QtCore import QCoreApplication, Qt, QTimer

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    from PyQt6 import QtWebEngineWidgets  # noqa: F401  (must be imported before QApplication)
    from PyQt6.QtWidgets import QApplication

    from .host import WebUIHost

    app = QApplication(sys.argv)
    import tempfile
    from pathlib import Path

    scratch = tempfile.TemporaryDirectory(prefix="jarvis_selfcheck_")      # never touch the real saved layouts
    w = WebUIHost(workspace_path=Path(scratch.name) / "workspaces.json")
    w.setWindowTitle("JARVIS web UI self-check")
    w.resize(1280, 800)
    w.ready.connect(lambda: setattr(facts, "hello", True))
    w.show()
    page = w._page

    def probe() -> None:
        def got(raw):
            try:
                d = json.loads(raw)
            except (TypeError, ValueError):
                d = {}
            facts.webgl, facts.renderer = d.get("webgl"), str(d.get("renderer") or "")
            facts.canvas_ok, facts.live_data = bool(d.get("canvas")), bool(d.get("live"))
            page.runJavaScript(_FPS_START_JS)
            QTimer.singleShot(2600, lambda: page.runJavaScript(_FPS_READ_JS, got_fps))

        def got_fps(v):
            facts.fps = float(v) if isinstance(v, (int, float)) else None
            finish()
        page.runJavaScript(_PROBE_JS, got)

    def finish() -> None:
        results = evaluate(facts)
        text = render(results)
        print(text)
        if not args.no_report:
            try:
                with open("webui_selfcheck.txt", "w", encoding="utf-8") as fh:
                    fh.write(text + "\n")
                print("\n(saved as webui_selfcheck.txt)")
            except OSError as exc:
                print(f"\n(could not save the report: {exc})")
        app.setProperty("exit_code", 1 if any(r[0] == "FAIL" for r in results) else 0)
        app.quit()

    QTimer.singleShot(int(args.seconds * 1000), probe)
    QTimer.singleShot(int((args.seconds + 30) * 1000), lambda: (print("[FAIL] Self-check timed out"), app.setProperty("exit_code", 1), app.quit()))
    app.exec()
    w.shutdown()
    scratch.cleanup()
    return int(app.property("exit_code") or 0)


if __name__ == "__main__":
    sys.exit(main())
