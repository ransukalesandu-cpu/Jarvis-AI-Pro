"""Measure draw calls and triangles per quality profile and face style, and fail over budget.

    python frontend/scripts/check_budget.py      (needs: npm ci, pip install playwright, playwright install chromium)

Starts the Vite dev server (the dev-only `__jarvisUi` hook sets the tier), renders each profile in
headless Chromium and reads the numbers the hologram measures itself (Performance overlay). Draw
calls and triangles do not depend on the GPU, so SwiftShader is fine for this; FPS is not checked.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import time
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent
PORT = 5181
# Budgets per profile. Measured 2026-11-22: circuit 54/52 draws (35k tris), mechanical 80/78 draws (49k tris).
BUDGET = {"full": 90, "balanced": 90, "lite": 85}
TRIANGLES = {"full": 60_000, "balanced": 60_000, "lite": 60_000}


async def read(page) -> tuple[int, int] | None:
    text = await page.inner_text(".perf-overlay")
    d, t = re.search(r"Draws\s+(\d+)", text), re.search(r"Tris\s+([\d.]+)k", text)
    return (int(d.group(1)), round(float(t.group(1)) * 1000)) if d and t else None


async def stable(page) -> tuple[int, int]:
    """The overlay publishes once a second from the previous frame, and a new face style first
    compiles its shaders: wait, then require three equal reads in a row."""
    await page.wait_for_timeout(6000)
    seen: list[tuple[int, int] | None] = []
    for _ in range(20):
        seen.append(await read(page))
        if len(seen) >= 3 and seen[-1] is not None and seen[-1] == seen[-2] == seen[-3]:
            return seen[-1]
        await page.wait_for_timeout(1200)
    raise RuntimeError("overlay numbers never settled")


async def measure() -> list[tuple[str, str, int, int]]:
    from playwright.async_api import async_playwright
    rows = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(f"http://localhost:{PORT}/?budget")
        await page.wait_for_function("globalThis.__jarvisUi !== undefined", timeout=30000)
        for style in ("brain", "circuit", "mechanical"):
            for tier in ("full", "balanced", "lite"):
                centre = "brain" if style == "brain" else "hologram"
                face = "circuit" if style == "brain" else style
                await page.evaluate(f"globalThis.__jarvisUi.setState({{centerStyle:'{centre}', faceStyle:'{face}', perfTier:'{tier}', perfOverlay:true, assistant:'thinking'}})")
                rows.append((style, tier, *await stable(page)))
        await browser.close()
    return rows


def main() -> int:
    vite = FRONTEND / "node_modules" / ".bin" / ("vite.cmd" if sys.platform == "win32" else "vite")
    server = subprocess.Popen([str(vite), "--port", str(PORT), "--strictPort"], cwd=FRONTEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(4)
        rows = asyncio.run(measure())
    finally:
        server.terminate()
    bad = 0
    for style, tier, draws, tris in rows:
        over = draws > BUDGET[tier] or tris > TRIANGLES[tier]
        bad += over
        print(f"{style:10} {tier:8} draws {draws:4} (<= {BUDGET[tier]})  triangles {tris:6} (<= {TRIANGLES[tier]})  {'OVER' if over else 'ok'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
