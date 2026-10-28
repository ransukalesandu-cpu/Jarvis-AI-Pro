# Holographic command centre — what shipped

This is the delivery report for the "next-generation holographic UI" upgrade:
what is implemented, what is only partial, what is deliberately not done, and
how to run and verify it.

The short version: the home screen is still one big hologram, but the hologram is
now a copper wireframe **face** rather than a rotating sphere, the small orb and
the "quantum heart" sit together under the chin instead of at opposite corners,
and every status surface behind them (battery, microphone, network, AI session,
task progress) is fed from real state. Nothing on screen invents a number.

---

## 1. Implemented

### Central hologram (`ui/hologram/wireframe_head.py`)

* **It is a face.** The old geometry was a UV sphere. It is now a head shell built
  from a profile table plus surface deformations: dome crown, temples and
  cheekbones as the widest points, a tapered jaw, a rounded chin, brow ridge, eye
  sockets, a nose ridge with nostril flare, upper-lip bulge and a mouth crease.
  The facial features (eyes, brows, nose, mouth) are sampled *on* the surface and
  drawn as glowing curves, so they move with the head instead of floating in
  front of it.
* **Hidden surfaces are culled**, which is what turns a fuzzy ball into a mask you
  can read. Perspective is gentle (focal length 9 rather than 3.5) so the nose no
  longer balloons relative to the temples.
* **It holds a gaze instead of spinning.** Each state sets a target
  three-quarter view with a slow ±0.2 rad drift: idle and listening look at the
  user, thinking scans, privacy lock faces straight ahead with a glitch.
* **State-driven animation** from real app state — `IDLE`, `LISTENING`,
  `THINKING`, `SPEAKING`, `ERROR`, `DISCONNECTED`, `PRIVACY_LOCK` — with audio
  energy from the existing `VisualizerBridge` driving scale, glow and node size.
* **No black box.** Both renderers used to clear to `transparent`, which Qt
  composites as black on a plain child widget; they now clear to
  `hologram_theme.BACKDROP_RGB`, the same colour the window paints, and the stage
  and visualizer stack no longer paint an opaque background.

### Palette and persona (`core/hologram_theme.py`)

* One `ThemePalette` per persona: **JARVIS** copper `#ff9d4d` / amber, **Bihansa**
  rose `#ff78d2`. Per-state accents are offsets on top of the persona, so Bihansa
  never turns JARVIS-cyan while speaking.
* Every renderer reads the palette: face, heart, orb, dashboard, task panels,
  island, health strip, status label.
* The Bihansa toggle still runs the existing persona path (`save_assistant_mode`
  → `sig_mode_changed` → live voice/persona selection) **and** now also switches
  the palette. It does not touch auth: a test asserts that switching persona while
  Privacy Lock is engaged leaves the lock banner up and the face locked.

### Orb and quantum heart (`ui/hologram/neural_heart_reactor.py`, `ui/panels/modern_dashboard.py`)

* The heart is **docked left of the status orb, below the face** (was the far-left
  screen edge with crescent conduits across the whole stage). Its filament now
  ends on the chin of the actual face rectangle, so the three elements read as one
  cluster and nothing crosses the face.
* **Real battery wiring**, via `BatteryMonitor`:
  * plugging in fires **one** energy pulse (rings expand and fade; it does not
    loop while the charger stays connected) plus a small bolt glyph;
  * at or under the low threshold the beat speeds up and the colour shifts amber;
  * a machine with **no battery sensor** shows nothing — no number, no bolt, no
    pulse, and the heart keeps its normal red→pink→orange cycle.
* The orb takes the same palette, honours `set_charging()` with an extra orbit
  ring, and respects the adaptive glow budget.

### Task panels (`ui/task_panels.py`)

* Kinds: music (slim 300×74 bar with a waveform), video, image, download,
  reminder, search, generic. `kind_for_action()` maps a real tool name to a kind.
* **Truthfulness by construction**: a control button is created only when its
  callback exists (play/pause/next only appear when the caller can actually do
  them); `progress=None` draws an indeterminate sweep; a percentage appears only
  when a real fraction is known; media panels stay 96 px tall until a thumbnail
  *file exists*.
* **Deterministic layout**: `layout_candidates()` generates slots in columns on
  both sides of the excluded rectangle and scores them by overlap with the
  blocked area (candidates that touch it are discarded outright), overlap with
  panels already placed, and distance from the face. Same inputs → same screen.
  When there is no honest space the panel is hidden, not clipped or stacked.
* The overlay follows the stage (resize-filtered) and excludes both the face
  rectangle and the orb/heart dock, so panels never land on the command centre.

### Task-panel producers (`core/task_sources.py`)

Voice commands are no longer the only source of panels. `TaskSourceRegistry`
polls the subsystems that already know about work in progress and turns their
state into `SourceTask`s; `TaskPanelManager.sync_sources()` diffs that list:

* **reminders** — the soonest pending prospective intention
  (`memory.prospective_memory.pending_intentions`), shown as `WAITING` because it
  is scheduled, not running;
* **downloads** — Steam's own manifest state (the same source
  `actions/game_updater._get_download_status` reads), shown as `RUNNING` and
  *indeterminate*: Steam reports a flag, not a percentage.

The diff updates a card in place (same `source:` id ⇒ same panel, no flicker),
closes cards whose producer stopped reporting, and never touches a voice-command
panel. Dismissing a producer card hides it until that producer stops reporting
the fact — so a reminder that comes due later is visible again. A producer that
*raises* is recorded in `registry.errors` and omitted: "unavailable" is never
reported as "nothing to show". The HUD polls this every 20 s (every fourth
status tick) so a file-reading producer never runs at frame rate.

### Music transport (`core/media_transport.py`)

The music panel's play/pause, previous and next buttons are wired to the OS
media keys (`pyautogui.press` on `playpause` / `nexttrack` / `prevtrack`). They
are *not* routed through `actions/spotify_control`, because that handler calls
`_ensure_spotify()` and would launch Spotify from a panel that may be showing a
YouTube tab.

* `TransportController.callbacks()` returns `{}` when no presser is available,
  and the panel then draws no transport buttons at all.
* The play/pause glyph flips only after the press reports success; a rejected
  key leaves the glyph alone. Media keys are fire-and-forget, so the card never
  claims what *is* playing — it shows the command that started it.
* A successful music command opens one persistent `media:now` card (`WAITING`,
  no progress sweep) with a dismiss control.

### Voice-command feedback (`main.py`, `ui/hud_main.py`)

* `_execute_tool` is wrapped by `begin_command` / `finish_command`; the HUD opens
  a task panel, **flashes it** as the target, marks it `RUNNING`, and marks it
  `COMPLETED` only when the tool's own returned text does not contain a failure
  marker. Otherwise it is `FAILED` and a notification is queued. An empty result
  counts as unconfirmed, never as success.
* Both helpers are no-ops for any other UI implementation, and cross threads via
  Qt signals.

### Dynamic Island (`ui/dynamic_island.py`)

* Frameless always-on-top pill, 208×44 collapsed, 344×108 expanded, 344×84 for a
  notification. Drag to move (drag is distinguished from click), click or
  Space/Enter to restore, Escape or click to collapse, arrow keys to expand.
* Shows real state (`listening`, `thinking`, `speaking`, `error`,
  `disconnected`, `privacy`), the battery text, the active task title and output
  energy.
* Minimising the HUD swaps the window for the pill; restoring swaps back. The
  timer, the bridge, audio and the live session keep running — a test asserts the
  bridge state and the poll timer survive the swap. The pill itself owns no audio
  or session reference.

### Live health and notifications (`ui/health_strip.py`, `core/substatus_probes`)

* Four indicators (MIC / SPK / NET / AI) with **letter glyphs** as well as colour,
  and a tooltip carrying the real detail string. `unavailable` renders as a hollow
  ring — no capability is never shown as green.
* Probes measure real things: audio devices via `sounddevice`, a TCP connect to
  the Gemini endpoint, and whether an API key is actually configured. Probes run
  in one daemon thread (`SubsystemProber`); an exception inside a probe is a
  broken subsystem, never a fake OK.
* `NotificationCenter` de-duplicates by key + cooldown, suppresses identical text
  forever, keeps the queue bounded by evicting the *least* important entry, and
  shows at most one alert per tick — in the island when minimised, in a toast
  otherwise.

### Adaptive performance and preferences

* `AdaptivePerformance` picks `full` (16 ms / 100 % particles / full glow),
  `balanced` (33 ms / 60 % / 75 %) or `saver` (66 ms / 25 % / 45 %) from battery
  level and optional CPU load, with 5-point hysteresis so a battery hovering at
  the threshold cannot thrash the renderer. Charging disables the saver tiers.
* Reduced motion, battery saver and charging effects are persisted in
  `QSettings` under `visual/*` and re-applied live. Reduced motion forces the
  saver budget.
* The four battery bands (`battery/fifty`, `battery/low`, `battery/critical`,
  `battery/full`) are edited in a real dialog — **BATTERY THRESHOLDS** in the
  right dropdown (`ui/panels/battery_settings.py`). `core/battery_settings.py` is
  the single reader/writer: junk values degrade to the documented defaults, and
  every save goes through `BatteryThresholds.validated()` so an out-of-order set
  can never reach the disk. Saving re-arms the live monitor and moves the
  adaptive-performance tiers to the same numbers, so the warning and the
  behaviour cannot disagree.
* Every timer is bounded to a widget or the window; no unbounded loops, no
  cross-thread widget updates (all cross-thread traffic is a Qt signal).

### Navigation and accessibility

* Minimal home page, expandable left rail, right dropdown, dashboard on its own
  page — all preserved from the previous UI.
* **Responsive chrome** (`core/hud_layout.py`): the rail is 44 px normally, 38 px
  under 1000 px and 32 px under 720 px, with buttons following it; the dropdown
  keeps 300 px on a wide window, shrinks to at most 34 % of the width and never
  below 208 px, and its height is clipped to the window. The window's minimum
  size is now 860×620 (was 1024×680) so those rules are actually reachable.
* The dropdown is a free-floating child, not a layout member, so it is sized with
  an explicit `adjustSize()` — without it Qt never gave it a height and it opened
  as a 30 px empty strip.
* **Escape closes the innermost overlay** (dropdown → toast → expanded island).
* Indicators carry text as well as colour; buttons have tooltips and accessible
  names; reduced motion is a first-class setting.

---

## 2. Partial

| Area | What works | What is missing |
| --- | --- | --- |
| Music transport | Play/pause/previous/next send real OS media keys when the platform can | There is still no *now playing* metadata: the OS media API is not queried, and the live Gemini audio stream is not a media player, so nothing here controls JARVIS's own voice output |
| Task producers | Reminders and Steam downloads push their own panels | No producer yet for the autonomous-agent step list (it has its own dashboard card) or for arbitrary background tools |
| Health indicators | Four indicators + audio-stream health feeding the island | The "audio error" indicator reflects the stream probe, not per-device error counts |
| Persona | Palette + existing persona/voice path + auth isolation | Voice timbre itself is unchanged (that is the live session's job, not the HUD's) |

---

## 3. Not implemented (on purpose)

* No OpenGL face-shader rewrite: the hologram is still QPainter, which keeps it
  working on the same machines as before and keeps the tests headless-friendly.
* No new heavyweight dependencies (the only import additions are stdlib).
* No fabricated placeholders anywhere: no fake battery percentage, no fake
  "connected", no fake progress bar, no decorative buttons.
* No auth changes: `AuthManager`, `ActionDispatcher`, Privacy Lock, host
  verification, owner voice ID and the PIN fallback are untouched.

---

## 4. Verification

```bash
# from the repository root
python -m pytest JarvisAI/tests -q          # 804 passed, 1 skipped, 109 subtests
ruff check JarvisAI                          # clean under the CI gate
```

Headless (no display server, e.g. CI or a container):

```bash
cd JarvisAI
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

If Qt's system libraries are missing, `conftest.py` skips the GUI modules rather
than failing; see `docs/DEVELOPMENT.md`.

New test files:

| File | Covers |
| --- | --- |
| `tests/test_hologram_theme.py` | palettes, per-state accents, preference parsing and junk tolerance |
| `tests/test_system_status.py` | battery edges (unplug/plug/threshold/full), no-sensor handling, health transitions, hysteresis, notification dedupe/eviction, probe isolation |
| `tests/test_task_panels.py` | layout never covers the face or other panels, determinism, control visibility, indeterminate progress, thumbnail-driven sizing |
| `tests/test_dynamic_island.py` | state normalisation, expand/collapse signals, drag vs click, keyboard, palette accents, "no audio handle" |
| `tests/test_hud_hologram_upgrade.py` | end-to-end wiring: palette reaches every renderer, persona switch keeps Privacy Lock, command → highlighted panel → truthful completion, battery absent/low/charging, health strip, minimise/restore, Escape, persisted preferences, and a paint smoke test for every custom surface |
| `tests/test_task_sources.py` | producer output (reminder/download), indeterminate progress, stable keys, failing producer reported as an error rather than as empty |
| `tests/test_hud_task_wiring.py` | `sync_sources` open/update/close, in-place updates, dismissal memory, transport buttons only with a real backend, glyph flips only on a delivered key, now-playing card, and the window applying the responsive chrome |
| `tests/test_media_transport.py` | media-key mapping, unavailable backend, rejected press, controller state truthfulness, action→command mapping |
| `tests/test_battery_settings.py` | load/save with junk, broken and out-of-order settings; dialog validation, defaults restore, emit-on-save |
| `tests/test_hud_layout.py` | rail/dropdown rules at every width |

The pre-existing suite is unchanged and still green (469 → 804 with the new
tests); no test was deleted or weakened.

## 5. Manual check

1. Launch the app. You should see the copper face centred, the orb and heart
   docked under the chin with one filament between them, and four small status
   letters at the top left.
2. Say something: the face should brighten with your voice; while JARVIS answers,
   the mouth region and ring respond.
3. Ask for a task (for example a YouTube search): a glass panel appears beside the
   face, pulses once as the target, then shows RUNNING and finally DONE or FAILED.
4. Unplug the charger: a single pulse runs through the heart, then it settles; at
   the low threshold the beat speeds up and turns amber.
5. Minimise the window: the Dynamic Island appears near the bottom of the screen
   and still shows state and battery. Click it to restore; everything keeps
   running while minimised.
6. Switch Bihansa mode: the chrome, heart, orb and panels turn rose while the
   JARVIS wireframe keeps its copper identity. Privacy Lock stays locked.
7. Press Escape with the dropdown open: it closes.
