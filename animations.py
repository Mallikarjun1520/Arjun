"""Low-cost, transparent neural-orb animation for ARJUN's HUD."""

import math

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QRadialGradient,
)
from PyQt5.QtWidgets import QWidget


_STATE_COLORS = {
    "idle": QColor(0, 174, 218),
    "listening": QColor(0, 229, 200),
    "thinking": QColor(0, 150, 255),
    "speaking": QColor(78, 198, 255),
}


class MoleculeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(260, 220)

        self.state = "idle"
        self.tick = 0
        self._zoom = 1.0
        self._spin_angle = 0.0
        self._muted = False
        self._gesture = ""
        self._color = QColor(_STATE_COLORS["idle"])
        self._nodes, self._bonds = self._make_orb(54)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    @staticmethod
    def _make_orb(count):
        nodes = []
        golden_angle = math.pi * (3.0 - math.sqrt(5.0))
        for i in range(count):
            y = 1.0 - 2.0 * (i + 0.5) / count
            radius = math.sqrt(1.0 - y * y)
            angle = golden_angle * i
            nodes.append((radius * math.cos(angle), y, radius * math.sin(angle)))

        bonds = []
        for i, first in enumerate(nodes):
            for j in range(i + 1, count):
                second = nodes[j]
                distance = sum((first[k] - second[k]) ** 2 for k in range(3))
                if distance < 0.19:
                    bonds.append((i, j))
        return nodes, bonds

    def set_state(self, state: str):
        aliases = {
            "PASSIVE_LISTENING": "listening",
            "ACTIVE_LISTENING": "listening",
        }
        state = aliases.get(state, state.lower())
        self.state = state if state in _STATE_COLORS else "idle"
        self.update()

    def set_zoom(self, scale: float):
        self._zoom = max(0.4, min(2.2, scale))
        self.update()

    def set_spin(self, angle_delta: float):
        self._spin_angle += angle_delta
        self.update()

    def set_muted(self, muted: bool):
        self._muted = muted
        self.update()

    def set_gesture(self, gesture: str):
        self._gesture = gesture
        self.update()

    def _tick(self):
        self.tick += 1
        target = _STATE_COLORS[self.state]
        self._color = QColor(
            round(self._color.red() + (target.red() - self._color.red()) * 0.12),
            round(self._color.green() + (target.green() - self._color.green()) * 0.12),
            round(self._color.blue() + (target.blue() - self._color.blue()) * 0.12),
        )
        self.update()

    def _project_nodes(self, cx, cy, radius):
        yaw = self.tick * 0.008 + self._spin_angle
        pitch = 0.32 + math.sin(self.tick * 0.005) * 0.12
        cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
        cos_pitch, sin_pitch = math.cos(pitch), math.sin(pitch)
        breathing = 1.0 + 0.025 * math.sin(self.tick * 0.055)
        points = []
        for x, y, z in self._nodes:
            rx = x * cos_yaw - z * sin_yaw
            rz = x * sin_yaw + z * cos_yaw
            ry = y * cos_pitch - rz * sin_pitch
            depth = y * sin_pitch + rz * cos_pitch
            scale = (0.82 + depth * 0.2) * radius * breathing * self._zoom
            points.append((cx + rx * scale, cy + ry * scale, depth))
        return points

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setCompositionMode(QPainter.CompositionMode_Plus)

        width, height = self.width(), self.height()
        cx, cy = width / 2.0, height / 2.0
        radius = min(width, height) * 0.36
        points = self._project_nodes(cx, cy, radius)
        pulse = (math.sin(self.tick * (0.16 if self.state == "speaking" else 0.045)) + 1) / 2
        core_radius = 18 + 4 * pulse if self.state == "speaking" else 15 + 2 * pulse

        glow = QRadialGradient(cx, cy, radius * 1.9)
        glow.setColorAt(0.0, QColor(self._color.red(), self._color.green(), self._color.blue(), 50))
        glow.setColorAt(0.48, QColor(self._color.red(), self._color.green(), self._color.blue(), 16))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(QPointF(cx, cy), radius * 1.9, radius * 1.9)

        for ring_index in range(3):
            ring_radius = radius * (0.72 + ring_index * 0.17)
            alpha = 34 - ring_index * 8
            pen = QPen(QColor(self._color.red(), self._color.green(), self._color.blue(), alpha), 1)
            pen.setStyle(Qt.DotLine if ring_index == 1 else Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), ring_radius, ring_radius * 0.78)

        for first, second in self._bonds:
            x1, y1, z1 = points[first]
            x2, y2, z2 = points[second]
            depth = (z1 + z2) / 2
            alpha = max(14, min(110, int(38 + (depth + 1) * 34)))
            if self.state == "thinking" and (first + second + self.tick // 3) % 11 == 0:
                alpha = min(210, alpha + 90)
            painter.setPen(QPen(QColor(self._color.red(), self._color.green(), self._color.blue(), alpha), 0.8))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        for x, y, depth in sorted(points, key=lambda point: point[2]):
            node_radius = 1.4 + (depth + 1) * 1.35
            alpha = int(95 + (depth + 1) * 78)
            color = QColor(self._color.red(), self._color.green(), self._color.blue(), alpha)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPointF(x, y), node_radius, node_radius)

        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        core = QRadialGradient(cx, cy, core_radius * 3.2)
        core.setColorAt(0.0, QColor(238, 255, 255, 235))
        core.setColorAt(0.18, QColor(self._color.red(), self._color.green(), self._color.blue(), 220))
        core.setColorAt(0.58, QColor(self._color.red(), self._color.green(), self._color.blue(), 75))
        core.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(core))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), core_radius * 3.2, core_radius * 3.2)

        if self.state == "speaking":
            painter.setCompositionMode(QPainter.CompositionMode_Plus)
            for index in range(3):
                phase = (self.tick * 0.035 + index / 3.0) % 1.0
                ring_radius = core_radius * 1.8 + phase * radius * 0.95
                alpha = int(125 * (1.0 - phase))
                pen = QPen(QColor(48, 225, 255, alpha), 1.4)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), ring_radius, ring_radius * 0.74)

        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setPen(QPen(QColor(110, 233, 255, 120), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), core_radius * 0.62, core_radius * 0.62)

        if self._muted:
            painter.setPen(QColor(255, 110, 110))
            painter.setFont(QFont("Consolas", 9, QFont.Bold))
            painter.drawText(QRectF(width - 62, 10, 52, 18), Qt.AlignRight, "MIC OFF")
        if self._gesture and self._gesture != "NONE":
            painter.setPen(QColor(80, 226, 255, 210))
            painter.setFont(QFont("Consolas", 8, QFont.Bold))
            painter.drawText(QRectF(8, height - 23, width - 16, 16), Qt.AlignLeft, self._gesture)
        painter.end()
