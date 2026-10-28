"""Battery warning-band editor.

The HUD has always honoured four persisted threshold keys, but there was no way
to change them short of editing the registry by hand. This dialog is that way.

Design notes
------------
* Four spin boxes, each with the same bounds :meth:`BatteryThresholds.validated`
  enforces. The dialog never lets the user *see* an impossible set: as values
  change, :func:`core.battery_settings.describe` shows the bands that would be
  stored, and Save writes the validated set.
* "Restore defaults" resets the spin boxes; it does not save until you press
  Save, so an accidental click is cancellable.
* Nothing is applied here. The dialog emits :attr:`sig_saved` with the validated
  thresholds and the HUD decides what to push into the live monitors — keeping
  the widget free of references to batteries, timers or performance budgets.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.battery_settings import DEFAULTS, describe
from core.system_status import BatteryThresholds

__all__ = ["BatteryThresholdsDialog"]

_STYLE = """
QDialog { background: #070c13; }
QLabel { color: #c8d9d5; }
QLabel#BatteryHint { color: #8fa6ad; font-size: 11px; }
QLabel#BatterySummary { color: #ffd7a8; font-size: 12px; }
QSpinBox {
    color: #eaf6ff; background: #101923; border: 1px solid #2a4756;
    border-radius: 6px; padding: 4px 8px; min-width: 74px;
}
QSpinBox:focus { border-color: #00e5ff; }
QPushButton {
    color: #c8d9e5; background: rgba(12,24,35,220); border: 1px solid #244857;
    border-radius: 8px; padding: 6px 12px;
}
QPushButton:hover { color: #ffffff; border-color: #00e5ff; background: #102a38; }
"""

#: Bounds mirror BatteryThresholds.validated(); the two must stay in step.
_BOUNDS = {
    "critical": (1, 89),
    "low": (2, 90),
    "fifty": (30, 90),
    "full": (31, 100),
}


class BatteryThresholdsDialog(QDialog):
    """Edit and persist the four battery bands."""

    sig_saved = pyqtSignal(object)   # BatteryThresholds

    def __init__(self, thresholds: BatteryThresholds | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Battery Thresholds")
        self.setModal(True)
        self.setStyleSheet(_STYLE)
        self._initial = (thresholds or DEFAULTS).validated()
        self._spins: dict[str, QSpinBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QLabel("BATTERY WARNING BANDS")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        layout.addWidget(heading)

        hint = QLabel(
            "These are the charge levels at which JARVIS warns you and, for the "
            "low band, starts drawing less. Values that break the ordering are "
            "clamped to the nearest valid band when saved."
        )
        hint.setObjectName("BatteryHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        for field, label in (
            ("critical", "Critical at or below"),
            ("low", "Low at or below"),
            ("fifty", "Half at or below"),
            ("full", "Full at or above"),
        ):
            row = QHBoxLayout()
            row.setSpacing(10)
            text = QLabel(label + " (%):")
            text.setMinimumWidth(170)
            row.addWidget(text)
            spin = QSpinBox(self)
            low, high = _BOUNDS[field]
            spin.setRange(low, high)
            spin.setSuffix(" %")
            spin.setValue(int(getattr(self._initial, field)))
            spin.valueChanged.connect(self._refresh_summary)
            self._spins[field] = spin
            row.addWidget(spin)
            row.addStretch()
            layout.addLayout(row)

        self._summary = QLabel("")
        self._summary.setObjectName("BatterySummary")
        layout.addWidget(self._summary)

        self._warning = QLabel("")
        self._warning.setObjectName("BatteryHint")
        self._warning.setWordWrap(True)
        layout.addWidget(self._warning)

        buttons_row = QHBoxLayout()
        self._defaults_button = QPushButton("Restore defaults")
        self._defaults_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._defaults_button.clicked.connect(self._restore_defaults)
        buttons_row.addWidget(self._defaults_button)
        buttons_row.addStretch()
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._button_box.accepted.connect(self._on_save)
        self._button_box.rejected.connect(self.reject)
        buttons_row.addWidget(self._button_box)
        layout.addLayout(buttons_row)

        self._refresh_summary()

    # -- public API ---------------------------------------------------------
    def thresholds(self) -> BatteryThresholds:
        """The validated set the spin boxes currently describe."""
        return BatteryThresholds(
            critical=self._spins["critical"].value(),
            low=self._spins["low"].value(),
            fifty=self._spins["fifty"].value(),
            full=self._spins["full"].value(),
        ).validated()

    # -- internals ----------------------------------------------------------
    def _refresh_summary(self, *_args) -> None:
        current = self.thresholds()
        self._summary.setText(describe(current))
        ordered = (
            self._spins["fifty"].value() > self._spins["low"].value()
            > self._spins["critical"].value()
        )
        self._warning.setText(
            "" if ordered else
            "Critical < low < half is enforced: the saved values are adjusted "
            "to keep every band strictly below the one above it."
        )
        self._warning.setVisible(not ordered)

    def _restore_defaults(self) -> None:
        for field, spin in self._spins.items():
            spin.blockSignals(True)
            spin.setValue(int(getattr(DEFAULTS, field)))
            spin.blockSignals(False)
        self._refresh_summary()

    def _on_save(self) -> None:
        """Emit the validated bands. Persisting is the caller's job."""
        self.sig_saved.emit(self.thresholds())
        self.accept()
