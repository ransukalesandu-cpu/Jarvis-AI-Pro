# Web UI parity checklist (before `JARVIS_UI=web` can become the default)

Source of truth for "what the classic UI does": `jarvis/core/ui_menus.py` (28 commands feeding the menus and Ctrl+K) and the buttons built in `jarvis/ui/__init__.py`. Status is what is merged on `main` today, nothing aspirational.

Legend: ✅ done · 🟡 partial · ⬜ not yet · 🔒 stays native on purpose (privileged or secret-handling; the page must never reach it without a designed, authorised request)

## 1. Show state (read-only)
| Capability | Web UI | Notes |
|---|---|---|
| Assistant state (idle/listening/thinking/speaking/sleeping/error…) | ✅ | via `ui_state` bus; unknown labels are dropped |
| Audio level driving the hologram | ✅ | 20 Hz throttle |
| Mic muted | ✅ | Island shows MIC MUTED |
| Persona (JARVIS / BIHANSA) display | ✅ | HUD publishes `PERSONA` at start-up and on every mode change; the page shows it read-only (changing it stays native) |
| Conversation log (read-only) | ✅ | redacted; nothing forwarded while locked / PIN needed / silent / guest (a typed PIN is logged by the classic box before it is recognised, so this is gated at log time) |
| One-shot AI provider/model/key-configured | ✅ | never sends a key |
| CPU/RAM/disk/battery/network + history | ✅ | psutil in Python, 2-minute sparklines |
| Hologram (HoloAvatar look, heart, orb, wires) | ✅ | verified in QtWebEngine; real-GPU/Windows look unconfirmed |
| Performance tier (Auto/Full/Balanced/Lite) | 🟡 | current tier (full/balanced/lite) shown read-only in Settings from `PERF_TIER`; choosing a tier stays native |

## 2. Workspace / shell (ui_menus)
| Classic command | Web UI | Notes |
|---|---|---|
| Show the hologram (`home`) | ✅ | palette: "Close all windows (show hologram)" |
| Tile windows (`tile`) | ✅ | |
| Command palette (`palette`, Ctrl+K) | ✅ | only implemented actions |
| Save / Load workspace (`ws:save/load`) | ✅ | separate `web_workspaces.json`, validated |
| Settings (`settings`) | 🟡 | web settings panel covers motion + clock only |
| System / Telemetry / Activity panels | ✅ | floating windows |
| Dynamic Island | ✅ | real state, window count |
| Ask JARVIS / text command bar (`ask`, Ctrl+L) | ✅ | `command.submit` through `CommandGate`: refused while locked / PIN / silent / guest, credential-shaped text refused, limits, fail closed |
| `ask:routines`, `ask:jobs`, `ask:recent_actions` | ✅ | palette entries send the fixed ASK_TEXT through the gated command path (offered only while typing is available); reply text appears in the log mirror |
| Bento dashboard (`bento`) | ⬜ | |
| `mode:jarvis` / `mode:bihansa` | ⬜ | write path (changes persona) |
| `perf:*` | ⬜ | write path to the perf tier |

## 3. Tools / media windows (ui_menus `open:*`)
YouTube Music, Music player, Video player, Image viewer, News, Downloads: ⬜ all. Timer: ✅ (a real local window in the web UI; no backend needed). Opening the native ones from the page would be hidden under the web overlay, so each needs its own web window instead. These are native windows with their own backends; the web UI can open them only through a typed, allow-listed "open window" request (not built).

## 4. Controls in the classic side panel
| Control | Web UI |
|---|---|
| Interrupt, mute / unmute | ✅ (`control.do`; unmute refused while locked / PIN / silent / guest). Wake: ⬜ |
| Fullscreen | ✅ (`control.do`) |
| AI provider / keys, Voice ID, Remote control, Memory, Plugins, Audio devices, Auto-start, Desktop shortcut, Customise assistant, Response personality, Bihansa settings | 🔒 until each has a designed request. Anything that stores or shows a secret stays native |
| Neural hand control / camera preview | 🔒 / ⬜ |

## 5. Not yet built (needs a backend design, will not be faked)
- Task events + cancellation, notification centre (no event source exists today).
- Persistent chat history and search (the log mirror is this session only).

## 6. Quality gates before flipping the default
1. Owner runs `JARVIS_UI=web` on Windows with a real GPU and confirms the hologram, windows, palette and a full voice conversation. (CI `windows-ui-smoke` only proves it starts.)
2. A way back: `JARVIS_UI=legacy` must stay supported for at least one release; failure in web start-up already falls back to the classic HUD.
3. Every ⬜ in sections 2 and 4 either implemented or explicitly kept native, so nothing the owner uses daily disappears.
4. Real screen-reader pass (NVDA) over palette, windows and settings.
5. No new dependency without licence check; `dist/` freshness stays enforced by CI.

## 7. Suggested order
1. ~~Command bar~~ ✅ · ~~mute/interrupt/fullscreen~~ ✅ · ~~read-only log~~ ✅
2. Routines / jobs / recent actions palette entries; persona and performance tier writes (small, allow-listed).
3. Settings parity (excluding secrets).
4. Task events + notification centre (needs backend event publisher).
5. Media/tool windows via an allow-listed "open window" request.
