"""
ui.py — ARJUN Interactive Conversation Window
Opens when you talk to Arjun locally.
Shows molecule animation (thinking/speaking) + chat transcript.
Communicates with main.py via a shared queue.
"""

import sys
import queue
import threading
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QTextEdit, QLineEdit, QPushButton,
    QLabel, QSizePolicy, QFrame, QComboBox, QCheckBox
)
from PyQt5.QtCore  import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui   import QColor, QFont, QPalette, QTextCursor

from animations import MoleculeWidget
from config import UI_WIDTH, UI_HEIGHT, UI_TITLE, TTS_VOICE


# ─────────────────────────────────────────────
#  SIGNALS BRIDGE  (thread-safe Qt signal relay)
# ─────────────────────────────────────────────

class SignalBridge(QThread):
    """
    Polls a queue from main.py and emits Qt signals so the
    UI can update safely from the main thread.
    """
    state_changed   = pyqtSignal(str)        # "thinking" | "speaking" | "idle"
    arjun_replied   = pyqtSignal(str)        # Arjun's response text
    user_said       = pyqtSignal(str)        # User's transcribed text
    status_updated  = pyqtSignal(str)        # Status bar text

    def __init__(self, event_queue: queue.Queue):
        super().__init__()
        self._queue = event_queue
        self._running = True

    def run(self):
        while self._running:
            try:
                event = self._queue.get(timeout=0.1)
                kind  = event.get("type", "")
                data  = event.get("data", "")

                if kind == "state":
                    self.state_changed.emit(data)
                elif kind == "arjun":
                    self.arjun_replied.emit(data)
                elif kind == "user":
                    self.user_said.emit(data)
                elif kind == "status":
                    self.status_updated.emit(data)

            except queue.Empty:
                continue

    def stop(self):
        self._running = False


# ─────────────────────────────────────────────
#  MAIN WINDOW
# ─────────────────────────────────────────────

class ArjunWindow(QMainWindow):

    # Signal to send user text back to main.py
    user_input_ready = pyqtSignal(str)

    def __init__(self, event_queue: queue.Queue, input_queue: queue.Queue):
        super().__init__()
        self._event_queue = event_queue   # main.py → UI
        self._input_queue = input_queue   # UI → main.py

        self.setWindowTitle(UI_TITLE)
        self.setFixedSize(UI_WIDTH, UI_HEIGHT)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self._apply_dark_theme()
        self._build_ui()
        self._start_bridge()

    # ── Theme ────────────────────────────────────────────

    def _apply_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window,          QColor(10, 12, 20))
        palette.setColor(QPalette.WindowText,      QColor(220, 220, 230))
        palette.setColor(QPalette.Base,            QColor(16, 18, 30))
        palette.setColor(QPalette.AlternateBase,   QColor(20, 22, 36))
        palette.setColor(QPalette.Text,            QColor(210, 215, 230))
        palette.setColor(QPalette.Button,          QColor(30, 34, 55))
        palette.setColor(QPalette.ButtonText,      QColor(220, 220, 240))
        palette.setColor(QPalette.Highlight,       QColor(0, 150, 255))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        self.setPalette(palette)
        self.setStyleSheet("""
            QMainWindow { background-color: #0a0c14; }
            QTextEdit {
                background-color: #10121e;
                color: #d2d7e6;
                border: 1px solid #1e2240;
                border-radius: 8px;
                padding: 10px;
                font-family: 'Segoe UI', Arial;
                font-size: 13px;
                selection-background-color: #0096ff;
            }
            QLineEdit {
                background-color: #141828;
                color: #e0e4f0;
                border: 1px solid #2a3060;
                border-radius: 20px;
                padding: 10px 18px;
                font-family: 'Segoe UI', Arial;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #0096ff;
            }
            QPushButton#send_btn {
                background-color: #0066cc;
                color: white;
                border: none;
                border-radius: 20px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton#send_btn:hover  { background-color: #0080ff; }
            QPushButton#send_btn:pressed { background-color: #0050aa; }
            QPushButton#mic_btn {
                background-color: #1a1e30;
                color: #aab0cc;
                border: 1px solid #2a3060;
                border-radius: 20px;
                padding: 10px 16px;
                font-size: 13px;
            }
            QPushButton#mic_btn:hover { background-color: #252a42; }
            QLabel#status_label {
                color: #5a6090;
                font-size: 11px;
                font-family: 'Segoe UI';
            }
            QLabel#name_label {
                color: #0096ff;
                font-size: 15px;
                font-weight: bold;
                font-family: 'Segoe UI';
                letter-spacing: 2px;
            }
        """)

    # ── Build UI ─────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Top bar ──
        top_bar = QWidget()
        top_bar.setFixedHeight(50)
        top_bar.setStyleSheet("background-color: #0d0f1c; border-bottom: 1px solid #1a1e30;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(20, 0, 20, 0)

        name_label = QLabel("ARJUN")
        name_label.setObjectName("name_label")
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status_label")

        top_layout.addWidget(name_label)
        top_layout.addStretch()
        top_layout.addWidget(self.status_label)
        root_layout.addWidget(top_bar)

        # ── Molecule animation area ──
        self.molecule = MoleculeWidget()
        self.molecule.setFixedHeight(260)
        self.molecule.setStyleSheet("background-color: #08090f;")
        root_layout.addWidget(self.molecule)

        # ── Divider ──
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("border: 1px solid #1a1e30;")
        root_layout.addWidget(divider)

        # ── Chat transcript ──
        self.chat_box = QTextEdit()
        self.chat_box.setReadOnly(True)
        self.chat_box.setMinimumHeight(200)
        self.chat_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root_layout.addWidget(self.chat_box, stretch=1)

        # ── Input row ──
        input_row = QWidget()
        input_row.setFixedHeight(66)
        input_row.setStyleSheet("background-color: #0d0f1c; border-top: 1px solid #1a1e30;")
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(14, 10, 14, 10)
        input_layout.setSpacing(8)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Type a message or press the mic…")
        self.text_input.returnPressed.connect(self._on_send)

        self.mic_btn  = QPushButton("🎙")
        self.mic_btn.setObjectName("mic_btn")
        self.mic_btn.setFixedWidth(46)
        self.mic_btn.clicked.connect(self._on_mic)

        self.stop_btn = QPushButton("■")
        self.stop_btn.setFixedWidth(36)
        self.stop_btn.setToolTip("Stop speaking")
        self.stop_btn.clicked.connect(self._on_stop)

        self.voice_combo = QComboBox()
        self.voice_combo.addItems(["Zira", "David"])
        self.voice_combo.setCurrentText(TTS_VOICE.title())
        self.voice_combo.setFixedWidth(72)
        self.voice_combo.setToolTip("Choose the local speech voice")
        self.voice_combo.currentTextChanged.connect(
            lambda name: self._input_queue.put(f"__VOICE__:{name.lower()}")
        )

        self.conversation_toggle = QCheckBox("Conv")
        self.conversation_toggle.setToolTip(
            "Keep listening for your next instruction after each reply"
        )
        self.conversation_toggle.toggled.connect(
            lambda enabled: self._input_queue.put(
                "__CONVERSATION__:" + ("on" if enabled else "off")
            )
        )

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("send_btn")
        self.send_btn.setFixedWidth(72)
        self.send_btn.clicked.connect(self._on_send)

        input_layout.addWidget(self.mic_btn)
        input_layout.addWidget(self.stop_btn)
        input_layout.addWidget(self.voice_combo)
        input_layout.addWidget(self.conversation_toggle)
        input_layout.addWidget(self.text_input, stretch=1)
        input_layout.addWidget(self.send_btn)
        root_layout.addWidget(input_row)

    # ── Signal bridge ────────────────────────────────────

    def _start_bridge(self):
        self._bridge = SignalBridge(self._event_queue)
        self._bridge.state_changed.connect(self._on_state_change)
        self._bridge.arjun_replied.connect(self._on_arjun_reply)
        self._bridge.user_said.connect(self._on_user_said)
        self._bridge.status_updated.connect(self._on_status_update)
        self._bridge.start()

    # ── Slots ────────────────────────────────────────────

    def _on_state_change(self, state: str):
        state = state.lower()
        self.molecule.set_state(state if state != "idle" else "thinking")
        if state == "thinking":
            self.status_label.setText("Thinking…")
            self.molecule.set_state("thinking")
        elif state == "speaking":
            self.status_label.setText("Speaking…")
            self.molecule.set_state("speaking")
        elif state in ("listening", "passive_listening", "active_listening"):
            self.status_label.setText("Listening…")
            self.molecule.set_state("listening")
        else:
            self.status_label.setText("Ready")
            self.molecule.set_state("idle")

    def _on_arjun_reply(self, text: str):
        self._append_chat("Arjun", text, color="#f0a040")

    def _on_user_said(self, text: str):
        self._append_chat("You", text, color="#60b8ff")

    def _on_status_update(self, text: str):
        self.status_label.setText(text)

    def _on_send(self):
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self._input_queue.put("__STOP__")
        self._append_chat("You", text, color="#60b8ff")
        self._input_queue.put(text)

    def _on_mic(self):
        # Signal main.py to start voice recording
        self._input_queue.put("__RECORD__")
        self.status_label.setText("Listening…")

    def _on_stop(self):
        self._input_queue.put("__STOP__")
        self.status_label.setText("Ready")
        self.molecule.set_state("idle")

    def _append_chat(self, speaker: str, text: str, color: str = "#ffffff"):
        cursor = self.chat_box.textCursor()
        cursor.movePosition(QTextCursor.End)

        # Speaker label
        fmt_name = self.chat_box.currentCharFormat()
        fmt_name.setForeground(QColor(color))
        fmt_name.setFontWeight(700)
        fmt_name.setFontPointSize(12)
        cursor.setCharFormat(fmt_name)
        cursor.insertText(f"{speaker}\n")

        # Message body
        fmt_body = self.chat_box.currentCharFormat()
        fmt_body.setForeground(QColor("#d2d7e6"))
        fmt_body.setFontWeight(400)
        fmt_body.setFontPointSize(12)
        cursor.setCharFormat(fmt_body)
        cursor.insertText(f"{text}\n\n")

        self.chat_box.setTextCursor(cursor)
        self.chat_box.ensureCursorVisible()

    # ── Close ────────────────────────────────────────────

    def closeEvent(self, event):
        self._bridge.stop()
        self._bridge.wait()
        event.accept()


# ─────────────────────────────────────────────
#  PUBLIC LAUNCHER
# ─────────────────────────────────────────────

def launch_ui(event_queue: queue.Queue, input_queue: queue.Queue) -> ArjunWindow:
    """
    Call this from a thread in main.py.
    Creates the QApplication and window, runs the event loop.
    Blocks until the window is closed.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    win = ArjunWindow(event_queue, input_queue)
    win.show()
    app.exec_()
    return win
