"""
holographic_ui.py — ARJUN Holographic UI (Complete)
Handles all gesture events from gesture_control.py:
  - molecule_zoom_in / molecule_zoom_out
  - molecule_spin
  - window_drag (pinch drag to move)
  - set_muted
  - window_minimize / window_maximize
  - scroll_chat
  - clear_history
  - stop_speaking
  - confirm_start / confirm_countdown / confirm_cancelled / confirm_executed
  - gesture_overlay (live gesture name badge)
  - state (thinking/speaking/idle → molecule + status)
"""

import sys
import queue
import logging

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QComboBox, QCheckBox,
    QSizePolicy, QMainWindow
)
from PyQt5.QtCore  import (
    Qt, QThread, pyqtSignal, QTimer,
    QPoint, QPointF, QRectF
)
from PyQt5.QtGui   import (
    QColor, QFont, QPalette, QTextCursor,
    QPainter, QBrush, QPen, QRadialGradient
)

from animations import MoleculeWidget
from config     import UI_WIDTH, UI_HEIGHT, UI_TITLE, TTS_VOICE

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  SIGNAL BRIDGE
# ─────────────────────────────────────────────

class SignalBridge(QThread):
    state_changed      = pyqtSignal(str)
    arjun_replied      = pyqtSignal(str)
    user_said          = pyqtSignal(str)
    status_updated     = pyqtSignal(str)
    gesture_detected   = pyqtSignal(str)
    confirm_start_sig  = pyqtSignal(dict)
    confirm_tick_sig   = pyqtSignal(dict)
    confirm_cancelled  = pyqtSignal()
    confirm_executed   = pyqtSignal(str)
    window_minimize    = pyqtSignal()
    window_maximize    = pyqtSignal()
    window_drag        = pyqtSignal(int, int)       # dx, dy pixels
    molecule_zoom_in   = pyqtSignal()
    molecule_zoom_out  = pyqtSignal()
    molecule_spin      = pyqtSignal(float)          # angle delta
    scroll_chat        = pyqtSignal(str)
    clear_history      = pyqtSignal()
    stop_speaking_sig  = pyqtSignal()
    set_muted          = pyqtSignal(bool)

    def __init__(self, event_queue: queue.Queue):
        super().__init__()
        self._queue   = event_queue
        self._running = True

    def run(self):
        while self._running:
            try:
                event = self._queue.get(timeout=0.1)
                kind  = event.get("type", "")
                data  = event.get("data", "")

                if   kind == "state":            self.state_changed.emit(str(data))
                elif kind == "arjun":            self.arjun_replied.emit(str(data))
                elif kind == "user":             self.user_said.emit(str(data))
                elif kind == "status":           self.status_updated.emit(str(data))
                elif kind == "gesture_overlay":  self.gesture_detected.emit(str(data))
                elif kind == "confirm_start":    self.confirm_start_sig.emit(data if isinstance(data, dict) else {})
                elif kind == "confirm_countdown":self.confirm_tick_sig.emit(data if isinstance(data, dict) else {})
                elif kind == "confirm_cancelled":self.confirm_cancelled.emit()
                elif kind == "confirm_executed": self.confirm_executed.emit(str(data))
                elif kind == "window_minimize":  self.window_minimize.emit()
                elif kind == "window_maximize":  self.window_maximize.emit()
                elif kind == "window_drag":
                    if isinstance(data, dict):
                        self.window_drag.emit(data.get("dx", 0), data.get("dy", 0))
                elif kind == "molecule_zoom_in": self.molecule_zoom_in.emit()
                elif kind == "molecule_zoom_out":self.molecule_zoom_out.emit()
                elif kind == "molecule_spin":
                    try:
                        self.molecule_spin.emit(float(data))
                    except Exception:
                        pass
                elif kind == "scroll_chat":      self.scroll_chat.emit(str(data))
                elif kind == "clear_history":    self.clear_history.emit()
                elif kind == "stop_speaking":    self.stop_speaking_sig.emit()
                elif kind == "set_muted":
                    self.set_muted.emit(bool(data))

            except queue.Empty:
                continue
            except Exception:
                logger.exception("UI event bridge failed.")

    def stop(self):
        self._running = False


# ─────────────────────────────────────────────
#  CONFIRMATION RING
# ─────────────────────────────────────────────

class ConfirmRingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setVisible(False)
        self._progress  = 0.0
        self._label     = ""
        self._remaining = 0.0
        self._total     = 2.0

    def show_confirm(self, label: str, total: float):
        self._label    = label
        self._total    = total
        self._progress = 0.0
        self.setVisible(True)
        self.update()

    def update_progress(self, remaining: float):
        self._remaining = remaining
        self._progress  = 1.0 - (remaining / self._total) if self._total > 0 else 1.0
        self.update()

    def hide_confirm(self):
        self.setVisible(False)

    def paintEvent(self, event):
        if not self.isVisible():
            return
        p  = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h   = self.width(), self.height()
        cx, cy = w // 2, h // 2
        r      = min(w, h) // 2 - 24

        p.fillRect(0, 0, w, h, QColor(0, 0, 0, 175))
        p.setPen(QPen(QColor(55, 55, 80, 180), 8))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), float(r), float(r))

        arc_c = QColor(255, int(55 + 110*self._progress), 20, 235)
        pen2  = QPen(arc_c, 8)
        pen2.setCapStyle(Qt.RoundCap)
        p.setPen(pen2)
        p.drawArc(cx-r, cy-r, r*2, r*2, 90*16, int(-360*self._progress*16))

        p.setPen(QColor(255, 200, 70))
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.drawText(QRectF(cx-r, cy-26, r*2, 22), Qt.AlignCenter, self._label[:35])

        p.setPen(QColor(255, 100, 35))
        p.setFont(QFont("Segoe UI", 20, QFont.Bold))
        p.drawText(QRectF(cx-r, cy+2, r*2, 32), Qt.AlignCenter, f"{self._remaining:.1f}s")

        p.setPen(QColor(120, 120, 145))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(cx-r, cy+r-22, r*2, 18), Qt.AlignCenter,
                   "Release gesture to cancel")
        p.end()


# ─────────────────────────────────────────────
#  GESTURE BADGE
# ─────────────────────────────────────────────

class GestureBadge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._text = "NONE"
        self.setFixedSize(185, 28)

    def set_gesture(self, name: str):
        self._text = name
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(8, 12, 26, 215)))
        p.setPen(QPen(QColor(28, 38, 70), 1))
        p.drawRoundedRect(0, 0, self.width(), self.height(), 8, 8)
        active = self._text not in ("NONE", "", "CIRCLE", "PINCH_DRAG")
        color  = QColor(0, 220, 120) if active else QColor(45, 50, 76)
        p.setPen(color)
        p.setFont(QFont("Consolas", 8, QFont.Bold))
        p.drawText(6, 18, f"✋  {self._text}")
        p.end()


# ─────────────────────────────────────────────
#  HOLOGRAPHIC WINDOW
# ─────────────────────────────────────────────

class HolographicWindow(QMainWindow):

    def __init__(self, event_queue: queue.Queue, input_queue: queue.Queue):
        super().__init__()
        self._event_queue = event_queue
        self._input_queue = input_queue
        self._drag_pos    = None
        self._mol_scale   = 1.0
        self._muted       = False
        self._chat_visible = True

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(UI_WIDTH, UI_HEIGHT)
        self.setWindowTitle(UI_TITLE)

        self._build_ui()
        self._start_bridge()

    # ── Build UI ─────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        central.setStyleSheet("""
            QWidget#central {
                background-color: rgba(10, 15, 28, 190);
                border: 1px solid rgba(0, 229, 255, 89);
                border-radius: 20px;
            }
        """)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ──
        top = QWidget()
        top.setFixedHeight(42)
        top.setStyleSheet("""
            background-color: rgba(10, 15, 28, 210);
            border-top-left-radius: 20px;
            border-top-right-radius: 20px;
            border-bottom: 1px solid rgba(0, 229, 255, 60);
        """)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 0, 14, 0)

        for color in ["#ff5f56", "#ffbd2e", "#27c93f"]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 9px;")
            tl.addWidget(dot)
        tl.addSpacing(8)

        name_lbl = QLabel("A R J U N")
        name_lbl.setStyleSheet(
            "color: #42dfff; font-size: 12px; font-weight: bold; "
            "font-family: 'Segoe UI'; letter-spacing: 4px;"
        )
        tl.addWidget(name_lbl)
        tl.addStretch()

        self.chat_toggle_btn = QPushButton("CHAT −")
        self.chat_toggle_btn.setFixedSize(58, 23)
        self.chat_toggle_btn.setStyleSheet("""
            QPushButton {
                color: rgba(120, 213, 230, 220);
                background: rgba(10, 25, 40, 170);
                border: 1px solid rgba(0, 229, 255, 75);
                border-radius: 11px;
                font: 8px 'Consolas';
            }
            QPushButton:hover { color: white; border-color: rgba(0, 229, 255, 180); }
        """)
        self.chat_toggle_btn.clicked.connect(self._toggle_chat)
        tl.addWidget(self.chat_toggle_btn)
        tl.addSpacing(8)

        self.status_lbl = QLabel("IDLE")
        self.status_lbl.setObjectName("state_badge")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setFixedSize(82, 22)
        self.status_lbl.setStyleSheet(
            "color: #71dff3; background: rgba(5, 28, 43, 210); "
            "border: 1px solid rgba(0, 229, 255, 105); border-radius: 11px; "
            "font: bold 9px 'Consolas';"
        )
        tl.addWidget(self.status_lbl)
        tl.addSpacing(10)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: rgba(90,90,115,200);
                border: none; font-size: 12px; border-radius: 11px;
            }
            QPushButton:hover { background: rgba(255,55,55,185); color: white; }
        """)
        close_btn.clicked.connect(self.close)
        tl.addWidget(close_btn)
        root.addWidget(top)

        # ── Molecule area ──
        self._mol_container = QWidget()
        self._mol_container.setFixedHeight(255)
        self._mol_container.setStyleSheet(
            "background-color: rgba(10, 15, 28, 135);"
        )

        self.molecule = MoleculeWidget(self._mol_container)
        self.molecule.setGeometry(0, 0, UI_WIDTH, 255)

        self.gesture_badge = GestureBadge(self._mol_container)
        self.gesture_badge.move(10, 8)

        self.confirm_ring = ConfirmRingWidget(self._mol_container)
        self.confirm_ring.setGeometry(0, 0, UI_WIDTH, 255)

        root.addWidget(self._mol_container)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: rgba(28, 44, 100, 115);")
        root.addWidget(sep)

        # ── Chat area ──
        self.chat_box = QTextEdit()
        self.chat_box.setReadOnly(True)
        self.chat_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.chat_box.setStyleSheet("""
            QTextEdit {
                background-color: rgba(10, 15, 28, 180);
                color: #b4c4e4;
                border: none;
                padding: 10px 14px;
                font-family: 'Segoe UI';
                font-size: 12px;
                selection-background-color: rgba(0, 95, 215, 180);
            }
            QScrollBar:vertical {
                background: rgba(8, 16, 28, 175);
                width: 5px; border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 190, 220, 125);
                border-radius: 2px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        root.addWidget(self.chat_box, stretch=1)

        # ── Input row ──
        input_row = QWidget()
        input_row.setFixedHeight(58)
        input_row.setStyleSheet("""
            background-color: rgba(10, 15, 28, 185);
            border-top: 1px solid rgba(0, 229, 255, 60);
            border-bottom-left-radius: 20px;
            border-bottom-right-radius: 20px;
        """)
        il = QHBoxLayout(input_row)
        il.setContentsMargins(12, 8, 12, 8)
        il.setSpacing(6)

        # Stop button
        self.stop_btn = QPushButton("■")
        self.stop_btn.setFixedSize(36, 36)
        self.stop_btn.setToolTip("Stop speaking (also: STOP gesture)")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(18, 22, 46, 205);
                color: rgba(195, 55, 55, 205);
                border: 1px solid rgba(38, 48, 98, 180);
                border-radius: 18px; font-size: 12px;
            }
            QPushButton:hover { background-color: rgba(175, 35, 35, 205); color: white; }
        """)
        self.stop_btn.clicked.connect(self._on_stop)

        # Mic button
        self.mic_btn = QPushButton("🎙")
        self.mic_btn.setFixedSize(36, 36)
        self.mic_btn.setToolTip("Record voice (also: PEACE gesture)")
        self.mic_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(18, 22, 46, 205);
                border: 1px solid rgba(38, 48, 98, 180);
                border-radius: 18px; font-size: 15px;
            }
            QPushButton:hover { background-color: rgba(0, 75, 195, 205); }
        """)
        self.mic_btn.clicked.connect(self._on_mic)

        self.voice_combo = QComboBox()
        self.voice_combo.addItems(["Zira", "David"])
        self.voice_combo.setCurrentText(TTS_VOICE.title())
        self.voice_combo.setFixedWidth(70)
        self.voice_combo.setToolTip("Choose the local speech voice")
        self.voice_combo.setStyleSheet("""
            QComboBox {
                color: #b4eaf3;
                background: rgba(10, 20, 36, 185);
                border: 1px solid rgba(0, 229, 255, 75);
                border-radius: 14px;
                padding: 4px 7px;
                font: 9px 'Consolas';
            }
            QComboBox QAbstractItemView {
                color: #d5e0f5;
                background: #0a0f1c;
                selection-background-color: #123b55;
            }
        """)
        self.voice_combo.currentTextChanged.connect(
            lambda name: self._input_queue.put(f"__VOICE__:{name.lower()}")
        )

        self.conversation_toggle = QCheckBox("CONV")
        self.conversation_toggle.setToolTip(
            "Keep listening for your next instruction after each reply"
        )
        self.conversation_toggle.setStyleSheet("""
            QCheckBox {
                color: #9db8d3;
                spacing: 3px;
                font: 8px 'Consolas';
            }
            QCheckBox::indicator {
                width: 13px;
                height: 13px;
                border: 1px solid rgba(0, 229, 255, 100);
                border-radius: 3px;
                background: rgba(10, 20, 36, 185);
            }
            QCheckBox::indicator:checked {
                background: #00aabe;
            }
        """)
        self.conversation_toggle.toggled.connect(
            lambda enabled: self._input_queue.put(
                "__CONVERSATION__:" + ("on" if enabled else "off")
            )
        )

        # Text input
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Type a message or say Hey Jarvis...")
        self.text_input.returnPressed.connect(self._on_send)
        self.text_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(10, 20, 36, 185);
                color: #d5e0f5;
                border: 1px solid rgba(0, 229, 255, 75);
                border-radius: 18px;
                padding: 8px 16px;
                font-family: 'Segoe UI'; font-size: 12px;
            }
            QLineEdit:focus { border: 1px solid rgba(0, 229, 255, 180); }
        """)

        # Send button
        self.send_btn = QPushButton("▶")
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 85, 195, 225);
                color: white; border: none;
                border-radius: 18px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover  { background-color: rgba(0, 115, 255, 235); }
            QPushButton:pressed { background-color: rgba(0, 55, 155, 240); }
        """)
        self.send_btn.clicked.connect(self._on_send)

        il.addWidget(self.stop_btn)
        il.addWidget(self.mic_btn)
        il.addWidget(self.voice_combo)
        il.addWidget(self.conversation_toggle)
        il.addWidget(self.text_input, stretch=1)
        il.addWidget(self.send_btn)
        root.addWidget(input_row)

    # ── Signal bridge ─────────────────────────────────────

    def _start_bridge(self):
        self._bridge = SignalBridge(self._event_queue)
        self._bridge.state_changed.connect(self._on_state)
        self._bridge.arjun_replied.connect(
            lambda t: self._append_chat("Arjun", t, "#f0a040"))
        self._bridge.user_said.connect(
            lambda t: self._append_chat("You", t, "#4499ff"))
        self._bridge.status_updated.connect(
            self._on_status_detail)
        self._bridge.gesture_detected.connect(self._on_gesture)
        self._bridge.confirm_start_sig.connect(self._on_confirm_start)
        self._bridge.confirm_tick_sig.connect(self._on_confirm_tick)
        self._bridge.confirm_cancelled.connect(self.confirm_ring.hide_confirm)
        self._bridge.confirm_executed.connect(
            lambda _: self.confirm_ring.hide_confirm())
        self._bridge.window_minimize.connect(self.showMinimized)
        self._bridge.window_maximize.connect(self.showNormal)
        self._bridge.window_drag.connect(self._on_window_drag)       # pinch drag
        self._bridge.molecule_zoom_in.connect(self._zoom_in)
        self._bridge.molecule_zoom_out.connect(self._zoom_out)
        self._bridge.molecule_spin.connect(self._on_spin)            # circle spin
        self._bridge.scroll_chat.connect(self._scroll_chat)
        self._bridge.clear_history.connect(self._clear_history)
        self._bridge.stop_speaking_sig.connect(self._on_stop)
        self._bridge.set_muted.connect(self._on_set_muted)
        self._bridge.start()

    # ── Slots ─────────────────────────────────────────────

    def _on_state(self, state: str):
        state = state.upper()
        states = {
            "THINKING": ("THINKING", "thinking"),
            "SPEAKING": ("SPEAKING", "speaking"),
            "LISTENING": ("LISTENING", "listening"),
            "PASSIVE_LISTENING": ("LISTENING", "listening"),
            "ACTIVE_LISTENING": ("LISTENING", "listening"),
            "IDLE": ("IDLE", "idle"),
            "IDLE_LISTENING": ("IDLE", "idle"),
        }
        label, mol = states.get(state, ("IDLE", "idle"))
        self.status_lbl.setText(label)
        self.molecule.set_state(mol)
        colors = {
            "THINKING": "#8bbaff",
            "SPEAKING": "#8bf2ff",
            "LISTENING": "#68f2ce",
            "PASSIVE_LISTENING": "#68f2ce",
            "ACTIVE_LISTENING": "#68f2ce",
            "IDLE": "#71dff3",
            "IDLE_LISTENING": "#71dff3",
        }
        color = colors.get(state, "#71dff3")
        self.status_lbl.setStyleSheet(
            f"color: {color}; background: rgba(5, 28, 43, 210); "
            "border: 1px solid rgba(0, 229, 255, 105); border-radius: 11px; "
            "font: bold 9px 'Consolas';"
        )

    def _on_status_detail(self, text: str):
        self.status_lbl.setToolTip(text)

    def _on_gesture(self, gesture: str):
        self.gesture_badge.set_gesture(gesture)
        self.molecule.set_gesture(gesture)

    def _toggle_chat(self):
        self._chat_visible = not self._chat_visible
        self.chat_box.setVisible(self._chat_visible)
        self.chat_toggle_btn.setText("CHAT −" if self._chat_visible else "CHAT +")

    def _on_confirm_start(self, d: dict):
        self.confirm_ring.show_confirm(
            d.get("label", "Confirm action"),
            d.get("seconds", 2.0)
        )

    def _on_confirm_tick(self, d: dict):
        self.confirm_ring.update_progress(d.get("remaining", 0.0))

    def _on_send(self):
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self._input_queue.put("__STOP__")
        self._input_queue.put(text)

    def _on_mic(self):
        self._input_queue.put("__RECORD__")
        self._on_state("ACTIVE_LISTENING")

    def _on_stop(self):
        self._input_queue.put("__STOP__")
        self._on_state("IDLE")
        self.status_lbl.setToolTip("Speech interrupted.")

    # ── Gesture-driven window drag ────────────────────────

    def _on_window_drag(self, dx: int, dy: int):
        """Move window by delta pixels — called from pinch drag gesture."""
        new_pos = self.pos() + QPoint(dx, dy)
        self.move(new_pos)

    # ── Molecule zoom ─────────────────────────────────────

    def _zoom_in(self):
        self._mol_scale = min(2.0, self._mol_scale + 0.12)
        self.molecule.set_zoom(self._mol_scale)
        self.status_lbl.setToolTip(f"Zoom {round(self._mol_scale * 100)}%")

    def _zoom_out(self):
        self._mol_scale = max(0.4, self._mol_scale - 0.12)
        self.molecule.set_zoom(self._mol_scale)
        self.status_lbl.setToolTip(f"Zoom {round(self._mol_scale * 100)}%")

    # ── Molecule spin (circle gesture) ───────────────────

    def _on_spin(self, angle_delta: float):
        """Rotate the molecule via finger circle gesture."""
        self.molecule.set_spin(angle_delta)

    # ── Mute indicator ───────────────────────────────────

    def _on_set_muted(self, muted: bool):
        self._muted = muted
        self.molecule.set_muted(muted)
        # Change mic button appearance
        if muted:
            self.mic_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(160, 30, 30, 220);
                    border: 1px solid rgba(220, 50, 50, 180);
                    border-radius: 18px; font-size: 15px;
                }
            """)
            self.mic_btn.setText("🔇")
        else:
            self.mic_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(18, 22, 46, 205);
                    border: 1px solid rgba(38, 48, 98, 180);
                    border-radius: 18px; font-size: 15px;
                }
                QPushButton:hover { background-color: rgba(0, 75, 195, 205); }
            """)
            self.mic_btn.setText("🎙")

    # ── Chat ─────────────────────────────────────────────

    def _scroll_chat(self, direction: str):
        sb    = self.chat_box.verticalScrollBar()
        delta = -100 if direction == "up" else 100
        sb.setValue(sb.value() + delta)

    def _clear_history(self):
        self.chat_box.clear()
        self._append_chat("System", "Conversation history cleared.", "#606880")

    def _append_chat(self, speaker: str, text: str, color: str):
        cursor = self.chat_box.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt = self.chat_box.currentCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setFontWeight(QFont.Bold)
        fmt.setFontPointSize(11)
        cursor.setCharFormat(fmt)
        cursor.insertText(f"{speaker}\n")

        fmt.setForeground(QColor("#b8c8e6"))
        fmt.setFontWeight(QFont.Normal)
        fmt.setFontPointSize(11)
        cursor.setCharFormat(fmt)
        cursor.insertText(f"{text}\n\n")

        self.chat_box.setTextCursor(cursor)
        self.chat_box.ensureCursorVisible()

    # ── Mouse drag fallback ───────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    # ── Close ─────────────────────────────────────────────

    def closeEvent(self, event):
        self._bridge.stop()
        self._bridge.wait(2000)
        event.accept()


# ─────────────────────────────────────────────
#  LAUNCH
# ─────────────────────────────────────────────

def launch_ui(event_queue: queue.Queue, input_queue: queue.Queue):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window,     QColor(6,  8, 18))
    palette.setColor(QPalette.WindowText, QColor(200, 210, 230))
    palette.setColor(QPalette.Base,       QColor(8,  12, 24))
    palette.setColor(QPalette.Text,       QColor(200, 210, 230))
    app.setPalette(palette)

    win = HolographicWindow(event_queue, input_queue)
    win.show()
    app.exec_()
