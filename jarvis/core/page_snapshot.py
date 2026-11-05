"""Page snapshots with element refs: see a web page as a short list, act on it by ref.

``take_snapshot`` lists the visible interactive elements of the current page as
``[e12] button "Search"`` lines and stamps each element with a ``data-jarvis-ref``
attribute. ``click_ref`` / ``type_ref`` / ``select_ref`` then act on the element
by that ref, so the model never has to guess a CSS selector, and each action
reports what actually changed (URL, title, the field's value) so a missed click is
noticed instead of assumed.

Refs belong to one snapshot of one page: after navigation, or when the page
re-renders and the element is gone, the action refuses and asks for a new
snapshot instead of clicking something else. Element names are page text and
therefore untrusted; callers wrap the snapshot with ``injection_guard``. Password
values are never read. Frames and shadow DOM are not covered yet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_ELEMENTS = 150
MAX_NAME = 80
MAX_HREF = 80
REF_RE = re.compile(r"^e[1-9][0-9]{0,3}$")

SNAPSHOT_JS = """
([maxElements, maxName, maxHref]) => {
  const SELECTOR = [
    'a[href]', 'button', 'input:not([type=hidden])', 'select', 'textarea', 'summary',
    '[role=button]', '[role=link]', '[role=checkbox]', '[role=radio]', '[role=tab]',
    '[role=menuitem]', '[role=switch]', '[role=combobox]', '[role=textbox]',
    '[role=searchbox]', '[role=option]', '[contenteditable=""]', '[contenteditable=true]',
    '[onclick]', '[tabindex]:not([tabindex="-1"])'
  ].join(',');
  document.querySelectorAll('[data-jarvis-ref]').forEach(e => e.removeAttribute('data-jarvis-ref'));
  const clean = (t) => (t || '').replace(/\\s+/g, ' ').trim();
  const visible = (el) => {
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const nameOf = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return clean(aria);
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\\s+/).map(id => document.getElementById(id)).filter(Boolean)
        .map(n => n.textContent).join(' ');
      if (clean(t)) return clean(t);
    }
    if (el.id) {
      const lab = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (lab && clean(lab.textContent)) return clean(lab.textContent);
    }
    const wrap = el.closest('label');
    if (wrap && clean(wrap.textContent) && el.tagName !== 'BUTTON') return clean(wrap.textContent);
    return clean(el.getAttribute('alt') || el.getAttribute('placeholder') || el.getAttribute('title')
      || ((el.tagName === 'INPUT' && ['button', 'submit', 'reset'].includes(el.type)) ? el.value : '')
      || el.innerText || el.textContent);
  };
  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = (el.type || 'text').toLowerCase();
      if (['button', 'submit', 'reset', 'image'].includes(t)) return 'button';
      if (t === 'checkbox' || t === 'radio') return t;
      if (t === 'search') return 'searchbox';
      return 'textbox';
    }
    return el.isContentEditable ? 'textbox' : 'clickable';
  };
  const rows = [];
  let total = 0;
  for (const el of document.querySelectorAll(SELECTOR)) {
    if (!visible(el)) continue;
    total += 1;
    if (rows.length >= maxElements) continue;
    const ref = 'e' + (rows.length + 1);
    el.setAttribute('data-jarvis-ref', ref);
    const tag = el.tagName.toLowerCase();
    const type = tag === 'input' ? (el.type || 'text').toLowerCase() : '';
    const row = {ref, role: roleOf(el), name: clean(nameOf(el)).slice(0, maxName)};
    if (tag === 'a') row.href = (el.getAttribute('href') || '').slice(0, maxHref);
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') row.disabled = true;
    if (type === 'checkbox' || type === 'radio') row.checked = !!el.checked;
    else if (el.getAttribute('aria-checked')) row.checked = el.getAttribute('aria-checked') === 'true';
    if (type === 'password') row.secret = true;
    else if (tag === 'input' && !['button', 'submit', 'reset', 'image', 'checkbox', 'radio', 'file'].includes(type))
      row.value = clean(el.value).slice(0, 60);
    else if (tag === 'textarea') row.value = clean(el.value).slice(0, 60);
    else if (tag === 'select') row.value = clean(el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : '').slice(0, 60);
    if (el.getAttribute('aria-expanded')) row.expanded = el.getAttribute('aria-expanded') === 'true';
    rows.push(row);
  }
  return {title: document.title || '', url: location.href, total, rows,
          scrollY: Math.round(window.scrollY), height: Math.round(document.documentElement.scrollHeight)};
}
"""

_STATE_JS = """
(ref) => {
  const el = document.querySelector('[data-jarvis-ref="' + ref + '"]');
  if (!el) return null;
  const tag = el.tagName.toLowerCase();
  const type = tag === 'input' ? (el.type || 'text').toLowerCase() : '';
  const out = {tag, type, disabled: !!el.disabled, secret: type === 'password',
               checked: (type === 'checkbox' || type === 'radio') ? !!el.checked : null};
  if (tag === 'select') out.value = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : '';
  else if (tag === 'input' || tag === 'textarea') out.value = el.value;
  else if (el.isContentEditable) out.value = el.innerText;
  return out;
}
"""


@dataclass
class RefState:
    """What the last snapshot of this session's page looked like."""
    url: str = ""
    refs: dict = None            # ref -> {"role": ..., "name": ...}

    def __post_init__(self):
        if self.refs is None:
            self.refs = {}


def format_snapshot(data: dict) -> str:
    lines = [f"Page: {data.get('title') or '(untitled)'} — {data.get('url', '')}"]
    for row in data.get("rows", []):
        bits = [f"[{row['ref']}] {row['role']}", f"\"{row['name']}\"" if row.get("name") else '""']
        if row.get("href"):
            bits.append(f"-> {row['href']}")
        if row.get("secret"):
            bits.append("(password field)")
        elif row.get("value"):
            bits.append(f"value=\"{row['value']}\"")
        if row.get("checked") is not None:
            bits.append("checked" if row["checked"] else "unchecked")
        if row.get("expanded") is not None:
            bits.append("expanded" if row["expanded"] else "collapsed")
        if row.get("disabled"):
            bits.append("(disabled)")
        lines.append(" ".join(bits))
    shown = len(data.get("rows", []))
    total = int(data.get("total", shown))
    if total > shown:
        lines.append(f"... {total - shown} more elements not listed; scroll and take a new snapshot.")
    if not shown:
        lines.append("(no visible interactive elements)")
    lines.append(f"Scroll {data.get('scrollY', 0)} of {data.get('height', 0)} px. "
                 "Act with click_ref / type_ref / select_ref using the e-numbers.")
    return "\n".join(lines)


async def take_snapshot(page: Any, state: RefState) -> str:
    data = await page.evaluate(SNAPSHOT_JS, [MAX_ELEMENTS, MAX_NAME, MAX_HREF])
    state.url = data["url"]
    state.refs = {r["ref"]: {"role": r["role"], "name": r["name"]} for r in data["rows"]}
    return format_snapshot(data)


def _label(state: RefState, ref: str) -> str:
    info = state.refs.get(ref) or {}
    name = (info.get("name") or "")[:60]
    return f"{ref} {info.get('role', '')} \"{name}\"".strip()


async def _locate(page: Any, state: RefState, ref: str):
    """(locator, None) or (None, refusal sentence)."""
    ref = str(ref or "").strip().lower().lstrip("[").rstrip("]")
    if not REF_RE.match(ref):
        return None, "Give a ref like e12 from the latest snapshot."
    if not state.refs:
        return None, "Take a snapshot first (action='snapshot')."
    if ref not in state.refs:
        return None, f"Ref {ref} is not in the latest snapshot."
    if page.url != state.url:
        return None, "The page changed since the snapshot. Take a new snapshot."
    locator = page.locator(f'[data-jarvis-ref="{ref}"]')
    if await locator.count() != 1:
        return None, f"{ref} is gone — the page re-rendered. Take a new snapshot."
    return (ref, locator), None


async def _element_state(page: Any, ref: str):
    return await page.evaluate(_STATE_JS, ref)


async def _outcome(page: Any, before_url: str, before_title: str, ref: str) -> str:
    await page.wait_for_timeout(400)
    parts = []
    if page.url != before_url:
        parts.append(f"URL changed to {page.url}")
    else:
        parts.append("URL unchanged")
    try:
        title = await page.title()
    except Exception:
        title = before_title
    if title != before_title:
        parts.append(f"title is now \"{title[:60]}\"")
    try:
        still = await page.locator(f'[data-jarvis-ref="{ref}"]').count()
    except Exception:
        still = 0
    parts.append("element still on page" if still else "element no longer on page")
    return "; ".join(parts)


async def click_ref(page: Any, state: RefState, ref: str) -> str:
    found, refusal = await _locate(page, state, ref)
    if refusal:
        return refusal
    ref, locator = found
    info = await _element_state(page, ref)
    if info and info.get("disabled"):
        return f"{_label(state, ref)} is disabled."
    before_url, before_title = page.url, await page.title()
    try:
        await locator.click(timeout=8000)
    except Exception as exc:
        return f"Click on {_label(state, ref)} failed: {str(exc).splitlines()[0][:160]}"
    result = await _outcome(page, before_url, before_title, ref)
    if page.url != before_url:
        state.refs = {}         # a new page: the old refs no longer apply
    return f"Clicked {_label(state, ref)}. {result}."


async def type_ref(page: Any, state: RefState, ref: str, text: str,
                   clear_first: bool = True, submit: bool = False) -> str:
    found, refusal = await _locate(page, state, ref)
    if refusal:
        return refusal
    ref, locator = found
    info = await _element_state(page, ref) or {}
    if info.get("disabled"):
        return f"{_label(state, ref)} is disabled."
    if info.get("tag") not in ("input", "textarea") and "value" not in info:
        return f"{_label(state, ref)} is not a text field."
    try:
        if clear_first:
            await locator.fill("", timeout=8000)
        await locator.type(str(text), delay=30, timeout=8000)
    except Exception as exc:
        return f"Typing into {_label(state, ref)} failed: {str(exc).splitlines()[0][:160]}"
    after = await _element_state(page, ref) or {}
    if info.get("secret"):
        verdict = "typed into a password field (value not read back)"
    elif after.get("value") == (str(text) if clear_first else after.get("value")):
        verdict = "verified: the field holds the typed text"
    else:
        verdict = "WARNING: the field does not hold the typed text"
    if submit:
        before_url, before_title = page.url, await page.title()
        await locator.press("Enter")
        verdict += "; pressed Enter — " + await _outcome(page, before_url, before_title, ref)
        if page.url != before_url:
            state.refs = {}
    return f"{_label(state, ref)}: {verdict}."


async def select_ref(page: Any, state: RefState, ref: str, value: str) -> str:
    found, refusal = await _locate(page, state, ref)
    if refusal:
        return refusal
    ref, locator = found
    info = await _element_state(page, ref) or {}
    if info.get("tag") == "select":
        try:
            try:
                await locator.select_option(label=str(value), timeout=5000)
            except Exception:
                await locator.select_option(value=str(value), timeout=5000)
        except Exception as exc:
            return f"Choosing '{str(value)[:40]}' in {_label(state, ref)} failed: {str(exc).splitlines()[0][:120]}"
        after = await _element_state(page, ref) or {}
        return f"{_label(state, ref)} now shows \"{str(after.get('value', ''))[:60]}\"."
    if info.get("checked") is not None:
        want = str(value).strip().lower() in ("1", "true", "yes", "on", "checked")
        try:
            await locator.set_checked(want, timeout=5000)
        except Exception as exc:
            return f"Setting {_label(state, ref)} failed: {str(exc).splitlines()[0][:120]}"
        after = await _element_state(page, ref) or {}
        return f"{_label(state, ref)} is now {'checked' if after.get('checked') else 'unchecked'}."
    return f"{_label(state, ref)} is not a dropdown or checkbox."
