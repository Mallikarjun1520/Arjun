"""
main.py — ARJUN Agent Loop (Fixed)
Fixes:
  - Typed text in UI now gets a response
  - Briefing is interruptible
  - Tool calling works reliably
  - Clean thread management
  - Proper error messages shown in UI
"""

import os
import sys
import time
import queue
import logging
import threading
import requests
import warnings

# Suppress protobuf deprecation warnings from mediapipe
warnings.filterwarnings("ignore", category=UserWarning)

from config import (
    OLLAMA_URL, OLLAMA_MODEL, MAX_TOKENS, MAX_HISTORY,
    LOG_LEVEL, LOG_FILE, BRIEFING_ENABLED
)
from tools        import dispatch_tool, TOOL_SCHEMAS, recall_memory
from voice        import (load_whisper, listen_for_wake_word,
                          record_until_silence, transcribe, speak, stop_speaking,
                          set_audio_state_callback, set_tts_voice,
                          set_voice_interrupt_callback)
from context_builder import build_system_prompt

logger = logging.getLogger(__name__)

# ── Logging setup ─────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# ── Shared queues ─────────────────────────────────────────
ui_event_queue  = queue.Queue()   # → UI  (state, text, status)
ui_input_queue  = queue.Queue()   # UI → agent (typed text or __RECORD__)
tg_input_queue  = queue.Queue()   # Telegram → agent
tg_output_queue = queue.Queue()   # agent → Telegram

conversation_history = []
_recording_flag      = threading.Event()
_agent_busy          = threading.Event()   # prevents overlapping requests
_conversation_mode   = False
_conversation_lock   = threading.Lock()


# ─────────────────────────────────────────────
#  DESTRUCTIVE CONFIRMATION
# ─────────────────────────────────────────────

DESTRUCTIVE_PHRASES = [
    "clear my history", "delete my memory", "clear conversation",
    "erase everything", "reset memory", "wipe memory",
    "clear all history", "delete all memory",
]

_pending_destructive = None

def _is_destructive(text: str) -> bool:
    return any(p in text.lower() for p in DESTRUCTIVE_PHRASES)

def _describe_destructive(text: str) -> str:
    t = text.lower()
    if "memory" in t:
        return "delete all stored memories about you"
    return "clear the entire conversation history"

def _execute_destructive(text: str):
    global conversation_history
    t = text.lower()
    if "memory" in t:
        import json
        from config import MEMORY_FILE
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"facts": [], "created": ""}, f)
        speak("Done. I have cleared everything I remembered about you.")
    else:
        conversation_history = []
        ui_event_queue.put({"type": "clear_history", "data": ""})
        speak("Done. Conversation history has been cleared.")


# ─────────────────────────────────────────────
#  OLLAMA CHAT
# ─────────────────────────────────────────────

def chat_with_arjun(user_message: str, source: str = "local") -> str:
    global conversation_history, _pending_destructive

    # ── Interrupt any ongoing speech ──
    stop_speaking()

    # ── Destructive confirmation flow ──
    if _pending_destructive:
        action_text, description = _pending_destructive
        _pending_destructive = None
        yes_words = ["yes", "confirm", "do it", "go ahead", "yeah", "yep", "sure", "ok"]
        no_words  = ["no", "cancel", "stop", "never mind", "nope", "abort", "don't"]

        if any(w in user_message.lower() for w in yes_words):
            _execute_destructive(action_text)
            return f"Done. I have gone ahead and {description}."
        elif any(w in user_message.lower() for w in no_words):
            return "Alright, cancelled. Nothing was changed."
        else:
            return f"I need a clear yes or no. Should I {description}?"

    # ── Check destructive command ──
    if _is_destructive(user_message):
        description = _describe_destructive(user_message)
        _pending_destructive = (user_message, description)
        return (f"Just to confirm, you want me to {description}. "
                f"This cannot be undone. Say yes to confirm or no to cancel.")

    # ── UI state update ──
    if source == "local":
        ui_event_queue.put({"type": "state",  "data": "thinking"})
        ui_event_queue.put({"type": "status", "data": "Thinking..."})

    # ── Memory ──
    memory_context = recall_memory()

    # ── RAG auto-search ──
    rag_context = ""
    try:
        from knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        if kb.chunk_count > 0:
            rag_context = kb.search(user_message, n=3)
    except Exception:
        pass

    # ── Build system prompt ──
    system_prompt = build_system_prompt(
        source=source,
        memory_context=memory_context,
        rag_context=rag_context,
        conversation_history=conversation_history
    )

    # ── Add to history ──
    conversation_history.append({"role": "user", "content": user_message})
    if len(conversation_history) > MAX_HISTORY:
        conversation_history = conversation_history[-MAX_HISTORY:]

    payload = {
        "model":    OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + conversation_history,
        "tools":    TOOL_SCHEMAS,
        "stream":   False,
        "options":  {
            "num_predict": MAX_TOKENS,
            "num_ctx":     32768,
            "temperature": 0.7
        }
    }

    # ── Agentic loop ──
    for round_num in range(8):
        try:
            ui_event_queue.put({"type": "status", "data": f"Calling Ollama (round {round_num+1})..."})
            resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
            resp.raise_for_status()
            data = resp.json()

        except requests.exceptions.ConnectionError:
            msg = "Ollama is not running. Please start it with ollama serve."
            logger.error(msg)
            return msg
        except requests.exceptions.Timeout:
            msg = "Ollama took too long to respond. Try a shorter question."
            logger.error(msg)
            return msg
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return f"Something went wrong talking to Ollama: {str(e)}"

        message    = data.get("message", {})
        tool_calls = message.get("tool_calls", [])
        content    = message.get("content", "").strip()

        # ── Tool calls ──
        if tool_calls:
            payload["messages"].append(message)
            for tc in tool_calls:
                fn_name = tc.get("function", {}).get("name", "")
                fn_args = tc.get("function", {}).get("arguments", {})
                if isinstance(fn_args, str):
                    import json
                    try:
                        fn_args = json.loads(fn_args)
                    except json.JSONDecodeError as e:
                        logger.error("Invalid JSON arguments for tool %s: %s", fn_name, e)
                        fn_args = None

                logger.info(f"Tool: {fn_name}({fn_args})")
                ui_event_queue.put({"type": "status", "data": f"Using {fn_name}..."})

                if not isinstance(fn_args, dict):
                    result = f"Tool call {fn_name} had invalid arguments; no action was taken."
                else:
                    result = dispatch_tool(fn_name, fn_args)
                logger.info(f"Tool result: {result[:150]}")

                payload["messages"].append({
                    "role":    "tool",
                    "content": str(result)
                })
            continue

        # ── Text response ──
        if content:
            conversation_history.append({"role": "assistant", "content": content})
            logger.info(f"Response: {content[:100]}")
            return content

        # Empty response
        logger.warning(f"Empty response from Ollama at round {round_num}")
        return "I seem to have lost my train of thought. Could you say that again?"

    return "I ran into a loop trying to answer that. Please try again."


# ─────────────────────────────────────────────
#  RESPONSE HANDLER  (shared by all input sources)
# ─────────────────────────────────────────────

def _schedule_followup_listening(source: str = "local"):
    with _conversation_lock:
        continue_listening = _conversation_mode and source == "local"
    if continue_listening:
        _recording_flag.set()


def _handle_input(text: str, source: str = "local"):
    """Process a user message through the full agent loop."""
    if _agent_busy.is_set():
        logger.debug("Agent busy, skipping duplicate request")
        return

    _agent_busy.set()
    try:
        ui_event_queue.put({"type": "user",  "data": text})
        ui_event_queue.put({"type": "state", "data": "thinking"})

        reply = chat_with_arjun(text, source=source)

        ui_event_queue.put({"type": "state", "data": "speaking"})
        ui_event_queue.put({"type": "arjun", "data": reply})

        speak(reply)

        ui_event_queue.put({"type": "status", "data": "Ready"})
        _schedule_followup_listening(source)

    except Exception as e:
        logger.error(f"Handle input error: {e}")
        ui_event_queue.put({"type": "status", "data": f"Error: {str(e)[:60]}"})
        ui_event_queue.put({"type": "state",  "data": "idle"})
    finally:
        _agent_busy.clear()


# ─────────────────────────────────────────────
#  INPUT LOOPS
# ─────────────────────────────────────────────

def _start_voice_capture(prompt: bool = False):
    def _prepare_capture():
        try:
            if prompt:
                speak("Yes?")
        finally:
            _recording_flag.set()

    threading.Thread(
        target=_prepare_capture,
        name="voice-capture-prompt",
        daemon=True,
    ).start()


def _wake_word_callback():
    logger.info("Wake word triggered.")
    stop_speaking()
    _start_voice_capture(prompt=True)


def _voice_interrupt_detected():
    logger.info("Spoken stop command detected; listening for the follow-up.")
    stop_speaking()
    _recording_flag.set()


def _set_conversation_mode(enabled: bool):
    global _conversation_mode
    with _conversation_lock:
        _conversation_mode = enabled
    logger.info("Continuous conversation %s.", "enabled" if enabled else "disabled")
    ui_event_queue.put({
        "type": "status",
        "data": "Continuous conversation on" if enabled else "Continuous conversation off",
    })


def _apply_voice_selection(voice_name: str):
    try:
        if set_tts_voice(voice_name):
            message = f"Voice set to {voice_name.title()}"
        else:
            message = f"{voice_name.title()} voice is not installed"
    except ValueError as exc:
        logger.warning("Ignoring invalid voice selection: %s", exc)
        return
    ui_event_queue.put({"type": "status", "data": message})


def _voice_state_changed(state: str):
    logger.info("Voice pipeline state: %s", state)
    ui_event_queue.put({"type": "state", "data": state})
    status = {
        "PASSIVE_LISTENING": "Listening for Hey Jarvis",
        "ACTIVE_LISTENING": "Listening for your command",
        "SPEAKING": "Speaking",
        "WAKE_LISTENER_RETRYING": "Wake listener reconnecting",
        "WAKE_LISTENER_ERROR": "Wake model unavailable; run setup.bat",
    }.get(state, state.replace("_", " ").title())
    ui_event_queue.put({"type": "status", "data": status})


def _local_voice_loop():
    """Handles microphone recording triggered by wake word or mic button."""
    while True:
        _recording_flag.wait()
        _recording_flag.clear()

        ui_event_queue.put({"type": "status", "data": "Listening..."})

        try:
            audio = record_until_silence()
            text  = transcribe(audio)
        except Exception as e:
            logger.error(f"Recording error: {e}")
            speak("Sorry, I had trouble hearing that.")
            ui_event_queue.put({"type": "status", "data": "Ready"})
            _schedule_followup_listening()
            continue

        if not text or len(text.strip()) < 2:
            speak("I did not catch that. Try again?")
            _schedule_followup_listening()
            continue

        # Run in thread so voice loop stays responsive
        threading.Thread(
            target=_handle_input,
            args=(text, "local"),
            daemon=True
        ).start()


def _ui_input_loop():
    """
    Reads typed messages and mic button presses from the UI queue.
    THIS is the fix for typed text not getting responses.
    """
    while True:
        try:
            text = ui_input_queue.get(timeout=0.05)
        except queue.Empty:
            continue

        if not text:
            continue

        if text == "__RECORD__":
            stop_speaking()
            _recording_flag.set()
            continue

        if text == "__WAKE_RECORD__":
            stop_speaking()
            _start_voice_capture(prompt=True)
            continue

        if text == "__STOP__":
            stop_speaking()
            continue

        if text.startswith("__VOICE__:"):
            voice_name = text.partition(":")[2]
            threading.Thread(
                target=_apply_voice_selection,
                args=(voice_name,),
                name="voice-selection",
                daemon=True,
            ).start()
            continue

        if text.startswith("__CONVERSATION__:"):
            _set_conversation_mode(text.partition(":")[2] == "on")
            continue

        text = text.strip()
        if not text:
            continue

        logger.info(f"UI input received: '{text}'")

        # Run in thread so UI stays responsive
        threading.Thread(
            target=_handle_input,
            args=(text, "local"),
            daemon=True
        ).start()


def _telegram_agent_loop():
    """Handles messages from Telegram."""
    while True:
        try:
            msg = tg_input_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        text   = msg.get("text", "")
        source = msg.get("source", "telegram")
        if not text:
            continue

        reply = chat_with_arjun(text, source=source)
        tg_output_queue.put(reply)


def _watch_wake_flag():
    """Watches for .wake_trigger file from startup_listener.py."""
    flag_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".wake_trigger")
    last_seen = 0.0
    while True:
        time.sleep(0.3)
        try:
            if os.path.exists(flag_path):
                mtime = os.path.getmtime(flag_path)
                if mtime > last_seen:
                    last_seen = mtime
                    os.remove(flag_path)
                    ui_input_queue.put("__WAKE_RECORD__")
        except Exception:
            pass


# ─────────────────────────────────────────────
#  STARTUP CHECKS
# ─────────────────────────────────────────────

def check_ollama() -> bool:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        if r.status_code == 200:
            # Check if arjun model exists
            models = r.json().get("models", [])
            names  = [m.get("name", "") for m in models]
            if not any("arjun" in n for n in names):
                logger.warning(f"Model 'arjun' not found. Available: {names}")
                logger.warning("Run: ollama create arjun -f Modelfile")
            return True
        return False
    except Exception:
        return False


# ─────────────────────────────────────────────
#  MORNING BRIEFING
# ─────────────────────────────────────────────

def _deliver_briefing():
    """Deliver morning briefing after UI is ready. Interruptible."""
    time.sleep(3.0)   # wait for UI to fully render

    if not BRIEFING_ENABLED:
        return

    try:
        logger.info("Assembling morning briefing...")
        ui_event_queue.put({"type": "status", "data": "Preparing briefing..."})
        ui_event_queue.put({"type": "state",  "data": "thinking"})

        from briefing import assemble_briefing
        briefing_text = assemble_briefing()

        ui_event_queue.put({"type": "state", "data": "speaking"})
        ui_event_queue.put({"type": "arjun", "data": briefing_text})

        speak(briefing_text)   # interruptible — stop_speaking() cuts this

    except Exception as e:
        logger.warning(f"Briefing failed: {e}")
        speak("Good morning. I am ready when you are.")
    finally:
        ui_event_queue.put({"type": "state",  "data": "listening"})
        ui_event_queue.put({"type": "status", "data": "Listening for Hey Jarvis"})


def _whatsapp_notification(message: str):
    logger.info("WhatsApp notification received.")
    ui_event_queue.put({"type": "arjun", "data": message})
    threading.Thread(target=speak, args=(message,), daemon=True).start()


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    logger.info("=" * 56)
    logger.info("ARJUN — Automated Retrieval, Judgment and Utility Network")
    logger.info("=" * 56)

    # ── Ollama check ──
    if not check_ollama():
        print("\n[ERROR] Ollama is not running.")
        print("Start it with:  ollama serve")
        print("Then run:       ollama create arjun -f Modelfile")
        sys.exit(1)

    # ── Load models ──
    logger.info("Loading Whisper STT...")
    load_whisper()

    logger.info("Loading knowledge base...")
    try:
        from knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        logger.info(f"KB: {kb.document_count} docs, {kb.chunk_count} chunks.")
    except Exception as e:
        logger.warning(f"KB init: {e}")

    # ── Wake word ──
    set_audio_state_callback(_voice_state_changed)
    set_voice_interrupt_callback(_voice_interrupt_detected)
    listen_for_wake_word(_wake_word_callback)

    # ── Background threads ──
    for target, name in [
        (_local_voice_loop,   "voice-loop"),
        (_ui_input_loop,      "ui-input-loop"),
        (_telegram_agent_loop,"telegram-loop"),
        (_watch_wake_flag,    "wake-flag-watcher"),
    ]:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        logger.info(f"Thread started: {name}")

    # ── Telegram ──
    try:
        from telegram_bot import TelegramBridge
        TelegramBridge(tg_input_queue, tg_output_queue).start()
    except Exception as e:
        logger.warning(f"Telegram skipped: {e}")

    # ── WhatsApp ──
    try:
        from whatsapp_bridge import start_whatsapp
        start_whatsapp(lambda message: _whatsapp_notification(message))
    except Exception as e:
        logger.warning(f"WhatsApp skipped: {e}")

    # ── Gesture control ──
    try:
        from gesture_control import GestureController, wire_gestures
        gesture_ctrl = GestureController(ui_event_queue)
        wire_gestures(gesture_ctrl, ui_event_queue, ui_input_queue, _recording_flag)
        gesture_ctrl.start()
        logger.info("Gesture control active.")
    except Exception as e:
        logger.warning(f"Gesture control skipped: {e}")

    # ── Morning briefing thread ──
    threading.Thread(target=_deliver_briefing, daemon=True, name="briefing").start()

    # ── Launch UI ──
    logger.info("Launching UI...")
    try:
        from holographic_ui import launch_ui
        logger.info("Using holographic UI.")
    except ImportError:
        from ui import launch_ui
        logger.info("Using standard UI.")

    # UI blocks main thread until window closed
    launch_ui(ui_event_queue, ui_input_queue)

    logger.info("ARJUN shutting down.")


if __name__ == "__main__":
    main()
