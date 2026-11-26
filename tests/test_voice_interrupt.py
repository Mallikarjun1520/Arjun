import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

import voice


class InterruptingEngine:
    def __init__(self):
        self.utterances = []

    def say(self, text):
        self.utterances.append(text)

    def runAndWait(self):
        voice.stop_speaking()

    def stop(self):
        pass


class BlockingEngine:
    def __init__(self):
        self.started = threading.Event()
        self.stopped = threading.Event()

    def say(self, text):
        pass

    def runAndWait(self):
        self.started.set()
        self.stopped.wait(2)

    def stop(self):
        self.stopped.set()


class FakeVoice:
    def __init__(self, name, voice_id):
        self.name = name
        self.id = voice_id


class VoiceSelectionEngine:
    def __init__(self):
        self.voices = [
            FakeVoice("Microsoft Zira Desktop", "zira-id"),
            FakeVoice("Microsoft David Desktop", "david-id"),
        ]
        self.properties = {}

    def getProperty(self, name):
        return self.voices if name == "voices" else self.properties.get(name)

    def setProperty(self, name, value):
        self.properties[name] = value


class VoiceInterruptTests(unittest.TestCase):
    def test_stop_interrupts_before_the_next_short_chunk(self):
        engine = InterruptingEngine()
        sounddevice = types.SimpleNamespace(stop=lambda: None)
        with patch.object(voice, "_piper_settings", return_value=None), \
             patch.dict(sys.modules, {"sounddevice": sounddevice}):
            voice._tts_engine = engine
            voice.speak("First sentence. Second sentence.")

        self.assertEqual(engine.utterances, ["First sentence."])
        self.assertFalse(voice.interrupt_event.is_set())
        self.assertFalse(voice.is_speaking)
        self.assertEqual(voice._current_audio_state(), "PASSIVE_LISTENING")

    def test_stop_returns_and_releases_playback_within_300ms(self):
        engine = BlockingEngine()
        sounddevice = types.SimpleNamespace(stop=lambda: None)
        with patch.object(voice, "_piper_settings", return_value=None), \
             patch.dict(sys.modules, {"sounddevice": sounddevice}):
            voice._tts_engine = engine
            speech_thread = threading.Thread(target=voice.speak, args=("Long answer.",))
            speech_thread.start()
            self.assertTrue(engine.started.wait(1))
            started_at = time.perf_counter()
            voice.stop_speaking()
            elapsed = time.perf_counter() - started_at
            speech_thread.join(1)

        self.assertFalse(speech_thread.is_alive())
        self.assertLess(elapsed, 0.3)

    def test_long_sentences_are_broken_into_bounded_chunks(self):
        chunks = voice._split_speech("word " * 80)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= voice._MAX_SPEECH_CHARS for chunk in chunks))

    def test_voice_interrupt_recognizes_direct_and_wake_prefixed_commands(self):
        self.assertTrue(voice._is_interrupt_command("Stop talking"))
        self.assertTrue(voice._is_interrupt_command("Arjun, interrupt"))
        self.assertTrue(voice._is_interrupt_command("Hey Jarvis, stop"))
        self.assertFalse(voice._is_interrupt_command("I should stop by the store"))
        self.assertFalse(voice._is_interrupt_command("Stop by the store"))

    def test_local_voice_selection_matches_installed_windows_voice(self):
        engine = VoiceSelectionEngine()

        self.assertTrue(voice._apply_tts_voice(engine, "david"))
        self.assertEqual(engine.properties["voice"], "david-id")

    def test_voice_selection_is_applied_by_the_serialized_tts_worker(self):
        engine = VoiceSelectionEngine()
        original_voice = voice.get_tts_voice()

        def apply_request(request):
            _, preferred, completed, result = request
            result.append(voice._apply_tts_voice(engine, preferred))
            completed.set()

        try:
            with patch.object(voice, "_ensure_tts_worker"), \
                 patch.object(voice._tts_requests, "put", side_effect=apply_request):
                self.assertTrue(voice.set_tts_voice("david"))
                self.assertEqual(engine.properties["voice"], "david-id")
                with self.assertRaises(ValueError):
                    voice.set_tts_voice("unknown")
        finally:
            voice._selected_voice = original_voice


if __name__ == "__main__":
    unittest.main()
