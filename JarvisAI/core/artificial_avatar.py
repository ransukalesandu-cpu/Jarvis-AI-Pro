"""Artificial holographic avatar for the Jarvis HUD.

This renderer is deliberately synthetic (not a photo or realistic human mesh).
It implements the same small interface as core.avatar.HoloAvatar so the
existing HUD, voice pipeline, viseme scheduler and facial-text callbacks remain
unchanged. No new third-party dependency is required.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QBrush, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient


def _with_alpha(color: QColor, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(max(0, min(255, int(alpha))))
    return result


class HoloAvatar:
    """Angular synthetic face with audio/viseme-driven mouth animation."""

    # Normalized vertical extent used by HudCanvas when sizing/centering the head.
    # Drawing spans approximately -0.94r through +0.955r, including the status bar.
    SPAN = 1.90

    def __init__(self) -> None:
        self._time = 0.0
        self._mouth = 0.0
        self._mouth_width = 0.0
        self._energy = 0.0
        self._blink = 0.0
        self._next_blink = 2.7
        self._state = "INITIALISING"
        self._speaking = False
        self._muted = False
        self._expression = 0.0
        self._expression_target = 0.0
        self._look_x = 0.0
        self._look_y = 0.0
        self._look_target = (0.0, 0.0)
        self._look_until = 0.0

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        self._look_target = (max(-1.0, min(1.0, float(dx))),
                             max(-1.0, min(1.0, float(dy))))
        self._look_until = self._time + max(0.0, float(hold))

    def react_to_text(self, text: str) -> None:
        raw = str(text or "").casefold()
        if any(k in raw for k in ("hello", "hi ", "hey", "ayubowan", "ආයුබෝවන්", "great", "thanks", "thank you", "හොඳයි", "ස්තුතියි")):
            self._expression_target = 0.82
        elif any(k in raw for k in ("sorry", "sad", "අවුල්", "කණගාටු", "වැරදි")):
            self._expression_target = -0.62
        elif any(k in raw for k in ("warning", "danger", "error", "careful", "අවදානම්", "ප්‍රවේශම්")):
            self._expression_target = -0.92
        elif "?" in raw:
            self._expression_target = 0.38
        else:
            self._expression_target = 0.0

    def step(self, dt: float, amp: float, speaking: bool = False,
             muted: bool = False, state: str = "",
             v_open: float | None = None, v_wide: float = 0.0,
             v_level: float | None = None,
             v_seq: list | None = None, v_hop: float = 0.02) -> None:
        dt = max(0.001, min(0.10, float(dt)))
        self._time += dt
        self._state = str(state or "IDLE").upper()
        self._speaking = bool(speaking and not muted)
        self._muted = bool(muted)
        # Whole-face expression and hologram geometry keep moving even in idle.
        if self._state in ("THINKING", "PROCESSING"):
            self._expression_target = max(self._expression_target, 0.30)
        elif self._state == "LISTENING":
            self._expression_target = max(self._expression_target, 0.12)
        elif not self._speaking and self._state in ("IDLE", "READY"):
            self._expression_target *= 0.985
        self._expression += (self._expression_target - self._expression) * (1.0 - math.exp(-dt * 3.2))

        # Consume every scheduled viseme frame. This preserves short lip
        # closures (M/B/P) even when the UI timer skips a render frame.
        if self._speaking and v_seq:
            for frame in v_seq:
                try:
                    level, openness, width = frame
                    level = max(0.0, min(1.0, float(level)))
                    openness = max(0.0, min(1.0, float(openness)))
                    width = max(-1.0, min(1.0, float(width)))
                    target = (level ** 0.55) * openness
                    if level < 0.035:
                        target = 0.0
                    frame_dt = max(0.008, min(0.04, float(v_hop)))
                    tau = 0.018 if target > self._mouth else 0.012
                    self._mouth += (target - self._mouth) * (1.0 - math.exp(-frame_dt / tau))
                    self._mouth_width += (width - self._mouth_width) * 0.55
                except (TypeError, ValueError):
                    continue
        elif self._speaking:
            shape = 0.75 if v_open is None else max(0.0, min(1.0, float(v_open)))
            level = max(float(amp), float(v_level or 0.0))
            target = min(1.0, max(0.0, (level ** 0.58) * shape))
            self._mouth += (target - self._mouth) * (1.0 - math.exp(-dt / 0.025))
            if v_wide is not None:
                self._mouth_width += (max(-1.0, min(1.0, float(v_wide))) -
                                      self._mouth_width) * 0.30
        else:
            self._mouth += (0.0 - self._mouth) * (1.0 - math.exp(-dt / 0.06))
            self._mouth_width += (0.0 - self._mouth_width) * 0.15

        self._mouth = max(0.0, min(1.0, self._mouth))
        target_energy = 0.72 if self._speaking else (0.5 if self._state == "LISTENING" else 0.22)
        if self._state in ("THINKING", "PROCESSING"):
            target_energy = 0.9
        if self._muted:
            target_energy = 0.12
        self._energy += (target_energy - self._energy) * (1.0 - math.exp(-dt / 0.22))

        if self._time >= self._next_blink:
            self._blink = 1.0
            self._next_blink = self._time + 2.2 + (math.sin(self._time * 2.1) + 1.0) * 1.2
        self._blink = max(0.0, self._blink - dt * 7.5)
        if self._time > self._look_until:
            self._look_target = (0.0, 0.0)
        self._look_x += (self._look_target[0] - self._look_x) * min(1.0, dt * 5.0)
        self._look_y += (self._look_target[1] - self._look_y) * min(1.0, dt * 5.0)

    def paint(self, p, cx: float, cy: float, r: float,
              primary: QColor, accent: QColor, bg: QColor) -> None:
        """Render an always-moving, blue-line holographic face."""
        r = max(1.0, float(r))
        t = self._time
        mood = max(-1.0, min(1.0, self._expression))
        speaking = self._speaking
        listening = self._state == "LISTENING"
        thinking = self._state in ("THINKING", "PROCESSING")
        pulse = 0.5 + 0.5 * math.sin(t * (4.4 if speaking else 2.0))
        breathe = math.sin(t * 1.25) * 0.012
        shift_x = math.sin(t * 0.72) * 0.012 + self._look_x * 0.018
        shift_y = math.sin(t * 0.91) * 0.009 + self._look_y * 0.012
        blink = max(0.035, 1.0 - self._blink)
        energy = max(self._energy, pulse * 0.18)

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        def pt(x: float, y: float) -> QPointF:
            # Slight coordinated drift makes the complete line-built face feel alive.
            return QPointF(cx + (x + shift_x) * r, cy + (y + shift_y + breathe) * r)

        def line(a, b, alpha=210, width=0.009):
            p.setPen(QPen(_with_alpha(primary, int(max(0, min(255, alpha)))),
                          max(1.0, r * width), Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(pt(a[0], a[1]), pt(b[0], b[1]))

        def poly(points, alpha=210, width=0.009, closed=False):
            path = QPainterPath()
            path.moveTo(pt(points[0][0], points[0][1]))
            for x, y in points[1:]:
                path.lineTo(pt(x, y))
            if closed:
                path.closeSubpath()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_with_alpha(primary, int(max(0, min(255, alpha)))),
                          max(1.0, r * width), Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)

        def node(x, y, radius=0.018, alpha=220):
            q = pt(x, y)
            rr = r * radius * (0.8 + pulse * 0.45)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_with_alpha(primary, alpha), max(1.0, r * 0.007)))
            p.drawEllipse(QRectF(q.x()-rr, q.y()-rr, rr*2, rr*2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_with_alpha(primary, int(alpha * 0.20)))
            p.drawEllipse(QRectF(q.x()-rr*0.35, q.y()-rr*0.35, rr*0.7, rr*0.7))

        # Ambient blue aura; the face itself remains a wireframe, not a filled mask.
        aura = QRadialGradient(QPointF(cx, cy), r * 1.18)
        aura.setColorAt(0.0, _with_alpha(primary, int(18 + energy * 24)))
        aura.setColorAt(0.58, _with_alpha(primary, 7))
        aura.setColorAt(1.0, _with_alpha(primary, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(aura))
        p.drawEllipse(QRectF(cx-r*1.18, cy-r*1.18, r*2.36, r*2.36))

        # Rotating orbital rings and segmented perimeter marks.
        for idx, (scale, alpha) in enumerate(((0.93, 45), (1.04, 75), (1.15, 28))):
            rect = QRectF(cx-r*scale, cy-r*scale, 2*r*scale, 2*r*scale)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_with_alpha(primary, int(alpha * (0.55 + pulse*0.45))),
                          max(1.0, r*0.004)))
            p.drawArc(rect, int((t*35 + idx*72) % 360 * 16), 248*16)
        for i in range(48):
            a = (i / 48.0) * math.tau + t * 0.16
            inner = 1.07 if i % 4 else 1.045
            outer = 1.10 if i % 4 else 1.135
            line((math.cos(a)*inner, math.sin(a)*inner),
                 (math.cos(a)*outer, math.sin(a)*outer), 75 if i % 4 else 155, 0.004)

        # Outer head contour: every segment softly ripples in a synchronized wave.
        contour = [
            (-0.61,-0.62), (-0.48,-0.82), (-0.25,-0.91), (0.0,-0.94),
            (0.25,-0.91), (0.48,-0.82), (0.61,-0.62), (0.70,-0.34),
            (0.72,-0.05), (0.65,0.30), (0.50,0.59), (0.27,0.78),
            (0.0,0.85), (-0.27,0.78), (-0.50,0.59), (-0.65,0.30),
            (-0.72,-0.05), (-0.70,-0.34)
        ]
        moving_contour = []
        for i, (x, y) in enumerate(contour):
            wave = math.sin(t*1.8 + i*0.77) * 0.006
            moving_contour.append((x + math.copysign(wave, x if x else 1), y + wave))
        poly(moving_contour, 235, 0.015, True)

        # Cross-grid curves and animated scan bands define the face planes.
        for row, y in enumerate((-0.77,-0.66,-0.53,-0.40,-0.18,0.04,0.24,0.44,0.62,0.73)):
            half = 0.20 + 0.48 * math.sqrt(max(0.05, 1.0 - ((y+0.02)/0.98)**2))
            points = []
            for j in range(13):
                x = -half + 2*half*j/12
                yy = y + math.sin(x*7.0 + t*1.65 + row) * (0.008 + pulse*0.004)
                points.append((x, yy))
            poly(points, 62 if row % 2 else 112, 0.0045)
        for col in range(-4, 5):
            x0 = col * 0.125
            points = []
            for j in range(13):
                y = -0.80 + j * 0.125
                x = x0 + math.sin(y*5.2 + t*1.35 + col) * 0.012
                points.append((x, y))
            poly(points, 48 if col % 2 else 85, 0.004)

        # Forehead circuit paths with traveling highlight nodes.
        for side in (-1, 1):
            poly([(side*0.08,-0.83),(side*0.22,-0.78),(side*0.29,-0.68),
                  (side*0.43,-0.64),(side*0.49,-0.54)], 170, 0.008)
            poly([(side*0.56,-0.42),(side*0.48,-0.34),(side*0.51,-0.20),
                  (side*0.43,-0.10),(side*0.48,0.02)], 190, 0.009)
            poly([(side*0.58,0.20),(side*0.48,0.28),(side*0.43,0.42),
                  (side*0.31,0.50)], 145, 0.007)
            idx = int((t*5 + (0 if side < 0 else 3)) % 5)
            nodes = [(-0.29,-0.68),(-0.49,-0.54),(-0.51,-0.20),(-0.48,0.02),(-0.43,0.42)]
            nx, ny = nodes[idx]
            node(nx if side < 0 else -nx, ny, 0.014, 210)

        # Eyebrows rotate into expressive angles instead of staying fixed.
        brow_raise = mood * 0.055 + (0.018 if thinking else 0.0)
        brow_tilt = mood * 0.11
        for side in (-1, 1):
            inner_x = side * 0.10
            outer_x = side * 0.52
            inner_y = -0.405 - brow_raise + brow_tilt * side
            outer_y = -0.435 - brow_raise - brow_tilt * side
            poly([(outer_x,outer_y),(side*0.38,inner_y-0.015),
                  (side*0.24,inner_y+0.012),(inner_x,inner_y+0.035)],
                 235, 0.014)
            # Eye sockets and lids respond to blinking, listening and emotion.
            eye_y = -0.285 + mood*0.012
            eye_h = (0.045 + (0.018 if listening else 0.0)) * blink
            poly([(side*0.09,eye_y),(side*0.18,eye_y-eye_h),
                  (side*0.33,eye_y-eye_h*1.12),(side*0.47,eye_y),
                  (side*0.34,eye_y+eye_h),(side*0.19,eye_y+eye_h*0.92)],
                 235, 0.011, True)
            # Iris and pupil drift with gaze; iris rings pulse while listening.
            ix = side*0.29 + self._look_x*0.035
            iy = eye_y + self._look_y*0.018
            q = pt(ix, iy)
            ir = r * (0.036 if blink > 0.22 else 0.012)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_with_alpha(primary, 235), max(1.0,r*0.009)))
            p.drawEllipse(QRectF(q.x()-ir,q.y()-ir,q.x()+ir-(q.x()-ir),q.y()+ir-(q.y()-ir)))
            line((ix-ir/r*0.35,iy),(ix+ir/r*0.35,iy),255,0.008)
            poly([(side*0.16,eye_y+eye_h+0.035),(side*0.29,eye_y+eye_h+0.05),
                  (side*0.43,eye_y+eye_h+0.025)], 100, 0.005)

        # Cheek plates, cheek contours and jaw hinges subtly shift with expression.
        cheek_lift = mood * 0.025
        for side in (-1, 1):
            poly([(side*0.12,0.04),(side*0.23,0.09+cheek_lift),
                  (side*0.40,0.12+cheek_lift),(side*0.53,0.08)],
                 185, 0.009)
            poly([(side*0.17,0.18),(side*0.31,0.22+cheek_lift),
                  (side*0.43,0.27),(side*0.39,0.39),(side*0.27,0.46)],
                 220, 0.010)
            poly([(side*0.54,0.39),(side*0.48,0.52),(side*0.34,0.65),
                  (side*0.19,0.73)], 145, 0.008)
            node(side*0.52, 0.19 + math.sin(t*2.2+side)*0.012, 0.012, 190)

        # Nose is a multi-line sensor, with a tiny animated bridge highlight.
        poly([(0.0,-0.20),(-0.025,-0.06),(-0.065,0.075),(0.0,0.12),
              (0.065,0.075),(0.025,-0.06),(0.0,-0.20)], 225, 0.010)
        line((-0.10,0.105),(-0.045,0.14),170,0.007)
        line((0.045,0.14),(0.10,0.105),170,0.007)
        node(0.0, -0.055 + math.sin(t*3.0)*0.008, 0.010, 225)

        # Mouth line becomes a smile, neutral line or frown; voice adds a pulsing aperture.
        mouth_y = 0.405
        mouth_open = self._mouth if speaking else 0.0
        mouth_half = 0.235 + 0.025 * max(0.0, mood) + 0.025 * self._mouth_width
        smile = mood * 0.075
        mouth_path = QPainterPath()
        mouth_path.moveTo(pt(-mouth_half, mouth_y + smile))
        mouth_path.quadTo(pt(-mouth_half*0.50, mouth_y - smile*0.38 - mouth_open*0.07),
                          pt(0.0, mouth_y - mouth_open*(0.045+0.10*mouth_open)))
        mouth_path.quadTo(pt(mouth_half*0.50, mouth_y - smile*0.38 - mouth_open*0.07),
                          pt(mouth_half, mouth_y + smile))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_with_alpha(primary, 250), max(1.4,r*0.014),
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(mouth_path)
        if mouth_open > 0.10:
            mouth_inner = QPainterPath()
            mouth_inner.moveTo(pt(-mouth_half*0.80,mouth_y+0.005))
            mouth_inner.quadTo(pt(0,mouth_y+mouth_open*0.15),
                               pt(mouth_half*0.80,mouth_y+0.005))
            p.setPen(QPen(_with_alpha(primary,int(100+140*mouth_open)),max(1.0,r*0.007)))
            p.drawPath(mouth_inner)
            for k in range(1, 1 + int(mouth_open*3)):
                yy = mouth_y + k*0.018
                line((-mouth_half*0.65,yy),(mouth_half*0.65,yy),100+int(100*mouth_open),0.004)

        # Chin/jaw lines move with speech and emotion.
        jaw_drop = mouth_open * 0.035
        poly([(-0.32,0.54),(-0.22,0.66-jaw_drop),(0.0,0.72-jaw_drop),
              (0.22,0.66-jaw_drop),(0.32,0.54)], 210, 0.010)
        poly([(-0.17,0.59),(-0.10,0.63),(0.0,0.64),(0.10,0.63),(0.17,0.59)],
             145, 0.007)
        line((-0.07,0.69),(0.07,0.69),170,0.006)

        # Moving horizontal scanner clips visually to the head region.
        scan_y = -0.84 + ((t * (0.68 if thinking else 0.48)) % 1.0) * 1.62
        scan_wave = math.sin(t*5.0) * 0.025
        line((-0.62,scan_y),(0.62,scan_y+scan_wave),int(90+110*pulse),0.008)
        line((-0.58,scan_y+0.018),(0.58,scan_y+0.018+scan_wave),55,0.004)

        # Traveling sparks run around the facial contour and give constant motion.
        for i in range(6):
            pos = (t*0.12 + i/6.0) % 1.0
            idxf = pos * len(moving_contour)
            idx = int(idxf) % len(moving_contour)
            frac = idxf - int(idxf)
            a = moving_contour[idx]
            b = moving_contour[(idx+1) % len(moving_contour)]
            sx = a[0] + (b[0]-a[0])*frac
            sy = a[1] + (b[1]-a[1])*frac
            node(sx, sy, 0.009 + pulse*0.003, 185)

        # Tiny status waveform below the chin changes with the assistant's state.
        status_y = 0.91
        for i in range(19):
            x = -0.22 + i*0.024
            wave = math.sin(t*5.0+i*0.72) * (0.012 + (0.035 if speaking or thinking else 0.012))
            line((x,status_y-wave),(x,status_y+wave),150 if i%3 else 235,0.005)
        p.restore()
