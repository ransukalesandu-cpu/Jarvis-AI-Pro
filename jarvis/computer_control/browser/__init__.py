"""Browser control (Project 3): Playwright on the installed Edge/Chrome.

* :mod:`backend`            — protocol, page/element data, backend selection;
* :mod:`fake`               — in-memory browser for tests (pages, forms, login, downloads);
* :mod:`playwright_backend` — the real backend: Playwright sync API on its own
  thread, the installed ``msedge``/``chrome`` channel (no bundled Chromium
  download), a dedicated JARVIS profile (never the owner's personal profile),
  element refs from ``core/page_snapshot.SNAPSHOT_JS``;
* :mod:`controller`         — the Browser Controller API with verification;
* :mod:`tools`              — the ``cc_browser`` ToolSpec.
"""
