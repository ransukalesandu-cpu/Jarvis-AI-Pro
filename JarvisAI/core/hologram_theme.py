"""Hologram colour identities and the settings that scale their intensity.

JARVIS and Bihansa are two *personas*, and a persona is more than a hue: the
voice, the name and the accent palette ship together. This module owns the
palette half so every renderer (wireframe head, pink face, orb, heart, task
panels, dynamic island) pulls from one place instead of hard-coding hex values
that drift apart.

Design rules
------------
* Pure data + arithmetic. No Qt, no I/O, so it is trivial to test and cannot
  fail because a display or an audio device is missing.
* Colours are ``(r, g, b)`` tuples in 0-255. Renderers convert to whatever type
  they need.
* Every palette ships a *neutral* fallback: if a value is unknown, the caller
  gets JARVIS copper rather than a crash or an invisible black.

The settings object (:class:`VisualPreferences`) is deliberately tolerant: it
clamps out-of-range values and falls back to defaults, because it is fed
straight from a settings file that a user can hand-edit.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

__all__ = [
    "ThemePalette",
    "JARVIS_PALETTE",
    "BIHANSA_PALETTE",
    "PALETTES",
    "palette_for_mode",
    "VisualPreferences",
    "STATE_ACCENTS",
    "state_accent",
]

RGB = tuple[int, int, int]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class ThemePalette:
    """One persona's colour identity.

    ``primary`` is the wireframe line colour, ``secondary`` the neural nodes,
    ``glow`` the bloom around the mesh, ``accent`` the UI chrome (labels,
    rings), and ``deep`` the darker tone used for depth fade so the far side of
    the mesh reads as further away.
    """

    mode: str
    primary: RGB
    secondary: RGB
    glow: RGB
    accent: RGB
    deep: RGB
    # Heart / reactor colours, in the requested red → pink → orange cycle.
    heart_red: RGB
    heart_pink: RGB
    heart_orange: RGB

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "primary": self.primary,
            "secondary": self.secondary,
            "glow": self.glow,
            "accent": self.accent,
            "deep": self.deep,
            "heart_red": self.heart_red,
            "heart_pink": self.heart_pink,
            "heart_orange": self.heart_orange,
        }

    def scaled(self, intensity: float) -> "ThemePalette":
        """Brighten (or dim) the palette for glow/intensity settings.

        Only the emissive colours scale; ``deep`` stays put so the depth fade
        keeps its contrast instead of washing out.
        """
        factor = _clamp(intensity, 0.2, 1.6)

        def scale(rgb: RGB) -> RGB:
            return tuple(min(255, int(channel * factor)) for channel in rgb)  # type: ignore[return-value]

        return replace(
            self,
            primary=scale(self.primary),
            secondary=scale(self.secondary),
            glow=scale(self.glow),
            accent=scale(self.accent),
            heart_red=scale(self.heart_red),
            heart_pink=scale(self.heart_pink),
            heart_orange=scale(self.heart_orange),
        )


# JARVIS: copper-orange, amber and warm gold. The old cyan palette is kept only
# as the "deep" tone so the far side of the mesh still reads cool against the
# warm front — that contrast is what gives the wireframe its depth.
JARVIS_PALETTE = ThemePalette(
    mode="jarvis",
    primary=(255, 157, 77),      # copper
    secondary=(255, 199, 115),   # amber
    glow=(255, 138, 42),         # hot copper bloom
    accent=(255, 176, 84),       # UI chrome
    deep=(122, 63, 28),          # far-side depth
    heart_red=(255, 56, 72),
    heart_pink=(255, 96, 158),
    heart_orange=(255, 140, 48),
)

# Bihan: rose-pink neural network, same geometry, feminine accents.
BIHANSA_PALETTE = ThemePalette(
    mode="bihansa",
    primary=(255, 120, 210),     # pink
    secondary=(255, 170, 228),   # rose
    glow=(255, 76, 190),
    accent=(255, 155, 226),
    deep=(120, 42, 96),
    heart_red=(255, 88, 140),
    heart_pink=(255, 128, 190),
    heart_orange=(255, 150, 110),
)

PALETTES = {"jarvis": JARVIS_PALETTE, "bihansa": BIHANSA_PALETTE}

#: The HUD's backdrop. Renderers that must look "transparent" clear to this
#: exact colour instead of to alpha 0: on a plain child widget Qt composites a
#: transparent clear as black, which is what produced the old black rectangle
#: around the hologram.
BACKDROP_RGB: RGB = (8, 11, 17)


def backdrop_rgb() -> RGB:
    return BACKDROP_RGB


def backdrop_css() -> str:
    return "#%02x%02x%02x" % BACKDROP_RGB


def palette_for_mode(mode: str | None) -> ThemePalette:
    """Palette for ``"jarvis"`` / ``"bihansa"``; anything else gets JARVIS."""
    return PALETTES.get(str(mode or "").strip().lower(), JARVIS_PALETTE)


# Per-state accents used for rings, dust and status chrome. Values are offsets
# applied *on top of* the persona palette so Bihansa stays pink while speaking
# instead of turning JARVIS-cyan.
STATE_ACCENTS: dict[str, float] = {
    "IDLE": 0.0,
    "LISTENING": 0.35,
    "THINKING": 0.55,
    "SPEAKING": 0.75,
    "ERROR": 0.0,
    "DISCONNECTED": 0.0,
    "PRIVACY_LOCK": 0.0,
}


def state_accent(state: str) -> float:
    """0.0-1.0 intensity hint for a visual state (unknown states get 0.0)."""
    return STATE_ACCENTS.get(str(state or "IDLE").upper(), 0.0)


@dataclass(frozen=True)
class VisualPreferences:
    """User-tunable visual settings, already validated.

    Defaults match the shipped look. ``from_settings`` accepts anything that
    behaves like ``QSettings`` (``.value(key, default, type=...)``) and never
    raises: a corrupt settings file degrades to the defaults.
    """

    mode: str = "jarvis"
    glow: float = 1.0
    animation_speed: float = 1.0
    particle_intensity: float = 1.0
    glass_opacity: float = 0.92
    hologram_scale: float = 1.0
    reduced_motion: bool = False
    charging_effects: bool = True
    battery_saver: bool = True

    def validated(self) -> "VisualPreferences":
        return replace(
            self,
            mode="bihansa" if str(self.mode).lower() == "bihansa" else "jarvis",
            glow=round(_clamp(self.glow, 0.2, 1.6), 3),
            animation_speed=round(_clamp(self.animation_speed, 0.0, 2.0), 3),
            particle_intensity=round(_clamp(self.particle_intensity, 0.0, 1.0), 3),
            glass_opacity=round(_clamp(self.glass_opacity, 0.35, 1.0), 3),
            hologram_scale=round(_clamp(self.hologram_scale, 0.7, 1.3), 3),
        )

    @property
    def palette(self) -> ThemePalette:
        return palette_for_mode(self.mode)

    def scaled_palette(self) -> ThemePalette:
        return self.palette.scaled(self.glow)

    @classmethod
    def from_settings(cls, settings, fallback_mode: str = "jarvis") -> "VisualPreferences":
        """Build from a QSettings-like object, tolerating junk values."""

        def read(key: str, default, cast):
            try:
                value = settings.value(key, default)
            except Exception:
                return default
            try:
                return cast(value)
            except (TypeError, ValueError):
                return default

        def as_float(value, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        def as_bool(value, default: bool) -> bool:
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
            return default

        mode = read("visual/mode", fallback_mode, str)
        return cls(
            mode=mode,
            glow=as_float(read("visual/glow", 1.0, str), 1.0),
            animation_speed=as_float(read("visual/animation_speed", 1.0, str), 1.0),
            particle_intensity=as_float(read("visual/particles", 1.0, str), 1.0),
            glass_opacity=as_float(read("visual/glass_opacity", 0.92, str), 0.92),
            hologram_scale=as_float(read("visual/hologram_scale", 1.0, str), 1.0),
            reduced_motion=as_bool(read("visual/reduced_motion", False, str), False),
            charging_effects=as_bool(read("visual/charging_effects", True, str), True),
            battery_saver=as_bool(read("visual/battery_saver", True, str), True),
        ).validated()
