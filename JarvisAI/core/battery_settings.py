"""Persistence for the battery warning bands.

``BatteryThresholds`` already knows how to *validate* a set of bands, but until
now the only way to set them was to hand-edit the registry: the HUD read
``battery/fifty``, ``battery/low``, ``battery/critical`` and ``battery/full``
straight out of ``QSettings`` at start-up. This module is the one place that
reads and writes those keys, so the settings dialog and the HUD cannot drift.

Qt-free on purpose: it accepts anything resembling ``QSettings`` (``.value(key,
default, type=...)`` / ``.setValue`` / ``.sync``), which makes it testable with a
plain dict wrapper and keeps the validation rules in one place.

Truthfulness rules
------------------
* Values that are not integers (or are missing) fall back to the documented
  defaults instead of raising — a corrupt settings file must not stop the HUD.
* Bands are always written back through :meth:`BatteryThresholds.validated`,
  so an out-of-order set can never be persisted as-is.
* Nothing here invents a battery: it only stores the *levels* at which a real
  reading will be reported.
"""

from __future__ import annotations

from core import failsoft
from core.system_status import BatteryThresholds

__all__ = [
    "KEYS",
    "DEFAULTS",
    "load_thresholds",
    "save_thresholds",
    "describe",
]

#: Settings key per band, in descending order of warning severity.
KEYS = {
    "fifty": "battery/fifty",
    "low": "battery/low",
    "critical": "battery/critical",
    "full": "battery/full",
}

DEFAULTS = BatteryThresholds()


def _read_int(settings, key: str, default: int) -> int:
    try:
        raw = settings.value(key, default)
    except Exception:
        return default
    if isinstance(raw, bool):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def load_thresholds(settings=None) -> BatteryThresholds:
    """The persisted bands, validated. No settings ⇒ the defaults."""
    if settings is None:
        return DEFAULTS
    return BatteryThresholds(
        fifty=_read_int(settings, KEYS["fifty"], DEFAULTS.fifty),
        low=_read_int(settings, KEYS["low"], DEFAULTS.low),
        critical=_read_int(settings, KEYS["critical"], DEFAULTS.critical),
        full=_read_int(settings, KEYS["full"], DEFAULTS.full),
    ).validated()


def save_thresholds(settings, thresholds: BatteryThresholds) -> BatteryThresholds:
    """Persist ``thresholds`` (after validation) and return what was stored."""
    clean = thresholds.validated()
    if settings is None:
        return clean
    for field, key in KEYS.items():
        try:
            settings.setValue(key, getattr(clean, field))
        except Exception:
            # A read-only or broken settings backend must not break the HUD;
            # the in-memory thresholds still apply for this session.
            failsoft.suppress("core.battery_settings:save_thresholds")
            continue
    flush = getattr(settings, "sync", None)
    if callable(flush):
        try:
            flush()
        except Exception:
            failsoft.suppress("core.battery_settings:save_thresholds.sync")
    return clean


def describe(thresholds: BatteryThresholds) -> str:
    """One line for a dialog's summary label."""
    clean = thresholds.validated()
    return (
        f"Critical ≤ {clean.critical}%  ·  Low ≤ {clean.low}%  ·  "
        f"Half ≤ {clean.fifty}%  ·  Full ≥ {clean.full}%"
    )
