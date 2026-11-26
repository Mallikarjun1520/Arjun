# Phase 3 — Holographic Gesture UI

## What Was Built

Phase 3 replaces the flat PyQt5 window with a frameless transparent holographic interface and adds real-time hand gesture control via MediaPipe. It also adds desktop app launching by both voice and gesture.

## Files Added

| File | Purpose |
|------|---------|
| `gesture_control.py` | MediaPipe hand tracking, gesture classification, hold timers, destructive confirmation |
| `holographic_ui.py` | Frameless transparent floating window with molecule, gesture overlay, confirmation ring, app shortcuts |
| `app_launcher.py` | Fuzzy-match app launcher used by both voice and gesture |

## Files Modified

| File | What Changed |
|------|-------------|
| `config.py` | Gesture settings, app registry, gesture-to-app shortcuts |
| `tools.py` | open_application and list_applications tools added |
| `requirements.txt` | mediapipe, opencv-python added |
| `main.py` | Gesture controller wired in, holographic UI used |

## Key Design Decisions

**Frameless transparent window** — Qt.FramelessWindowHint + WA_TranslucentBackground gives the floating hologram feel. The dark semi-transparent background still lets you see your desktop through it.

**Gesture hold timer** — Discrete gestures must be held for 0.5 seconds before firing. Swipe and motion gestures fire as continuous events with a cooldown.

**Destructive gesture confirmation** — Fist and both-palms gestures show a countdown ring. The user must hold the gesture for the full 2 seconds to confirm. Releasing the gesture at any point cancels the action. The ring renders directly over the molecule using a stacked QWidget.

**App registry in config** — All app paths live in config.py so the user can add, remove or remap apps without touching any code.

**Browser services** — Chrome is found through Windows app registration or common install locations, with a default-browser fallback. Spotify and YouTube open their websites rather than requiring desktop executables.

**Fuzzy match** — difflib.get_close_matches handles typos and partial names so "open chorme" still opens Chrome.

## Gesture Reference

| Gesture | Action |
|---------|--------|
| Pinch + drag | Move window |
| Fist | Minimize |
| Open palm | Maximize |
| Two fingers spread | Zoom molecule in |
| Two fingers pinch | Zoom molecule out |
| Stop signal | Interrupt speech |
| Swipe left | Scroll chat up |
| Swipe right | Scroll chat down |
| Both palms (hold 2s) | Clear history (confirms) |
| Peace sign | Trigger voice recording |
| One finger | Open Chrome |
| Three fingers | Open File Explorer |
| Four fingers | Open Spotify |
| Thumbs up | Switch to speaking mode |
| Thumbs down | Switch to thinking mode |

## Setup Steps for Phase 3

```
pip install mediapipe opencv-python
```
No additional model downloads needed. MediaPipe downloads its hand model automatically on first use.
