"""
gesture_control.py — ARJUN Complete Gesture Control
Every gesture from the original specification implemented.

WINDOW CONTROL:
  Pinch + drag         → Move window anywhere on screen
  Fist                 → Minimize window
  Open palm            → Maximize window

MOLECULE:
  Two fingers spread   → Zoom molecule in
  Two fingers pinch    → Zoom molecule out
  Index finger circle  → Spin molecule manually

CONVERSATION:
  Stop signal          → Pause/interrupt speech
  Swipe left           → Scroll chat backward
  Swipe right          → Scroll chat forward
  Both palms (hold 2s) → Clear history (destructive — confirms)
  Wave                 → Greeting + status report

VOICE:
  Two fingers up hold  → Trigger voice recording (Hey Arjun equivalent)
  Thumb sideways hold  → Toggle microphone mute

APP SHORTCUTS:
  One finger           → Open Chrome
  Three fingers        → Open File Explorer
  Four fingers         → Open Spotify

MOLECULE STATE:
  Thumbs up            → Switch molecule to speaking/orange
  Thumbs down          → Switch molecule to thinking/blue
"""

import time
import math
import queue
import logging
import threading
from enum import Enum, auto
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    import mediapipe as mp
    MP_AVAILABLE = True
except ImportError:
    MP_AVAILABLE = False
    logger.warning("MediaPipe not installed. Gesture control disabled.")

from config import (
    GESTURE_CAMERA_INDEX, GESTURE_HOLD_SECONDS,
    GESTURE_CONFIRM_SECONDS, GESTURE_COOLDOWN,
    GESTURE_MIN_CONFIDENCE, GESTURE_APP_SHORTCUTS
)


# ─────────────────────────────────────────────
#  GESTURE ENUM
# ─────────────────────────────────────────────

class Gesture(Enum):
    NONE            = auto()
    FIST            = auto()   # minimize
    OPEN_PALM       = auto()   # maximize
    PINCH           = auto()   # zoom out / grab window
    PEACE           = auto()   # two fingers up = voice trigger
    ONE_FINGER      = auto()   # open Chrome
    THREE_FINGERS   = auto()   # open File Explorer
    FOUR_FINGERS    = auto()   # open Spotify
    THUMBS_UP       = auto()   # speaking mode
    THUMBS_DOWN     = auto()   # thinking mode
    THUMB_SIDEWAYS  = auto()   # mute toggle
    STOP            = auto()   # pause speech
    SWIPE_LEFT      = auto()   # scroll up
    SWIPE_RIGHT     = auto()   # scroll down
    BOTH_PALMS      = auto()   # clear history (destructive)
    WAVE            = auto()   # greeting / status
    SPREAD          = auto()   # zoom in
    CIRCLE          = auto()   # spin molecule
    PINCH_DRAG      = auto()   # move window


# Destructive gestures require 2-second confirmation hold
DESTRUCTIVE_GESTURES = {Gesture.BOTH_PALMS}
DESTRUCTIVE_LABELS   = {
    Gesture.BOTH_PALMS: "Clear all conversation history"
}


# ─────────────────────────────────────────────
#  LANDMARK HELPERS
# ─────────────────────────────────────────────

def _dist2d(a, b) -> float:
    return math.sqrt((a.x - b.x)**2 + (a.y - b.y)**2)

def _dist3d(a, b) -> float:
    return math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2 + (a.z-b.z)**2)

def _finger_up(lm, tip: int, mcp: int) -> bool:
    """True if finger tip is clearly above its MCP joint."""
    return lm[tip].y < lm[mcp].y - 0.025

def _thumb_right(lm) -> bool:
    return lm[4].x > lm[3].x + 0.02

def _thumb_left(lm) -> bool:
    return lm[4].x < lm[3].x - 0.02

def _thumb_up(lm) -> bool:
    return lm[4].y < lm[3].y - 0.04

def _thumb_down(lm) -> bool:
    return lm[4].y > lm[3].y + 0.04

def _classify(lm, handedness: str) -> Gesture:
    """
    Classify hand landmarks into a Gesture.
    Uses MCP joints for more reliable detection on built-in webcams.
    """
    # Finger extension
    index  = _finger_up(lm, 8,  5)
    middle = _finger_up(lm, 12, 9)
    ring   = _finger_up(lm, 16, 13)
    pinky  = _finger_up(lm, 20, 17)
    up_count = sum([index, middle, ring, pinky])

    # Thumb
    if handedness == "Right":
        thumb_ext = _thumb_left(lm)
        thumb_side = _thumb_right(lm)
    else:
        thumb_ext = _thumb_right(lm)
        thumb_side = _thumb_left(lm)

    thumb_pointing_up   = _thumb_up(lm)
    thumb_pointing_down = _thumb_down(lm)

    # ── Fist ──
    if up_count == 0 and not thumb_ext:
        return Gesture.FIST

    # ── Thumbs up / down ──
    if up_count == 0 and thumb_pointing_up:
        return Gesture.THUMBS_UP
    if up_count == 0 and thumb_pointing_down:
        return Gesture.THUMBS_DOWN

    # ── Thumb sideways (mute) ──
    if up_count == 0 and thumb_side:
        return Gesture.THUMB_SIDEWAYS

    # ── Open palm / stop ──
    if up_count == 4 and thumb_ext:
        spread = _dist2d(lm[8], lm[12])
        if spread > 0.07:
            return Gesture.STOP
        return Gesture.OPEN_PALM

    # ── Four fingers no thumb ──
    if up_count == 4 and not thumb_ext:
        return Gesture.FOUR_FINGERS

    # ── Three fingers ──
    if index and middle and ring and not pinky:
        return Gesture.THREE_FINGERS

    # ── Two fingers (peace / voice trigger) ──
    if index and middle and not ring and not pinky:
        gap = _dist2d(lm[8], lm[12])
        if gap > 0.09:
            return Gesture.SPREAD
        return Gesture.PEACE

    # ── One finger ──
    if index and not middle and not ring and not pinky:
        return Gesture.ONE_FINGER

    # ── Pinch (thumb + index close) ──
    if _dist2d(lm[4], lm[8]) < 0.055:
        return Gesture.PINCH

    return Gesture.NONE


# ─────────────────────────────────────────────
#  CIRCLE DETECTOR
# ─────────────────────────────────────────────

class CircleDetector:
    """
    Detects a circular motion from index finger tip trajectory.
    Returns the angular progress around the circle (0 → 2pi).
    """
    def __init__(self, window: float = 1.5, min_radius: float = 0.08):
        self._history  = []   # list of (x, y, time)
        self._window   = window
        self._min_r    = min_radius
        self._last_angle = None

    def update(self, x: float, y: float) -> float:
        """
        Feed the current index finger tip position.
        Returns angle delta if circle motion detected, else 0.
        """
        now = time.time()
        self._history.append((x, y, now))
        self._history = [(px, py, pt) for px, py, pt in self._history
                         if now - pt < self._window]

        if len(self._history) < 8:
            return 0.0

        # Find centroid
        cx = sum(p[0] for p in self._history) / len(self._history)
        cy = sum(p[1] for p in self._history) / len(self._history)

        # Check if points are roughly circular
        radii = [math.sqrt((p[0]-cx)**2 + (p[1]-cy)**2) for p in self._history]
        avg_r = sum(radii) / len(radii)

        if avg_r < self._min_r:
            return 0.0

        variance = sum((r - avg_r)**2 for r in radii) / len(radii)
        if variance > (avg_r * 0.5)**2:
            return 0.0   # Not circular enough

        # Compute angular velocity
        if len(self._history) >= 2:
            p1 = self._history[-2]
            p2 = self._history[-1]
            a1 = math.atan2(p1[1] - cy, p1[0] - cx)
            a2 = math.atan2(p2[1] - cy, p2[0] - cx)
            delta = a2 - a1
            # Wrap to -pi..pi
            if delta > math.pi:
                delta -= 2 * math.pi
            elif delta < -math.pi:
                delta += 2 * math.pi
            return delta

        return 0.0

    def reset(self):
        self._history = []


# ─────────────────────────────────────────────
#  WAVE DETECTOR
# ─────────────────────────────────────────────

class WaveDetector:
    """
    Detects a side-to-side wave gesture from wrist X position.
    Requires at least 2 direction reversals within 1.5 seconds.
    """
    def __init__(self):
        self._positions  = []
        self._reversals  = 0
        self._last_dir   = 0
        self._last_wave  = 0.0

    def update(self, x: float) -> bool:
        now = time.time()
        self._positions.append((x, now))
        self._positions = [(px, pt) for px, pt in self._positions
                           if now - pt < 1.5]

        if len(self._positions) < 4:
            return False

        # Detect direction reversals
        xs = [p[0] for p in self._positions]
        reversals = 0
        for i in range(1, len(xs) - 1):
            if (xs[i] - xs[i-1]) * (xs[i+1] - xs[i]) < -0.001:
                reversals += 1

        if reversals >= 2 and now - self._last_wave > 2.0:
            self._last_wave = now
            self._positions = []
            return True

        return False


# ─────────────────────────────────────────────
#  PINCH DRAG TRACKER
# ─────────────────────────────────────────────

class PinchDragTracker:
    """
    Tracks pinch gesture for window dragging.
    Returns screen-space delta (dx, dy) while pinch is held.
    """
    def __init__(self, screen_w: int, screen_h: int):
        self._screen_w    = screen_w
        self._screen_h    = screen_h
        self._pinch_start = None   # (norm_x, norm_y)
        self._active      = False

    def update(self, gesture: Gesture, index_tip, thumb_tip) -> Optional[Tuple[int, int]]:
        """
        Returns (dx, dy) in pixels if dragging, else None.
        """
        if gesture != Gesture.PINCH:
            if self._active:
                self._active      = False
                self._pinch_start = None
            return None

        # Midpoint of pinch
        mx = (index_tip.x + thumb_tip.x) / 2
        my = (index_tip.y + thumb_tip.y) / 2

        if not self._active:
            self._active      = True
            self._pinch_start = (mx, my)
            return None

        dx = int((mx - self._pinch_start[0]) * self._screen_w)
        dy = int((my - self._pinch_start[1]) * self._screen_h)
        self._pinch_start = (mx, my)   # rolling delta

        if abs(dx) < 2 and abs(dy) < 2:
            return None   # filter tiny jitter

        return (dx, dy)


# ─────────────────────────────────────────────
#  GESTURE CONTROLLER
# ─────────────────────────────────────────────

class GestureController:

    def __init__(self, ui_event_queue: queue.Queue):
        self._queue      = ui_event_queue
        self._callbacks: Dict[Gesture, Callable] = {}
        self._running    = False
        self._thread: Optional[threading.Thread] = None

        # State
        self._current    = Gesture.NONE
        self._start_time = 0.0
        self._last_fired: Dict[Gesture, float] = {}
        self._confirm_g  = None
        self._confirm_t  = 0.0
        self._hand_list  = []

        # Special trackers
        self._circle_det = CircleDetector()
        self._wave_det   = WaveDetector()
        self._swipe_pos  = []
        self._pinch_drag: Optional[PinchDragTracker] = None
        self._muted      = False

        # Timing (tuned for built-in webcam)
        self._hold_time    = max(0.4, GESTURE_HOLD_SECONDS)
        self._cooldown     = max(1.0, GESTURE_COOLDOWN)
        self._confirm_time = GESTURE_CONFIRM_SECONDS

    def on_gesture(self, gesture: Gesture, callback: Callable):
        self._callbacks[gesture] = callback

    def start(self):
        if not MP_AVAILABLE:
            logger.warning("MediaPipe not available — gesture control disabled.")
            return
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Gesture controller started.")

    def stop(self):
        self._running = False

    # ── Main loop ─────────────────────────────────────────

    def _run(self):
        mp_hands = mp.solutions.hands
        hands    = mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=max(0.55, GESTURE_MIN_CONFIDENCE),
            min_tracking_confidence=0.5
        )

        cap = cv2.VideoCapture(GESTURE_CAMERA_INDEX)
        if not cap.isOpened():
            logger.error("Could not open webcam for gesture control.")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS,          30)

        # Get screen resolution for pinch drag
        try:
            import ctypes
            user32 = ctypes.windll.user32
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
        except Exception:
            sw, sh = 1920, 1080

        self._pinch_drag = PinchDragTracker(sw, sh)

        logger.info("Gesture camera active.")

        while self._running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            frame = cv2.flip(frame, 1)
            rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = hands.process(rgb)
            rgb.flags.writeable = True

            self._hand_list   = []
            frame_gesture     = Gesture.NONE
            primary_lm        = None

            if results.multi_hand_landmarks and results.multi_handedness:
                for lm_obj, hand_info in zip(
                    results.multi_hand_landmarks,
                    results.multi_handedness
                ):
                    handedness = hand_info.classification[0].label
                    lm         = lm_obj.landmark
                    g          = _classify(lm, handedness)
                    self._hand_list.append(g)

                    if primary_lm is None:
                        primary_lm = lm

                # Both-palms check
                if len(self._hand_list) == 2:
                    both_open = all(
                        h in (Gesture.OPEN_PALM, Gesture.STOP, Gesture.FOUR_FINGERS)
                        for h in self._hand_list
                    )
                    frame_gesture = Gesture.BOTH_PALMS if both_open else self._hand_list[0]
                elif self._hand_list:
                    frame_gesture = self._hand_list[0]

                # ── Special continuous gesture handling ──

                if primary_lm is not None:
                    wrist_x = primary_lm[0].x
                    wrist_y = primary_lm[0].y

                    # ── Swipe detection ──
                    now = time.time()
                    self._swipe_pos.append((wrist_x, now))
                    self._swipe_pos = [(x, t) for x, t in self._swipe_pos
                                       if now - t < 0.45]

                    if len(self._swipe_pos) >= 7:
                        dx = self._swipe_pos[-1][0] - self._swipe_pos[0][0]
                        if dx > 0.22:
                            frame_gesture   = Gesture.SWIPE_RIGHT
                            self._swipe_pos = []
                        elif dx < -0.22:
                            frame_gesture   = Gesture.SWIPE_LEFT
                            self._swipe_pos = []

                    # ── Wave detection ──
                    if frame_gesture == Gesture.OPEN_PALM:
                        if self._wave_det.update(wrist_x):
                            frame_gesture = Gesture.WAVE

                    # ── Circle spin detection (one finger) ──
                    if frame_gesture == Gesture.ONE_FINGER:
                        index_tip  = primary_lm[8]
                        angle_delta = self._circle_det.update(index_tip.x, index_tip.y)
                        if abs(angle_delta) > 0.02:
                            # Send spin event directly — no hold timer
                            self._queue.put({
                                "type": "molecule_spin",
                                "data": angle_delta * 2.0
                            })
                            # Don't treat as one_finger tap while spinning
                            if abs(angle_delta) > 0.05:
                                frame_gesture = Gesture.CIRCLE
                    else:
                        self._circle_det.reset()

                    # ── Pinch drag — window movement ──
                    if frame_gesture == Gesture.PINCH and primary_lm:
                        drag = self._pinch_drag.update(
                            frame_gesture,
                            primary_lm[8],
                            primary_lm[4]
                        )
                        if drag:
                            self._queue.put({
                                "type": "window_drag",
                                "data": {"dx": drag[0], "dy": drag[1]}
                            })
                            frame_gesture = Gesture.PINCH_DRAG
                    elif primary_lm:
                        self._pinch_drag.update(Gesture.NONE, primary_lm[8], primary_lm[4])

            else:
                # No hands — reset trackers
                self._circle_det.reset()
                self._pinch_drag.update(Gesture.NONE,
                                        type('obj', (object,), {'x': 0, 'y': 0})(),
                                        type('obj', (object,), {'x': 0, 'y': 0})())

            # Send overlay
            self._queue.put({
                "type": "gesture_overlay",
                "data": frame_gesture.name
            })

            self._process(frame_gesture)
            time.sleep(0.030)

        cap.release()
        hands.close()

    # ── Gesture processing with hold timer ────────────────

    def _process(self, gesture: Gesture):
        now = time.time()

        # Handle pending destructive confirmation
        if self._confirm_g is not None:
            elapsed   = now - self._confirm_t
            remaining = self._confirm_time - elapsed

            if remaining > 0:
                self._queue.put({
                    "type": "confirm_countdown",
                    "data": {
                        "gesture":   self._confirm_g.name,
                        "label":     DESTRUCTIVE_LABELS.get(self._confirm_g, ""),
                        "remaining": round(remaining, 1)
                    }
                })
                if gesture != self._confirm_g:
                    logger.info(f"Destructive cancelled: {self._confirm_g.name}")
                    self._queue.put({"type": "confirm_cancelled", "data": ""})
                    self._confirm_g = None
                return
            else:
                logger.info(f"Destructive confirmed: {self._confirm_g.name}")
                self._queue.put({"type": "confirm_executed", "data": self._confirm_g.name})
                self._fire(self._confirm_g)
                self._last_fired[self._confirm_g] = now
                self._confirm_g = None
                return

        if gesture in (Gesture.SWIPE_LEFT, Gesture.SWIPE_RIGHT):
            if now - self._last_fired.get(gesture, 0) >= self._cooldown:
                self._fire(gesture)
                self._last_fired[gesture] = now
            self._current = Gesture.NONE
            return

        # Skip continuous gestures from the hold timer.
        if gesture in (Gesture.CIRCLE, Gesture.PINCH_DRAG):
            return

        # Cooldown
        if now - self._last_fired.get(gesture, 0) < self._cooldown:
            return

        # Hold timer
        if gesture == self._current and gesture != Gesture.NONE:
            held = now - self._start_time
            if held >= self._hold_time:
                if gesture in DESTRUCTIVE_GESTURES:
                    self._confirm_g = gesture
                    self._confirm_t = now
                    logger.info(f"Destructive started: {gesture.name}")
                    self._queue.put({
                        "type": "confirm_start",
                        "data": {
                            "gesture": gesture.name,
                            "label":   DESTRUCTIVE_LABELS.get(gesture, ""),
                            "seconds": self._confirm_time
                        }
                    })
                else:
                    self._fire(gesture)
                    self._last_fired[gesture] = now
                self._current = Gesture.NONE

        elif gesture != self._current:
            self._current    = gesture
            self._start_time = now

    def _fire(self, gesture: Gesture):
        cb = self._callbacks.get(gesture)
        if cb:
            try:
                threading.Thread(target=cb, daemon=True).start()
                logger.info(f"Gesture fired: {gesture.name}")
            except Exception as e:
                logger.error(f"Gesture callback error {gesture.name}: {e}")


# ─────────────────────────────────────────────
#  WIRE ALL GESTURES
# ─────────────────────────────────────────────

def wire_gestures(
    controller:      GestureController,
    ui_event_queue:  queue.Queue,
    ui_input_queue:  queue.Queue,
    recording_flag
):
    """
    Register every gesture from the original specification.
    """

    def _speak(text: str):
        from voice import speak
        threading.Thread(target=speak, args=(text,), daemon=True).start()

    def _launch_app(name: str):
        from app_launcher import launch_app
        result = launch_app(name)
        ui_event_queue.put({"type": "status", "data": result})
        _speak(result)

    # ── WINDOW CONTROL ────────────────────────────────────

    # Fist → minimize
    controller.on_gesture(
        Gesture.FIST,
        lambda: ui_event_queue.put({"type": "window_minimize", "data": ""})
    )

    # Open palm → maximize
    controller.on_gesture(
        Gesture.OPEN_PALM,
        lambda: ui_event_queue.put({"type": "window_maximize", "data": ""})
    )

    # Pinch drag is handled directly in the gesture loop via "window_drag" event
    # The UI reads window_drag and moves itself

    # ── MOLECULE ZOOM ─────────────────────────────────────

    # Two fingers spread → zoom in
    controller.on_gesture(
        Gesture.SPREAD,
        lambda: ui_event_queue.put({"type": "molecule_zoom_in", "data": ""})
    )

    # Pinch (when not dragging) → zoom out
    # Note: pinch drag takes priority; if not dragging it zooms out
    controller.on_gesture(
        Gesture.PINCH,
        lambda: ui_event_queue.put({"type": "molecule_zoom_out", "data": ""})
    )

    # Circle spin is handled directly via "molecule_spin" event in the loop

    # ── CONVERSATION CONTROL ──────────────────────────────

    # Stop signal (open palm with spread fingers) → interrupt speech
    controller.on_gesture(
        Gesture.STOP,
        lambda: ui_input_queue.put("__STOP__")
    )

    # Swipe left → scroll chat backward
    controller.on_gesture(
        Gesture.SWIPE_LEFT,
        lambda: ui_event_queue.put({"type": "scroll_chat", "data": "up"})
    )

    # Swipe right → scroll chat forward
    controller.on_gesture(
        Gesture.SWIPE_RIGHT,
        lambda: ui_event_queue.put({"type": "scroll_chat", "data": "down"})
    )

    # Both palms → clear history (destructive, requires 2s hold)
    controller.on_gesture(
        Gesture.BOTH_PALMS,
        lambda: ui_event_queue.put({"type": "clear_history", "data": ""})
    )

    # Wave → greeting + status report
    def _on_wave():
        ui_event_queue.put({"type": "status", "data": "Wave detected!"})
        # Trigger a status report through the agent
        ui_input_queue.put("Give me a quick system status report.")

    controller.on_gesture(Gesture.WAVE, _on_wave)

    # ── VOICE CONTROL ─────────────────────────────────────

    # Peace sign (two fingers up) → trigger voice recording
    def _on_peace():
        from voice import stop_speaking
        stop_speaking()
        ui_input_queue.put("__WAKE_RECORD__")

    controller.on_gesture(Gesture.PEACE, _on_peace)

    # Thumb sideways → toggle mute
    _mute_state = [False]   # mutable container for closure

    def _on_thumb_sideways():
        _mute_state[0] = not _mute_state[0]
        muted = _mute_state[0]
        ui_event_queue.put({"type": "set_muted", "data": muted})
        controller._muted = muted
        if muted:
            ui_event_queue.put({"type": "status", "data": "Microphone muted"})
            _speak("Microphone muted.")
        else:
            ui_event_queue.put({"type": "status", "data": "Microphone unmuted"})
            _speak("Microphone back on.")

    controller.on_gesture(Gesture.THUMB_SIDEWAYS, _on_thumb_sideways)

    # ── APP SHORTCUTS ─────────────────────────────────────

    shortcuts = GESTURE_APP_SHORTCUTS

    # One finger → open Chrome (or config override)
    controller.on_gesture(
        Gesture.ONE_FINGER,
        lambda: _launch_app(shortcuts.get("one_finger", "chrome"))
    )

    # Three fingers → open File Explorer (or config override)
    controller.on_gesture(
        Gesture.THREE_FINGERS,
        lambda: _launch_app(shortcuts.get("three_fingers", "explorer"))
    )

    # Four fingers → open Spotify (or config override)
    controller.on_gesture(
        Gesture.FOUR_FINGERS,
        lambda: _launch_app(shortcuts.get("four_fingers", "spotify"))
    )

    # ── MOLECULE STATE ────────────────────────────────────

    # Thumbs up → switch to speaking/orange
    controller.on_gesture(
        Gesture.THUMBS_UP,
        lambda: ui_event_queue.put({"type": "state", "data": "speaking"})
    )

    # Thumbs down → switch to thinking/blue
    controller.on_gesture(
        Gesture.THUMBS_DOWN,
        lambda: ui_event_queue.put({"type": "state", "data": "thinking"})
    )

    logger.info("All gesture bindings registered — full spec implemented.")
