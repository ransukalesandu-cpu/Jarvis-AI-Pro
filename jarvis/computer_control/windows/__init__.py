"""Windows native control (Project 1, with the Project 6 fallback input folded in).

* :mod:`model` — plain data: apps, processes, windows, UI elements.
* :mod:`backend` — the backend protocol plus backend selection.
* :mod:`uia` — the real backend: pywinauto UI Automation (+ Win32 for window
  geometry), imported lazily and only on Windows.
* :mod:`fake` — an in-memory desktop for unit tests (Notepad, Calculator, a
  login form, dialogs) so the whole controller runs on Linux CI.
* :mod:`fallback_input` — guarded pyautogui-style coordinate input, used only
  when no accessible control exists.
* :mod:`controller` — the one Windows Controller API the tools and the
  orchestrator use. Every method verifies its effect where it can.
"""
