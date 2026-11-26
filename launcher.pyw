"""
launcher.pyw — ARJUN Silent Launcher
The .pyw extension means Windows runs this with pythonw.exe
so zero terminal window appears. Double-click the desktop
icon and Arjun starts invisibly in the background.
Only the UI window appears.
"""

import os
import sys
import subprocess
import time

# Add the arjun folder to path regardless of where shortcut is launched from
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

def is_ollama_running() -> bool:
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False

def start_ollama():
    """Start Ollama silently in the background if not already running."""
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    # Wait up to 10 seconds for it to come online
    for _ in range(20):
        time.sleep(0.5)
        if is_ollama_running():
            return True
    return False

# Start Ollama if needed
if not is_ollama_running():
    start_ollama()

# Now launch the main Arjun process
subprocess.Popen(
    [sys.executable, os.path.join(BASE_DIR, "main.py")],
    cwd=BASE_DIR,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NO_WINDOW
)
