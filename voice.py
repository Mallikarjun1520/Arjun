"""
voice.py — ARJUN Audio Pipeline
OpenWakeWord listening, Faster-Whisper transcription, and interruptible local TTS.
"""

import logging
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from typing import Callable, Optional

import numpy as np
import pyaudio
from faster_whisper import WhisperModel

from config import (
    MAX_RECORD_SECS,
    PIPER_MODEL_DIR,
    PIPER_VOICE,
    SAMPLE_RATE,
    CHANNELS,
    CHUNK_SIZE,
    SILENCE_DURATION,
    SILENCE_THRESHOLD,
    TTS_RATE,
    TTS_VOICE,
    WAKE_THRESHOLD,
    WAKE_WORD,
    WHISPER_COMPUTE,
    WHISPER_DEVICE,
    WHISPER_LANGUAGE,
    WHISPER_MODEL,
)

logger = logging.getLogger(__name__)

_whisper_model = None
_whisper_lock = threading.RLock()

interrupt_event = threading.Event()
is_speaking = False
is_listening = False
_audio_state = "PASSIVE_LISTENING"
_audio_state_lock = threading.RLock()
_state_callback: Optional[Callable[[str], None]] = None
_wake_cooldown_until = 0.0
_interrupt_callback: Optional[Callable[[], None]] = None
_interrupt_transcription_busy = threading.Event()
_interrupt_next_check_at = 0.0

_speech_generation = 0
_speech_lock = threading.RLock()
_tts_engine = None
_tts_requests = queue.Queue()
_tts_worker_thread = None
_tts_worker_lock = threading.Lock()
_selected_voice = TTS_VOICE.lower()
_voice_lock = threading.RLock()
_piper_process = None
_piper_process_lock = threading.Lock()
_POST_SPEECH_COOLDOWN = 0.45
_MAX_SPEECH_CHARS = 120


def _set_audio_state(state: str):
    global _audio_state, is_speaking, is_listening
    with _audio_state_lock:
        _audio_state = state
        is_speaking = state == "SPEAKING"
        is_listening = state in ("ACTIVE_LISTENING", "PASSIVE_LISTENING")
    logger.info("Audio state: %s", state)
    if _state_callback is not None:
        try:
            _state_callback(state)
        except Exception:
            logger.exception("Audio state callback failed.")


def set_audio_state_callback(callback: Optional[Callable[[str], None]]):
    """Set the UI/console state observer without coupling voice.py to the UI."""
    global _state_callback
    _state_callback = callback
    if callback is not None:
        callback(_current_audio_state())


def set_voice_interrupt_callback(callback: Optional[Callable[[], None]]):
    global _interrupt_callback
    _interrupt_callback = callback


def get_tts_voice() -> str:
    with _voice_lock:
        return _selected_voice


def set_tts_voice(voice_name: str) -> bool:
    global _selected_voice
    voice_name = voice_name.lower().strip()
    if voice_name not in ("zira", "david"):
        raise ValueError(f"Unsupported local voice: {voice_name}")

    with _voice_lock:
        _selected_voice = voice_name
    _ensure_tts_worker()
    completed = threading.Event()
    result = []
    _tts_requests.put(("voice", voice_name, completed, result))
    completed.wait()
    return bool(result and result[0])


def _current_audio_state() -> str:
    with _audio_state_lock:
        return _audio_state


def _notify_listener_status(status: str):
    if _state_callback is not None:
        try:
            _state_callback(status)
        except Exception:
            logger.exception("Wake listener status callback failed.")


def _is_interrupted(generation: int) -> bool:
    with _speech_lock:
        return interrupt_event.is_set() or generation != _speech_generation


def load_whisper():
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:
            return
        logger.info("Loading Whisper model...")
        _whisper_model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
        )
        logger.info("Whisper ready.")


def _init_tts_engine():
    """Initialize pyttsx3 on the dedicated TTS worker thread."""
    global _tts_engine
    if _tts_engine is not None:
        return
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", TTS_RATE)
        _tts_engine = engine
        with _voice_lock:
            preferred = _selected_voice
        if not _apply_tts_voice(engine, preferred):
            _apply_tts_voice(engine, "zira" if preferred != "zira" else "david")
    except Exception:
        logger.exception("TTS engine initialization failed.")
        _tts_engine = None


def _apply_tts_voice(engine, preferred: str) -> bool:
    for voice in engine.getProperty("voices"):
        if voice.name and preferred in voice.name.lower():
            engine.setProperty("voice", voice.id)
            logger.info("TTS voice selected: %s", voice.name)
            return True
    logger.warning("No installed TTS voice matched %r.", preferred)
    return False


def _piper_settings():
    executable = shutil.which("piper")
    model_path = os.path.join(PIPER_MODEL_DIR, PIPER_VOICE + ".onnx")
    if executable and os.path.isfile(model_path):
        return executable, model_path
    return None


def _speak_with_piper(text: str, generation: int) -> bool:
    """Speak with a local Piper CLI/model when both are available."""
    global _piper_process

    settings = _piper_settings()
    if settings is None:
        return False

    executable, model_path = settings
    import sounddevice
    import soundfile

    file_descriptor, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(file_descriptor)
    process = None
    try:
        process = subprocess.Popen(
            [executable, "--model", model_path, "--output_file", wav_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        with _piper_process_lock:
            _piper_process = process
        _, stderr = process.communicate(
            input=text.encode("utf-8"),
            timeout=45,
        )
        if process.returncode:
            raise RuntimeError(stderr.decode("utf-8", errors="replace")[-500:])
        if _is_interrupted(generation):
            return True

        audio, sample_rate = soundfile.read(wav_path, dtype="float32")
        sounddevice.play(audio, sample_rate)
        while True:
            stream = sounddevice.get_stream()
            if stream is None or not stream.active:
                break
            if interrupt_event.wait(0.025) or _is_interrupted(generation):
                sounddevice.stop()
                break
        return True
    finally:
        with _piper_process_lock:
            if _piper_process is process:
                _piper_process = None
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
        try:
            os.remove(wav_path)
        except FileNotFoundError:
            pass


def _speak_with_pyttsx3(text: str):
    global _tts_engine
    _init_tts_engine()
    if _tts_engine is None:
        raise RuntimeError("No local TTS engine is available.")
    _tts_engine.say(text)
    _tts_engine.runAndWait()


def _speech_worker():
    global _tts_engine, _wake_cooldown_until
    while True:
        request = _tts_requests.get()
        if request[0] == "voice":
            _, preferred, completed, result = request
            try:
                _init_tts_engine()
                result.append(
                    _tts_engine is not None
                    and _apply_tts_voice(_tts_engine, preferred)
                )
            except Exception:
                logger.exception("Could not change the local TTS voice.")
                result.append(False)
            finally:
                completed.set()
            continue

        _, generation, chunks, completed = request
        try:
            with _speech_lock:
                if generation != _speech_generation:
                    continue
                interrupt_event.clear()

            _set_audio_state("SPEAKING")
            for chunk in chunks:
                if _is_interrupted(generation):
                    break
                try:
                    _speak_with_pyttsx3(chunk)
                except Exception:
                    logger.exception("TTS chunk failed.")
                    _tts_engine = None
                    if not _is_interrupted(generation):
                        try:
                            if not _speak_with_piper(chunk, generation):
                                _speak_with_pyttsx3(chunk)
                        except Exception:
                            logger.exception("Local TTS fallback failed.")
                if _is_interrupted(generation):
                    break
        finally:
            with _speech_lock:
                interrupt_event.clear()
            with _speech_lock:
                speech_is_current = generation == _speech_generation
            if speech_is_current and _current_audio_state() == "SPEAKING":
                _wake_cooldown_until = time.monotonic() + _POST_SPEECH_COOLDOWN
                if _current_audio_state() == "SPEAKING":
                    _set_audio_state("PASSIVE_LISTENING")
            completed.set()


def _ensure_tts_worker():
    global _tts_worker_thread
    with _tts_worker_lock:
        if _tts_worker_thread is None or not _tts_worker_thread.is_alive():
            _tts_worker_thread = threading.Thread(
                target=_speech_worker,
                name="arjun-tts",
                daemon=True,
            )
            _tts_worker_thread.start()


def _split_speech(text: str):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks = []
    for sentence in sentences:
        sentence = sentence.strip()
        while len(sentence) > _MAX_SPEECH_CHARS:
            split_at = sentence.rfind(" ", 0, _MAX_SPEECH_CHARS + 1)
            if split_at <= 0:
                split_at = _MAX_SPEECH_CHARS
            chunks.append(sentence[:split_at].strip())
            sentence = sentence[split_at:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks


def stop_speaking():
    """Interrupt speech, stop local playback, and publish an immediate idle/listening state."""
    global _speech_generation, _wake_cooldown_until
    with _speech_lock:
        _speech_generation += 1
        interrupt_event.set()
        _wake_cooldown_until = time.monotonic() + _POST_SPEECH_COOLDOWN

    try:
        import sounddevice
        sounddevice.stop()
    except ImportError:
        pass
    except Exception:
        logger.exception("Could not stop Piper audio playback.")

    with _piper_process_lock:
        process = _piper_process
    if process is not None and process.poll() is None:
        process.terminate()

    engine = _tts_engine
    if engine is not None:
        try:
            engine.stop()
        except Exception:
            logger.exception("Could not stop the pyttsx3 engine.")

    _set_audio_state("PASSIVE_LISTENING")


def speak(text: str):
    """Queue interruptible speech; pyttsx3 is confined to one worker thread."""
    if not text or not text.strip():
        return

    clean = (
        text.replace("**", "")
        .replace("*", "")
        .replace("# ", "")
        .replace("## ", "")
        .replace("`", "")
        .replace("- ", "")
        .replace("• ", "")
        .replace("→", "to")
    )
    chunks = _split_speech(clean)
    if not chunks:
        return

    with _speech_lock:
        generation = _speech_generation
    completed = threading.Event()
    _ensure_tts_worker()
    _tts_requests.put(("speak", generation, chunks, completed))
    completed.wait()


def _is_interrupt_command(text: str) -> bool:
    words = re.findall(r"[a-z']+", text.lower())
    if not words:
        return False
    fillers = {"please", "now", "talking", "speaking"}
    command_index = 0
    if words[:2] == ["hey", "jarvis"]:
        command_index = 2
    elif words[0] in ("arjun", "jarvis"):
        command_index = 1
    if command_index >= len(words) or words[command_index] not in ("stop", "interrupt"):
        return False
    return len(words) - command_index <= 4 and all(
        word in fillers for word in words[command_index + 1:]
    )


def _transcribe_interrupt_audio(audio: np.ndarray, generation: int):
    try:
        with _whisper_lock:
            model = _whisper_model
            if model is None:
                return
            segments, _ = model.transcribe(
                audio,
                language=WHISPER_LANGUAGE,
                beam_size=1,
                vad_filter=False,
            )
            text = " ".join(segment.text for segment in segments).strip()

        if not _is_interrupt_command(text):
            return

        with _audio_state_lock:
            speaking = _audio_state == "SPEAKING"
        if not speaking or _is_interrupted(generation):
            return

        logger.info("Voice interruption command detected.")
        if _interrupt_callback is not None:
            _interrupt_callback()
        else:
            stop_speaking()
    except Exception:
        logger.exception("Voice interruption recognition failed.")
    finally:
        _interrupt_transcription_busy.clear()


def _check_voice_interrupt(audio: np.ndarray):
    global _interrupt_next_check_at
    rms = float(np.sqrt(np.mean(audio * audio))) if len(audio) else 0.0
    if rms < max(0.015, SILENCE_THRESHOLD / 32768.0):
        return
    now = time.monotonic()
    if now < _interrupt_next_check_at or _interrupt_transcription_busy.is_set():
        return
    _interrupt_next_check_at = now + 1.0
    _interrupt_transcription_busy.set()
    with _speech_lock:
        generation = _speech_generation
    threading.Thread(
        target=_transcribe_interrupt_audio,
        args=(audio, generation),
        name="voice-interrupt-recognition",
        daemon=True,
    ).start()


def record_until_silence() -> np.ndarray:
    """Record from the microphone until silence is detected."""
    pa = None
    stream = None
    frames = []
    _set_audio_state("ACTIVE_LISTENING")
    try:
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE,
        )

        silent_chunks = 0
        silence_limit = int(SILENCE_DURATION * SAMPLE_RATE / CHUNK_SIZE)
        max_chunks = int(MAX_RECORD_SECS * SAMPLE_RATE / CHUNK_SIZE)
        total_chunks = 0
        logger.debug("Recording started...")

        while total_chunks < max_chunks:
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            frames.append(data)
            total_chunks += 1
            audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float64)
            rms = np.sqrt(np.mean(audio_np ** 2)) if len(audio_np) else 0.0
            silent_chunks = silent_chunks + 1 if rms < SILENCE_THRESHOLD else 0
            if silent_chunks >= silence_limit and total_chunks > 15:
                break
    finally:
        try:
            if stream is not None:
                try:
                    stream.stop_stream()
                finally:
                    stream.close()
        finally:
            if pa is not None:
                pa.terminate()
            _set_audio_state("PASSIVE_LISTENING")

    raw = b"".join(frames)
    audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    logger.debug("Recorded %.1fs", len(audio_np) / SAMPLE_RATE)
    return audio_np


def transcribe(audio_np: np.ndarray) -> str:
    with _whisper_lock:
        if _whisper_model is None:
            load_whisper()
        try:
            segments, _ = _whisper_model.transcribe(
                audio_np,
                language=WHISPER_LANGUAGE,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            text = " ".join(segment.text for segment in segments).strip()
            logger.info("Transcribed: %r", text)
            return text
        except Exception:
            logger.exception("Transcription failed.")
            return ""


def listen_for_wake_word(callback):
    """Keep the wake listener alive and reconnect its microphone stream on errors."""
    def _run():
        try:
            from openwakeword.model import Model

            wake_model_name = WAKE_WORD
            logger.info("Loading wake word model: %s", wake_model_name)
            wake_model = Model(
                wakeword_models=[wake_model_name],
                inference_framework="onnx",
            )
        except Exception:
            logger.exception(
                "Wake word model initialization failed. Run setup.bat to install "
                "the local OpenWakeWord model."
            )
            _notify_listener_status("WAKE_LISTENER_ERROR")
            return

        while True:
            pa = None
            stream = None
            retry = False
            try:
                pa = pyaudio.PyAudio()
                stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=1280,
                )
                logger.info("Wake word '%s' listening.", wakeword_model_name)
                cooldown_until = 0.0
                speech_frames = deque(maxlen=16)
                speech_check_counter = 0

                while True:
                    chunk = stream.read(1280, exception_on_overflow=False)
                    now = time.monotonic()
                    state = _current_audio_state()
                    if state == "SPEAKING":
                        speech_frames.append(np.frombuffer(chunk, dtype=np.int16))
                        speech_check_counter += 1
                        if len(speech_frames) >= 8 and speech_check_counter >= 8:
                            speech_check_counter = 0
                            audio = np.concatenate(tuple(speech_frames)).astype(np.float32) / 32768.0
                            _check_voice_interrupt(audio)
                    else:
                        speech_frames.clear()
                        speech_check_counter = 0

                    if (
                        now < max(cooldown_until, _wake_cooldown_until)
                        or state == "ACTIVE_LISTENING"
                    ):
                        continue

                    audio_np = np.frombuffer(chunk, dtype=np.int16)
                    prediction = wake_model.predict(audio_np)
                    threshold = WAKE_THRESHOLD * (
                        1.4 if state == "SPEAKING" else 1.0
                    )
                    if any(score >= threshold for score in prediction.values()):
                        logger.info("Wake word detected.")
                        cooldown_until = now + 2.0
                        callback()
            except Exception:
                logger.exception("Wake listener microphone failed; retrying in 2 seconds.")
                _notify_listener_status("WAKE_LISTENER_RETRYING")
                retry = True
            finally:
                if stream is not None:
                    try:
                        stream.stop_stream()
                    except Exception:
                        logger.exception("Could not stop the wake-listener stream.")
                    try:
                        stream.close()
                    except Exception:
                        logger.exception("Could not close the wake-listener stream.")
                if pa is not None:
                    try:
                        pa.terminate()
                    except Exception:
                        logger.exception("Could not release the wake-listener audio device.")
            if retry:
                time.sleep(2.0)

    listener = threading.Thread(target=_run, name="arjun-wake-word", daemon=True)
    listener.start()
    return listener
