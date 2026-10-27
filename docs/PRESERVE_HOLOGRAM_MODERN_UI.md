# Preserve the Original JARVIS Hologram with Modern UI Enhancements

## Design rule
The original central NeuralWireframeHead and BihansaHologramWidget implementations and their central layout block are preserved from the pre-dashboard HUD. The original visualizer stack continues to switch between those two widgets. The small 28 px orb in the header is an additional status indicator, never a replacement for the center hologram.

## Added around the hologram
- Rounded bento-style telemetry surfaces around Brain, Security, Memory, Scheduler, and System Telemetry panels.
- Skeleton placeholder bars that briefly show on those side panels, followed by a short opacity reveal of their existing live widgets.
- A subtle pointer-directed shadow for side cards. It changes only the shadow offset/intensity and never moves the widget geometry.
- A small header orb that mirrors JARVIS state and audio energy without touching the central hologram's drawing or audio pipeline.
- Smooth 210 ms fades on ordinary pages in the separate HUD workspace. Canvas/WebEngine pages, including the Holo Hands view, are intentionally excluded to avoid altering their rendering or camera timing.

## Privacy and compatibility
Existing panel objects and telemetry signals are retained, so security lock still blurs the original Memory and Scheduler panels. The wrapper fades its own stack instead of adding/removing effects on a panel, preserving security-layer blur effects. No camera or microphone permission is enabled by these visual changes.

## Testing
The UI test suite verifies the original visualizer widget types and current-widget behavior, state/audio updates to both original holograms, the compact status orb, the new side-panel wrappers, and Bihansa mode switching.
