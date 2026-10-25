"""Small QSettings-backed preferences for the optional Bihansa mode.

This module deliberately does not change voice providers or the existing JARVIS
mode. Provider-specific female voice selection belongs in a later integration
step after the current Gemini Live session configuration has been inspected.
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings


class BihansaModeSettings:
    """Persist Bihansa appearance preferences without touching other settings."""

    GROUP = "bihansa"

    def __init__(self, settings: QSettings | None = None):
        self._settings = settings or QSettings("JarvisAI", "JarvisAIPro")

    def _get(self, key: str, default):
        self._settings.beginGroup(self.GROUP)
        try:
            return self._settings.value(key, default)
        finally:
            self._settings.endGroup()

    def _set(self, key: str, value) -> None:
        self._settings.beginGroup(self.GROUP)
        try:
            self._settings.setValue(key, value)
            self._settings.sync()
        finally:
            self._settings.endGroup()

    @property
    def assistant_mode(self) -> str:
        value = str(self._get("assistant_mode", "jarvis")).strip().lower()
        if value not in {"jarvis", "bihansa"}:
            value = "jarvis"
        try:
            from memory.config_manager import get_assistant_mode
            cfg_val = get_assistant_mode()
            if cfg_val in {"jarvis", "bihansa"} and cfg_val != value:
                value = cfg_val
        except Exception:
            pass
        return value

    @assistant_mode.setter
    def assistant_mode(self, value: str) -> None:
        normalized = str(value or "jarvis").strip().lower()
        if normalized not in {"jarvis", "bihansa"}:
            normalized = "jarvis"
        self._set("assistant_mode", normalized)
        try:
            from memory.config_manager import save_assistant_mode
            save_assistant_mode(normalized)
        except Exception:
            pass

    @property
    def bihansa_voice(self) -> str:
        try:
            from memory.config_manager import get_bihansa_voice
            return get_bihansa_voice()
        except Exception:
            val = str(self._get("bihansa_voice", "Kore")).strip()
            return val if val in {"Kore", "Aoede"} else "Kore"

    @bihansa_voice.setter
    def bihansa_voice(self, value: str) -> None:
        normalized = str(value or "Kore").strip()
        valid = normalized if normalized in {"Kore", "Aoede"} else "Kore"
        self._set("bihansa_voice", valid)
        try:
            from memory.config_manager import save_bihansa_voice
            save_bihansa_voice(valid)
        except Exception:
            pass

    @property
    def reduced_motion(self) -> bool:
        value = self._get("reduced_motion", False)
        return value if isinstance(value, bool) else str(value).lower() in {"1", "true", "yes", "on"}

    @reduced_motion.setter
    def reduced_motion(self, value: bool) -> None:
        self._set("reduced_motion", bool(value))

    @property
    def glow_intensity(self) -> float:
        try:
            val = float(self._get("glow_intensity", 1.0))
            return max(0.0, min(1.5, val))
        except (TypeError, ValueError):
            return 1.0

    @glow_intensity.setter
    def glow_intensity(self, value: float) -> None:
        try:
            normalized = max(0.0, min(1.5, float(value)))
        except (TypeError, ValueError):
            normalized = 1.0
        self._set("glow_intensity", normalized)

    @property
    def animation_speed(self) -> float:
        try:
            val = float(self._get("animation_speed", 1.0))
            return max(0.0, min(2.0, val))
        except (TypeError, ValueError):
            return 1.0

    @animation_speed.setter
    def animation_speed(self, value: float) -> None:
        try:
            normalized = max(0.0, min(2.0, float(value)))
        except (TypeError, ValueError):
            normalized = 1.0
        self._set("animation_speed", normalized)

    def restore_bihansa_defaults(self) -> None:
        """Reset only Bihansa preferences; preserve unrelated app settings."""
        self._settings.beginGroup(self.GROUP)
        try:
            self._settings.remove("")
            self._settings.setValue("assistant_mode", "jarvis")
            self._settings.setValue("reduced_motion", False)
            self._settings.setValue("glow_intensity", 1.0)
            self._settings.setValue("animation_speed", 1.0)
            self._settings.sync()
        finally:
            self._settings.endGroup()
        try:
            from memory.config_manager import save_assistant_mode, save_bihansa_voice
            save_assistant_mode("jarvis")
            save_bihansa_voice("Kore")
        except Exception:
            pass


try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import (
        QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout
    )

    class BihansaSettingsDialog(QDialog):
        """Configuration dialog for Bihansa Mode appearance and voice preferences."""

        def __init__(self, parent=None, settings: BihansaModeSettings | None = None, on_applied=None):
            super().__init__(parent)
            self.setWindowTitle("Bihansa Mode Settings")
            self.setMinimumWidth(340)
            self.setStyleSheet("""
                QDialog { background-color: #0b0710; color: #ffb3e2; }
                QLabel { color: #ffb3e2; font-size: 11px; }
                QComboBox, QCheckBox { color: #ffffff; background-color: #1a0f24; border: 1px solid #ff72c6; padding: 3px; border-radius: 3px; }
                QSlider::groove:horizontal { background: #1a0f24; height: 6px; border-radius: 3px; }
                QSlider::handle:horizontal { background: #ff72c6; width: 14px; margin: -4px 0; border-radius: 7px; }
                QPushButton { background: #1a0f24; color: #ffb3e2; border: 1px solid #ff72c6; border-radius: 3px; padding: 4px 10px; font-weight: bold; }
                QPushButton:hover { background: #ff72c6; color: #0b0710; }
            """)
            self._settings = settings or BihansaModeSettings()
            self._on_applied = on_applied

            layout = QVBoxLayout(self)
            layout.setSpacing(10)

            hdr = QLabel("⚙ BIHANSA MODE PREFERENCES")
            hdr.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            hdr.setStyleSheet("color: #ff72c6; padding-bottom: 4px; border-bottom: 1px solid #ff3eae;")
            layout.addWidget(hdr)

            layout.addWidget(QLabel("Assistant Mode:"))
            self._mode_combo = QComboBox()
            self._mode_combo.addItem("JARVIS Mode", "jarvis")
            self._mode_combo.addItem("Bihansa Mode", "bihansa")
            m_idx = 1 if self._settings.assistant_mode == "bihansa" else 0
            self._mode_combo.setCurrentIndex(m_idx)
            layout.addWidget(self._mode_combo)

            layout.addWidget(QLabel("Female Voice (Gemini Live):"))
            self._voice_combo = QComboBox()
            self._voice_combo.addItem("Kore (Warm / Calm)", "Kore")
            self._voice_combo.addItem("Aoede (Expressive)", "Aoede")
            v_idx = 1 if self._settings.bihansa_voice == "Aoede" else 0
            self._voice_combo.setCurrentIndex(v_idx)
            layout.addWidget(self._voice_combo)

            self._motion_chk = QCheckBox("Reduced Motion")
            self._motion_chk.setChecked(self._settings.reduced_motion)
            layout.addWidget(self._motion_chk)

            layout.addWidget(QLabel("Glow Intensity:"))
            self._glow_slider = QSlider(Qt.Orientation.Horizontal)
            self._glow_slider.setRange(0, 150)
            self._glow_slider.setValue(int(self._settings.glow_intensity * 100))
            layout.addWidget(self._glow_slider)

            layout.addWidget(QLabel("Animation Speed:"))
            self._speed_slider = QSlider(Qt.Orientation.Horizontal)
            self._speed_slider.setRange(0, 200)
            self._speed_slider.setValue(int(self._settings.animation_speed * 100))
            layout.addWidget(self._speed_slider)

            btn_lay = QHBoxLayout()
            reset_btn = QPushButton("Restore Defaults")
            reset_btn.clicked.connect(self._reset_defaults)
            save_btn = QPushButton("Save & Apply")
            save_btn.clicked.connect(self._save_and_apply)
            btn_lay.addWidget(reset_btn)
            btn_lay.addWidget(save_btn)
            layout.addLayout(btn_lay)

        def _reset_defaults(self):
            self._settings.restore_bihansa_defaults()
            self._mode_combo.setCurrentIndex(0)
            self._voice_combo.setCurrentIndex(0)
            self._motion_chk.setChecked(False)
            self._glow_slider.setValue(100)
            self._speed_slider.setValue(100)

        def _save_and_apply(self):
            self._settings.assistant_mode = self._mode_combo.currentData()
            self._settings.bihansa_voice = self._voice_combo.currentData()
            self._settings.reduced_motion = self._motion_chk.isChecked()
            self._settings.glow_intensity = self._glow_slider.value() / 100.0
            self._settings.animation_speed = self._speed_slider.value() / 100.0
            if callable(self._on_applied):
                self._on_applied()
            self.accept()
except ImportError:
    pass
