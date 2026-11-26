"""
config.py — ARJUN Central Configuration
All settings in one place. Everything else reads from here.
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ── LLM ──
OLLAMA_URL      = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "arjun")
FALLBACK_MODEL  = "qwen2.5:3b"
MAX_TOKENS      = 1024

# ── Whisper STT ──
WHISPER_MODEL   = "base.en"
WHISPER_DEVICE  = "cpu"
WHISPER_COMPUTE = "int8"
WHISPER_LANGUAGE= "en"

# ── Wake Word ──
WAKE_WORD       = "hey_jarvis"
WAKE_THRESHOLD  = 0.5

# ── Audio ──
SAMPLE_RATE       = 16000
CHANNELS          = 1
CHUNK_SIZE        = 1024
SILENCE_THRESHOLD = 500
SILENCE_DURATION  = 1.5
MAX_RECORD_SECS   = 30

# ── TTS ──
PIPER_VOICE     = "en_US-lessac-medium"
PIPER_MODEL_DIR = os.path.join(os.path.dirname(__file__), "piper_models")
TTS_VOICE       = "zira"
TTS_RATE        = 165

# ── Memory ──
MEMORY_FILE       = os.path.join(os.path.dirname(__file__), "memory.json")
MAX_MEMORY_FACTS  = 100

# ── Projects ──
PROJECTS_DIR    = os.path.expanduser("~/Documents/ArjunProjects")
VSCODE_PATH     = r"C:\Users\{}\AppData\Local\Programs\Microsoft VS Code\Code.exe".format(
                    os.environ.get("USERNAME", "user"))

# ── Conversation ──
MAX_HISTORY     = 20

# ── Telegram ──
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Gmail ──
GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
GMAIL_IMAP_SERVER  = "imap.gmail.com"
GMAIL_SMTP_SERVER  = "smtp.gmail.com"
GMAIL_SMTP_PORT    = 587

# ── UI ──
UI_WIDTH        = 480
UI_HEIGHT       = 680
UI_TITLE        = "Arjun"

# ── Logging ──
LOG_LEVEL       = "INFO"
LOG_FILE        = os.path.join(os.path.dirname(__file__), "arjun.log")

# ── Knowledge Base (Phase 2) ──
KB_DIR           = os.path.join(os.path.dirname(__file__), "knowledge_base_store")
EMBED_MODEL      = "nomic-embed-text"
OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
KB_CHUNK_SIZE    = 500
KB_CHUNK_OVERLAP = 50
KB_TOP_N         = 5          # results injected into context per query

# ── Context Builder (Phase 2) ──
PREFS_FILE       = os.path.join(os.path.dirname(__file__), "preferences.json")

# ── Gesture Control (Phase 3) ──
GESTURE_CAMERA_INDEX    = 0        # webcam index, 0 = default
GESTURE_HOLD_SECONDS    = 0.5      # seconds a gesture must be held to fire
GESTURE_CONFIRM_SECONDS = 2.0      # seconds to confirm a destructive action
GESTURE_COOLDOWN        = 1.2      # seconds between successive gesture fires
GESTURE_MIN_CONFIDENCE  = 0.75     # MediaPipe hand detection confidence
GESTURE_OVERLAY         = True     # show real-time gesture name in UI corner

# ── App Launcher (Phase 3) ──
# Add your own desktop apps here — browser services are routed by app_launcher.py.
APP_REGISTRY = {
    "edge":             "msedge.exe",
    "firefox":          "firefox.exe",
    "notepad":          "notepad.exe",
    "calculator":       "calc.exe",
    "vscode":           r"C:\Users\{USERNAME}\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "vs code":          r"C:\Users\{USERNAME}\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "explorer":         "explorer.exe",
    "discord":          r"C:\Users\{USERNAME}\AppData\Local\Discord\Update.exe --processStart Discord.exe",
    "whatsapp":         r"C:\Users\{USERNAME}\AppData\Local\WhatsApp\WhatsApp.exe",
    "word":             "winword.exe",
    "excel":            "excel.exe",
    "powerpoint":       "powerpnt.exe",
    "paint":            "mspaint.exe",
    "settings":         "ms-settings:",
    "task manager":     "taskmgr.exe",
    "terminal":         "wt.exe",
    "cmd":              "cmd.exe",
    "file explorer":    "explorer.exe",
}

# Gesture-to-app bindings (shown as floating buttons in UI)
# These appear as quick-launch icons around the molecule
GESTURE_APP_SHORTCUTS = {
    "one_finger":   "chrome",       # point one finger → open Chrome
    "two_fingers":  "vscode",       # peace sign → open VS Code
    "three_fingers":"explorer",     # three up → open File Explorer
    "four_fingers": "spotify",      # four up → open Spotify
}

# ── Morning Briefing (Phase 4) ──
BRIEFING_ENABLED       = True
BRIEFING_USER_NAME     = "there"        # replaced by memory if name is known
BRIEFING_LOCATION      = "Hyderabad"    # set your city for weather
BRIEFING_NEWS_TOPICS   = ["artificial intelligence", "technology", "science","business", "health", "sports","trending"]  # topics for news headlines
BRIEFING_NEWS_COUNT    = 3
BRIEFING_PARALLEL_FETCH = True          # fetch weather + news simultaneously

# ── WhatsApp (Phase 4) ──
WHATSAPP_SESSION_DIR   = os.path.join(os.path.dirname(__file__), "whatsapp_session")
WHATSAPP_IMPORTANT_CONTACTS = []        # e.g. ["Mom", "Best Friend"] — notified immediately
WHATSAPP_CHECK_INTERVAL = 30            # seconds between checking new messages
WHATSAPP_MAX_MSG_LENGTH = 300           # chars before truncating when reading aloud
