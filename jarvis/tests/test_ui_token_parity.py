"""UI P1 token parity: web CSS, Qt tokens.py and QSS all come from frontend/tokens/core.json.

The colour maths is re-implemented here independently of the JS build, so a bug in either side shows up.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = json.loads((ROOT / "frontend" / "tokens" / "core.json").read_text(encoding="utf-8"))
CSS = (ROOT / "frontend" / "src" / "styles" / "tokens.css").read_text(encoding="utf-8")
THEME_DIR = ROOT / "jarvis" / "ui" / "theme"
THEMES = ("dark", "light", "hc")


def _load_tokens_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ui_theme_tokens", THEME_DIR / "tokens.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # loaded by path: no PyQt import through jarvis.ui
    return mod


TOK = _load_tokens_module()


def parse(value: str):
    v = value.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3,8})", v)
    if m:
        h = m.group(1)
        if len(h) <= 4:
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return r, g, b, (int(h[6:8], 16) / 255 if len(h) == 8 else 1.0)
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", v)
    assert m, v
    return float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4) or 1)


def oklch(r, g, b):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    R, G, B = lin(r), lin(g), lin(b)
    l_ = (0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B) ** (1 / 3)
    m_ = (0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B) ** (1 / 3)
    s_ = (0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    A = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    Bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    C = math.hypot(A, Bb)
    H = math.degrees(math.atan2(Bb, A)) % 360
    return L, C, (0.0 if C < 1e-4 else H)


def expected(theme: str) -> dict[str, dict]:
    out = dict(CORE["base"])
    out.update(CORE["themes"]["dark"])
    if theme != "dark":
        out.update(CORE["themes"][theme])
    return out


def css_block(selector: str) -> dict[str, str]:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, selector
    return dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", m.group(1)))


SELECTORS = {"dark": ":root", "light": ":root[data-theme='light']", "hc": ":root[data-theme='hc']"}


@pytest.mark.parametrize("theme", THEMES)
def test_qt_tokens_match_core(theme):
    exp = expected(theme)
    got = TOK.THEMES[theme]
    assert set(got) == set(exp)
    for name, tok in exp.items():
        if tok["$type"] != "color":
            assert got[name] == str(tok["$value"]), name
            continue
        r, g, b, a = parse(tok["$value"])
        q = parse(got[name])
        assert q[:3] == pytest.approx((r, g, b), abs=0.51), name
        qa = q[3] / 255 if got[name].startswith("rgba") else q[3]
        assert qa == pytest.approx(a, abs=1 / 255), name


@pytest.mark.parametrize("theme", THEMES)
def test_css_colours_match_core_in_oklch(theme):
    block = css_block(SELECTORS[theme])
    exp = expected(theme)
    names = exp if theme == "dark" else CORE["themes"][theme]
    names = [n for n in names if not n.startswith("stage-")]     # 3D-only colours live in tokens.ts
    assert set(names) <= set(block)
    for name in names:
        tok = exp[name]
        if tok["$type"] != "color":
            continue
        r, g, b, a = parse(tok["$value"])
        m = re.fullmatch(r"oklch\(([\d.]+)% ([\d.]+) ([\d.]+)(?: / ([\d.]+))?\)", block[name])
        assert m, (name, block[name])
        L, C, H = oklch(r, g, b)
        assert float(m.group(1)) == pytest.approx(L * 100, abs=0.02), name
        assert float(m.group(2)) == pytest.approx(C, abs=2e-4), name
        if C > 0.002:
            assert float(m.group(3)) == pytest.approx(H, abs=0.05), name
        assert float(m.group(4) or 1) == pytest.approx(a, abs=1e-3), name
        assert TOK.OKLCH[theme][name] == block[name]


def test_stage_colours_reach_the_3d_tokens():
    ts = (ROOT / "frontend" / "src" / "styles" / "tokens.ts").read_text(encoding="utf-8")
    for name, tok in CORE["base"].items():
        if name.startswith("stage-"):
            r, g, b, _ = parse(tok["$value"])
            assert f"'{name}': {{ hex: 0x{int(r):02x}{int(g):02x}{int(b):02x}," in ts, name


def test_high_contrast_follows_the_os_setting():
    assert "@media (prefers-contrast: more)" in CSS


@pytest.mark.parametrize("theme", THEMES)
def test_qss_is_complete(theme):
    path = THEME_DIR / ("jarvis.qss" if theme == "dark" else f"jarvis.{theme}.qss")
    qss = path.read_text(encoding="utf-8")
    assert "{{" not in qss
    assert TOK.THEMES[theme]["bg"] in qss and TOK.THEMES[theme]["text"] in qss
    assert len(qss.splitlines()) <= 400      # P8 budget
