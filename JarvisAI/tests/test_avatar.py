"""Tests for Holographic AI Avatar enhancements."""

import pytest
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QImage, QPainter

from core.avatar import HoloAvatar as MeshHoloAvatar
from core.artificial_avatar import HoloAvatar as SyntheticHoloAvatar


def test_mesh_avatar_lifecycle_and_color_adaptation():
    avatar = MeshHoloAvatar()
    assert avatar.SPAN > 0

    # Test step with different states and expressions
    avatar.step(0.016, amp=0.5, speaking=True, muted=False, state="SPEAKING")
    assert avatar._glow > 0.0

    avatar.react_to_text("Emergency alert! Critical security warning.")
    avatar.step(0.016, amp=0.8, speaking=True, muted=False, state="SPEAKING")
    p, a = avatar._adapt_colors(0.016, QColor(113, 212, 194), QColor(217, 138, 89))
    assert p.isValid() and a.isValid()

    avatar.react_to_text("Hello good morning, welcome!")
    avatar.step(0.016, amp=0.2, speaking=False, muted=False, state="LISTENING")
    p_happy, a_happy = avatar._adapt_colors(0.016, QColor(113, 212, 194), QColor(217, 138, 89))
    assert p_happy.isValid() and a_happy.isValid()


def test_mesh_avatar_paint_offscreen():
    avatar = MeshHoloAvatar()
    img = QImage(QSize(400, 400), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0))

    painter = QPainter(img)
    try:
        avatar.step(0.016, amp=0.6, speaking=True, state="SPEAKING",
                    v_open=0.8, v_wide=0.3, v_level=0.5)
        avatar.paint(painter, 200.0, 200.0, 150.0,
                     QColor(113, 212, 194), QColor(217, 138, 89), QColor(8, 14, 18))
    finally:
        painter.end()


def test_synthetic_avatar_lifecycle_and_color_adaptation():
    avatar = SyntheticHoloAvatar()
    avatar.step(0.016, amp=0.7, speaking=True, muted=False, state="THINKING")
    assert avatar._energy > 0

    avatar.react_to_text("warning emergency error")
    avatar.step(0.016, amp=0.0, speaking=False, muted=False, state="PROCESSING")

    img = QImage(QSize(400, 400), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0))

    painter = QPainter(img)
    try:
        avatar.paint(painter, 200.0, 200.0, 150.0,
                     QColor(113, 212, 194), QColor(217, 138, 89), QColor(8, 14, 18))
    finally:
        painter.end()


def test_avatar_viseme_sequence_stepping():
    avatar = MeshHoloAvatar()
    v_seq = [
        (0.4, 0.8, 0.2),
        (0.6, 0.9, -0.1),
        (0.2, 0.1, 0.0),
    ]
    avatar.step(0.016, amp=0.5, speaking=True, state="SPEAKING",
                v_seq=v_seq, v_hop=0.02)
    assert avatar._mouth >= 0.0
