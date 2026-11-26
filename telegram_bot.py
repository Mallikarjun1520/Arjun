"""
telegram_bot.py — ARJUN Remote Control via Telegram
Runs as a background thread alongside main.py.
Receives text and voice messages from your phone,
feeds them into the shared Arjun agent queue,
and sends the reply back to your Telegram chat.
"""

import os
import logging
import asyncio
import tempfile
import threading
import queue as Queue

import requests as req
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, filters, ContextTypes
)

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from voice import transcribe
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


class TelegramBridge:
    """
    Bridges Telegram messages into the main Arjun agent loop.
    - Puts incoming user text into agent_input_queue
    - Reads Arjun's reply from agent_output_queue and sends it back
    """

    def __init__(self, agent_input_queue: Queue.Queue, agent_output_queue: Queue.Queue):
        self._in_q  = agent_input_queue   # → agent (from Telegram)
        self._out_q = agent_output_queue  # ← agent (reply to send)
        self._app   = None
        self._loop  = None

    # ── Telegram Handlers ────────────────────────────────

    async def _start_command(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != TELEGRAM_CHAT_ID:
            return
        await update.message.reply_text(
            "Arjun online. Send me a message or voice note and I will get right on it."
        )

    async def _handle_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != TELEGRAM_CHAT_ID:
            logger.warning(f"Blocked message from unknown chat: {update.effective_chat.id}")
            await update.message.reply_text("Sorry, you are not authorised to use this assistant.")
            return

        user_text = update.message.text.strip()
        if not user_text:
            return

        logger.info(f"[Telegram] Received: {user_text}")

        # Mark source as telegram so main.py can shorten responses if needed
        self._in_q.put({"text": user_text, "source": "telegram"})

        # Wait for reply (blocking with timeout)
        try:
            reply = self._out_q.get(timeout=60)
        except Queue.Empty:
            reply = "Sorry, I took too long to respond. Try again."

        await update.message.reply_text(reply)

    async def _handle_voice(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != TELEGRAM_CHAT_ID:
            return

        await update.message.reply_text("Got your voice note, give me a moment.")

        try:
            # Download voice file
            voice_file = await update.message.voice.get_file()
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                tmp_path = tmp.name
            await voice_file.download_to_drive(tmp_path)

            # Convert ogg → float32 numpy via soundfile
            data, samplerate = sf.read(tmp_path)
            os.unlink(tmp_path)

            # Resample to 16kHz if needed
            if samplerate != 16000:
                import scipy.signal as scipy_signal
                samples = int(len(data) * 16000 / samplerate)
                data = scipy_signal.resample(data, samples)

            if data.ndim > 1:
                data = data[:, 0]  # mono

            audio_np = data.astype(np.float32)
            text = transcribe(audio_np)

            if not text:
                await update.message.reply_text("I could not make out what you said. Try again?")
                return

            logger.info(f"[Telegram Voice] Transcribed: {text}")
            self._in_q.put({"text": text, "source": "telegram"})

            reply = self._out_q.get(timeout=60)
            await update.message.reply_text(reply)

        except Exception as e:
            logger.error(f"Voice handling error: {e}")
            await update.message.reply_text(f"Something went wrong processing your voice note: {str(e)}")

    # ── Run ──────────────────────────────────────────────

    def _run_bot(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._app = (
            ApplicationBuilder()
            .token(TELEGRAM_BOT_TOKEN)
            .build()
        )
        self._app.add_handler(CommandHandler("start", self._start_command))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        self._app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))

        logger.info("Telegram bot started. Polling for messages...")
        self._app.run_polling(stop_signals=None)

    def start(self):
        """Start the Telegram bot in a background daemon thread."""
        if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
            logger.warning("Telegram bot token not configured. Skipping Telegram integration.")
            return
        t = threading.Thread(target=self._run_bot, daemon=True)
        t.start()
        logger.info("Telegram bridge thread started.")
