"""Compile every hologram shader in a real WebGL2 context (headless Chromium).

    python frontend/scripts/check_shaders.py          (needs: npm ci, pip install playwright, playwright install chromium)

Bundles scripts/shader-check.entry.ts with rolldown (already a Vite dependency), opens it in headless
Chromium (SwiftShader WebGL2) and fails if any material does not compile or link.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent


def bundle(out: Path) -> None:
    rolldown = FRONTEND / "node_modules" / ".bin" / ("rolldown.cmd" if sys.platform == "win32" else "rolldown")
    subprocess.run([str(rolldown), str(HERE / "shader-check.entry.ts"), "--format", "iife", "--platform", "browser",
                    "--file", str(out)], check=True, cwd=FRONTEND, stdout=subprocess.DEVNULL)


async def run(js: Path) -> dict:
    from playwright.async_api import async_playwright
    html = js.with_suffix(".html")
    html.write_text(f"<!doctype html><script src='{js.name}'></script>", encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
        page = await browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(html.as_uri())
        await page.wait_for_function("window.__shaderCheck !== undefined", timeout=20000)
        result = await page.evaluate("window.__shaderCheck")
        await browser.close()
    result["pageErrors"] = errors
    return result


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        js = Path(d) / "shader-check.js"
        bundle(js)
        result = asyncio.run(run(js))
    print(json.dumps(result, indent=2))
    bad = [r for r in result["results"] if not r["ok"]] or result["pageErrors"]
    print("FAILED" if bad else f"OK: {len(result['results'])} materials compiled, {len(result['chunks'])} chunks")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
