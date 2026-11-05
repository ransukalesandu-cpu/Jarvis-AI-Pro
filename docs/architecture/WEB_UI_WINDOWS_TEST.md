# Trying the web UI on your Windows machine (about 10 minutes)

CI proves the web UI starts on Windows. It cannot prove that it looks and feels right on a real screen with a real
graphics card, or that it works during a real conversation. This is the short way to check that yourself.

## 1. Run the self-check (1 minute)

In the JARVIS folder:

```
python -m jarvis.webui.selfcheck
```

A window opens for about 15 seconds, then the result is printed (and saved as `webui_selfcheck.txt`). Lines are PASS, WARN or FAIL:

| Line | What it tells you |
|---|---|
| UI bundle / Backend link | the page loaded and talks to Python |
| Live data | CPU/RAM readings are arriving |
| WebGL | the hologram can draw; **SOFTWARE rendering** means the GPU is not being used (update the graphics driver) |
| Hologram canvas | the 3D scene exists |
| Smoothness | frames per second: 45+ good, 20 to 44 usable, below 20 too slow |

If you see `NOT READY`, keep using the classic HUD and send the saved `webui_selfcheck.txt` file.

## 2. Use it for real (5 minutes)

```
set JARVIS_UI=web
python main.py
```

(PowerShell: `$env:JARVIS_UI="web"`). Then check:

1. The blue head, orb and wires appear, and move when JARVIS talks (the hologram follows the real voice level).
2. Say something and let JARVIS answer: the state chip changes (listening, thinking, speaking) and the answer appears in the reply panel above the typing box.
3. `Ctrl+K` opens the command palette. Try "Open Dashboard window", "Open Background Jobs window", "Open Timer window", "Performance: Lite".
4. Type a question in the box (`Ctrl+L`) and press Enter.
5. Ask JARVIS for the news. Open the News window, press Open on a headline: it opens in your normal browser.
6. Lock JARVIS (privacy lock): typing and the log should stop working in the web UI, and unmuting from the page should be refused.
7. Close and reopen: your window layout comes back.

If anything looks wrong, take a screenshot and note what you did.

## 3. Going back

`JARVIS_UI=legacy` (or simply not setting `JARVIS_UI`) always gives the classic HUD. The web UI is opt-in; if it cannot start, JARVIS falls back to the classic HUD by itself.

## 4. What is not in the web UI yet

Music, YouTube Music, Video and Image windows, Downloads, wake from the page, and anything that handles keys or the
owner PIN stay in the classic HUD on purpose (see `WEB_UI_PARITY.md`). Screen-reader (NVDA) behaviour has only been
checked by an automated tool, not by ear.
