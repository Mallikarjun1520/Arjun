"""
startup_listener.py — ARJUN Always-On Background Listener
Runs silently from Windows startup.
Listens passively for the wake phrase "Hey Jarvis" at all times.
When heard, it checks if Arjun's UI is already open.
If not, it launches the full Arjun UI automatically.
If yes, it signals the existing instance to start recording.

This file is what makes saying "Hey Jarvis" work
even when you haven't touched your laptop yet.
"""

import os
import sys
import time
import subprocess
import threading
import logging
import numpy as np
import pyaudio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)
from config import WAKE_WORD

LOG_PATH = os.path.join(BASE_DIR, "startup_listener.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("arjun.startup")

WAKE_THRESHOLD = 0.5
CHUNK_SIZE     = 1280
SAMPLE_RATE    = 16000

# ── Lock file so only one listener runs at a time ──
LOCK_FILE = os.path.join(BASE_DIR, ".arjun_listener.lock")


def is_arjun_running() -> bool:
    """Check if main.py is already running as a process."""
    try:
        import psutil
        for proc in psutil.process_iter(["cmdline"]):
            cmdline = proc.info.get("cmdline") or []
            if any("main.py" in c for c in cmdline):
                return True
    except Exception:
        pass
    return False


def launch_arjun():
    """Launch Arjun's full UI silently."""
    try:
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable

        subprocess.Popen(
            [pythonw, os.path.join(BASE_DIR, "launcher.pyw")],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        logger.info("Arjun UI launched from wake word.")
    except Exception as e:
        logger.error(f"Failed to launch Arjun: {e}")


def already_listening() -> bool:
    """Prevent two instances of this listener running."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                pid = int(f.read().strip())
            import psutil
            if psutil.pid_exists(pid):
                return True
        except Exception:
            pass
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return False


def run_listener():
    if already_listening():
        logger.info("Another listener instance is already running. Exiting.")
        sys.exit(0)

    logger.info("ARJUN startup listener active. Waiting for 'Hey Jarvis'...")

    try:
        from openwakeword.model import Model

        oww = Model(wakeword_models=[WAKE_WORD], inference_framework="onnx")

        while True:
            if is_arjun_running():
                time.sleep(0.5)
                continue

            pa = pyaudio.PyAudio()
            stream = None
            try:
                stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=CHUNK_SIZE,
                )
                cooldown_until = 0.0
                while not is_arjun_running():
                    chunk = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    audio_np = np.frombuffer(chunk, dtype=np.int16)
                    pred = oww.predict(audio_np)

                    now = time.time()
                    if now < cooldown_until:
                        continue

                    for score in pred.values():
                        if score >= WAKE_THRESHOLD:
                            logger.info("Wake word detected (score=%.2f)", score)
                            cooldown_until = now + 3.0
                            if is_arjun_running():
                                flag = os.path.join(BASE_DIR, ".wake_trigger")
                                with open(flag, "w") as f:
                                    f.write(str(now))
                                logger.info("Arjun already running — wake flag written.")
                            else:
                                launch_arjun()
                            break
            finally:
                try:
                    if stream is not None:
                        try:
                            stream.stop_stream()
                        finally:
                            stream.close()
                finally:
                    pa.terminate()

    except Exception as e:
        logger.error(f"Listener error: {e}")
    finally:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)


if __name__ == "__main__":
    run_listener()
