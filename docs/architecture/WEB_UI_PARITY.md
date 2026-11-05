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
| Performance tier (Auto/Full/Balanced/Lite) | ✅ | current tier shown from `PERF_TIER`; choosing one is a gated `control.do` (see §2) |

## 2. Workspace / shell (ui_menus)
| Classic command | Web UI | Notes |
|---|---|---|
| Show the hologram (`home`) | ✅ | palette: "Close all windows (show hologram)" |
| Tile windows (`tile`) | ✅ | |
| Command palette (`palette`, Ctrl+K) | ✅ | only implemented actions |
| Save / Load workspace (`ws:save/load`) | ✅ | separate `web_workspaces.json`, validated |
| Settings (`settings`) | 🟡 | motion, clock, persona and performance tier are live; everything else in the classic panel either holds a secret/privileged action (stays native, §4) or has no backend yet (§5) |
| System / Telemetry / Activity panels | ✅ | floating windows |
| Dynamic Island | ✅ | real state, window count |
| Ask JARVIS / text command bar (`ask`, Ctrl+L) | ✅ | `command.submit` through `CommandGate`: refused while locked / PIN / silent / guest, credential-shaped text refused, limits, fail closed |
| `ask:routines`, `ask:jobs`, `ask:recent_actions` | ✅ | palette entries send the fixed ASK_TEXT through the gated command path (offered only while typing is available); reply text appears in the log mirror |
| Bento dashboard (`bento`) | ✅ | "Dashboard" window: assistant, model, CPU/RAM, network, storage cards from the same real data |
| `mode:jarvis` / `mode:bihansa` | ✅ | `control.do` `mode_*`: refused while locked / PIN / silent / guest, `noop` if already active; Settings + palette |
| `perf:*` | ✅ | `control.do` `perf_*` (same gate, saved like the classic menu); Settings + palette |

## 3. Tools / media windows (ui_menus `open:*`)
News: ✅ (read-only mirror of the headlines the HUD is showing, §22 of NEXT_GEN_UI.md; the page never receives a URL). YouTube Music, Music player, Video player, Image viewer, Downloads: 🔒 kept native on purpose for now. Each is a native window with its own backend (media decoding, network fetch, or reading the user's files); a web version needs its own designed, authorised request and privacy review (especially Downloads and Image viewer, which would expose file names or contents to page JavaScript). They are reachable from the classic HUD and by voice. Until then they are a deliberate gap, not a forgotten one. Timer and Dashboard: ✅ (a real local window in the web UI; no backend needed). Opening the native ones from the page would be hidden under the web overlay, so each needs its own web window instead. These are native windows with their own backends; the web UI can open them only through a typed, allow-listed "open window" request (not built).

## 4. Controls in the classic side panel
| Control | Web UI |
|---|---|
| Interrupt, mute / unmute | ✅ (`control.do`; unmute refused while locked / PIN / silent / guest). Wake: 🔒 (waking the assistant is a security-relevant action; stays native until it has a designed request) |
| Fullscreen | ✅ (`control.do`) |
| AI provider / keys, Voice ID, Remote control, Memory, Plugins, Audio devices, Auto-start, Desktop shortcut, Customise assistant, Response personality, Bihansa settings | 🔒 until each has a designed request. Anything that stores or shows a secret stays native |
| Neural hand control / camera preview | 🔒 / ⬜ |

## 5. Not yet built (needs a backend design, will not be faked)
- Task events + cancellation, notification centre (no event source exists today).
- Persistent chat history and search (the log mirror is this session only).

## 6. Quality gates before flipping the default
1. Owner runs `JARVIS_UI=web` on Windows with a real GPU and confirms the hologram, windows, palette and a full voice conversation. (CI `windows-ui-smoke` only proves it starts.)
2. A way back: `JARVIS_UI=legacy` must stay supported for at least one release; failure in web start-up already falls back to the classic HUD.
3. Every ⬜ in sections 2 and 4 either implemented or explicitly kept native, so nothing the owner uses daily disappears. (Done: sections 2 and 4 have no ⬜ left; see §3 and §5 for what stays native or unbuilt.)
4. Real screen-reader pass (NVDA) over palette, windows and settings.
5. No new dependency without licence check; `dist/` freshness stays enforced by CI.

## 7. Suggested order
1. ~~Command bar~~ ✅ · ~~mute/interrupt/fullscreen~~ ✅ · ~~read-only log~~ ✅
2. ~~Routines / jobs / recent actions palette entries; persona and performance tier writes~~ ✅
3. ~~Settings parity (excluding secrets)~~ ✅ ~~Bento~~ ✅ ~~Timer~~ ✅
4. Task events + notification centre (needs backend event publisher).
5. Media/tool windows: each needs its own web window and backend design (the native ones sit under the web overlay, so an "open window" request would show nothing).
