"""Qt versions of the web UI primitives (frontend/src/components/ui), on PyQt-Fluent-Widgets.

Same props on both surfaces: ``variant`` (solid / outline / ghost), ``size`` (sm / md / lg) and ``tone``
(neutral / primary / ok / warn / danger). Colours, spacing, radii and durations come from the shared tokens
(jarvis/ui/theme/tokens.py, generated from frontend/tokens/core.json).

Import this package lazily (it pulls in qfluentwidgets); nothing here runs at JARVIS start-up unless a
surface uses it. ``python -m jarvis.ui.components.gallery`` shows every component in every state.
"""
from .theme import apply_theme, current_theme, reduced_motion, token
from .widgets import (
    Button,
    Checkbox,
    Collapsible,
    Dialog,
    Input,
    Segmented,
    Select,
    Sheet,
    SparkChart,
    Switch,
    Table,
    Tabs,
    Textarea,
    popover,
    toast,
    tooltip,
)

__all__ = [
    "apply_theme", "current_theme", "reduced_motion", "token",
    "Button", "Checkbox", "Collapsible", "Dialog", "Input", "Segmented", "Select", "Sheet", "SparkChart",
    "Switch", "Table", "Tabs", "Textarea", "popover", "toast", "tooltip",
]
