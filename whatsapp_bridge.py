"""
whatsapp_bridge.py — ARJUN WhatsApp Integration (Phase 4)
Connects to your existing WhatsApp account via whatsapp-web.py.
One-time QR code scan on first setup, then runs silently.

Capabilities:
  - Send messages to any contact by name
  - Read recent messages from a contact
  - Get notified when important contacts message you
  - Reply to the last received message
  - Check unread message count
"""

import os
import json
import time
import logging
import threading
import asyncio
from datetime import datetime
from typing import Optional, Callable

from config import (
    WHATSAPP_SESSION_DIR,
    WHATSAPP_IMPORTANT_CONTACTS,
    WHATSAPP_CHECK_INTERVAL,
    WHATSAPP_MAX_MSG_LENGTH
)

logger = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────
_client         = None
_client_ready   = threading.Event()
_client_lock    = threading.RLock()
_last_messages  = {}       # contact_name → list of recent messages
_unread_cache   = []       # list of unread message dicts
_notify_callback: Optional[Callable] = None   # called when important contact msgs
_loop           = None


# ─────────────────────────────────────────────
#  CLIENT SETUP
# ─────────────────────────────────────────────

def _start_client():
    """
    Start the WhatsApp Web client in a background thread.
    Shows QR code in terminal on first run.
    Session is saved to WHATSAPP_SESSION_DIR after first scan.
    """
    global _client, _loop

    try:
        from webwhatsapi import WhatsAPIDriver
        from webwhatsapi.objects.message import Message
    except ImportError:
        logger.error(
            "whatsapp-web.py not installed. "
            "Run: pip install webwhatsapp"
        )
        return

    os.makedirs(WHATSAPP_SESSION_DIR, exist_ok=True)

    logger.info("Starting WhatsApp Web client...")
    logger.info("If this is your first time, scan the QR code that appears.")

    try:
        _client = WhatsAPIDriver(
            profile=WHATSAPP_SESSION_DIR,
            client="chrome",
            headless=False,          # visible on first scan, can set True after
            logger=logger
        )

        logger.info("Waiting for WhatsApp Web to load...")
        _client.wait_for_login()
        logger.info("WhatsApp connected.")
        _client_ready.set()

        # Start polling loop
        _poll_messages()

    except Exception as e:
        logger.error(f"WhatsApp client error: {e}")


def _poll_messages():
    """Poll for new messages on a timer and cache them."""
    global _unread_cache

    while True:
        try:
            if _client and _client_ready.is_set():
                with _client_lock:
                    unread = _client.get_unread()
                    _unread_cache = []

                    for chat in unread:
                        contact_name = getattr(chat, "name", "Unknown")
                        messages     = getattr(chat, "messages", [])

                        for msg in messages:
                            content = getattr(msg, "content", "")
                            sender  = getattr(msg, "sender", {})
                            sender_name = getattr(sender, "push_name",
                                         getattr(sender, "id", "Unknown"))
                            timestamp = getattr(msg, "timestamp",
                                       datetime.now().timestamp())

                            entry = {
                                "contact":   contact_name,
                                "sender":    sender_name,
                                "content":   content,
                                "timestamp": timestamp,
                                "chat_id":   getattr(chat, "id", "")
                            }
                            _unread_cache.append(entry)

                            for important_contact in WHATSAPP_IMPORTANT_CONTACTS:
                                if (
                                    important_contact.lower() in contact_name.lower()
                                    or important_contact.lower() in sender_name.lower()
                                ):
                                    if _notify_callback:
                                        short = content[:80] + "..." if len(content) > 80 else content
                                        _notify_callback(
                                            f"{sender_name} just messaged you on WhatsApp: {short}"
                                        )
                                    break

        except Exception as e:
            logger.debug(f"WhatsApp poll error: {e}")

        time.sleep(WHATSAPP_CHECK_INTERVAL)


# ─────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────

def start_whatsapp(notify_callback: Optional[Callable] = None):
    """
    Start WhatsApp bridge in a background daemon thread.
    notify_callback(text) is called when an important contact messages.
    """
    global _notify_callback
    _notify_callback = notify_callback

    t = threading.Thread(target=_start_client, daemon=True)
    t.start()
    logger.info("WhatsApp bridge thread started.")


def send_whatsapp_message(contact_name: str, message: str) -> str:
    """
    Send a WhatsApp message to a contact by name.
    Uses fuzzy matching to find the right contact.
    """
    if not _client_ready.is_set():
        return "WhatsApp is not connected yet. It may still be loading or needs a QR scan."

    try:
        # Search contacts
        with _client_lock:
            contacts = _client.get_contacts()
        matched  = None

        for contact in contacts:
            name = getattr(contact, "push_name",
                   getattr(contact, "name", "")).lower()
            if contact_name.lower() in name or name in contact_name.lower():
                matched = contact
                break

        if not matched:
            return f"I could not find a WhatsApp contact named {contact_name}."

        contact_id = getattr(matched, "id", "")
        with _client_lock:
            _client.send_message_to_id(contact_id, message)

        logger.info(f"WhatsApp message sent to {contact_name}")
        return f"Message sent to {contact_name} on WhatsApp."

    except Exception as e:
        logger.error(f"WhatsApp send error: {e}")
        return f"Failed to send WhatsApp message to {contact_name}: {str(e)}"


def read_whatsapp_messages(contact_name: str = "", count: int = 5) -> str:
    """
    Read recent messages from a contact or all unread messages.
    Returns a plain text summary suitable for TTS.
    """
    if not _client_ready.is_set():
        return "WhatsApp is not connected yet."

    try:
        with _client_lock:
            unread_cache = list(_unread_cache)
        if not contact_name:
            # Read all unread
            if not unread_cache:
                return "You have no unread WhatsApp messages right now."

            summaries = []
            for msg in unread_cache[:count]:
                content = msg["content"][:WHATSAPP_MAX_MSG_LENGTH]
                summaries.append(
                    f"From {msg['sender']}: {content}"
                )
            count_str = len(unread_cache)
            intro = f"You have {count_str} unread WhatsApp message{'s' if count_str != 1 else ''}. "
            return intro + ". Next message: ".join(summaries)

        else:
            # Read from specific contact
            relevant = [
                m for m in unread_cache
                if contact_name.lower() in m["contact"].lower() or
                   contact_name.lower() in m["sender"].lower()
            ]

            if not relevant:
                # Try fetching from chat history
                try:
                    with _client_lock:
                        chats = _client.get_all_chats()
                    for chat in chats:
                        chat_name = getattr(chat, "name", "").lower()
                        if contact_name.lower() in chat_name:
                            with _client_lock:
                                messages = _client.get_messages(chat)
                            if messages:
                                last = messages[-min(count, len(messages)):]
                                parts = []
                                for m in last:
                                    who = "You" if getattr(m, "is_sender", False) else contact_name
                                    parts.append(f"{who}: {getattr(m, 'content', '')[:100]}")
                                return f"Recent messages with {contact_name}: " + ". ".join(parts)
                except Exception:
                    pass
                return f"No unread messages from {contact_name}."

            parts = [f"{m['sender']}: {m['content'][:WHATSAPP_MAX_MSG_LENGTH]}"
                     for m in relevant[:count]]
            return f"Messages from {contact_name}: " + ". Next: ".join(parts)

    except Exception as e:
        logger.error(f"WhatsApp read error: {e}")
        return f"Could not read WhatsApp messages: {str(e)}"


def reply_last_whatsapp(message: str) -> str:
    """Reply to the most recently received WhatsApp message."""
    if not _client_ready.is_set():
        return "WhatsApp is not connected yet."

    try:
        with _client_lock:
            unread_cache = list(_unread_cache)
        if not unread_cache:
            return "There are no recent messages to reply to."

        last   = unread_cache[-1]
        chat_id = last.get("chat_id", "")
        contact = last.get("sender", "someone")

        if not chat_id:
            return "Could not find the chat to reply to."

        with _client_lock:
            _client.send_message_to_id(chat_id, message)
        return f"Reply sent to {contact} on WhatsApp."

    except Exception as e:
        logger.error(f"WhatsApp reply error: {e}")
        return f"Failed to send reply: {str(e)}"


def get_whatsapp_status() -> str:
    """Return connection status and unread count."""
    if not _client_ready.is_set():
        return "WhatsApp is still connecting. This can take up to 30 seconds on first run."
    with _client_lock:
        unread = len(_unread_cache)
    return f"WhatsApp is connected. You have {unread} unread message{'s' if unread != 1 else ''}."


# ─────────────────────────────────────────────
#  TOOL SCHEMAS
# ─────────────────────────────────────────────

WHATSAPP_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "send_whatsapp",
            "description": (
                "Send a WhatsApp message to a contact by name. "
                "Use when the user asks to message, text, or WhatsApp someone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_name": {
                        "type": "string",
                        "description": "The name of the WhatsApp contact to message."
                    },
                    "message": {
                        "type": "string",
                        "description": "The message text to send."
                    }
                },
                "required": ["contact_name", "message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_whatsapp",
            "description": (
                "Read unread WhatsApp messages. Can read all unread messages "
                "or messages from a specific contact."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_name": {
                        "type": "string",
                        "description": "Contact name to read from. Leave empty for all unread."
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of messages to read. Default 5."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reply_whatsapp",
            "description": "Reply to the most recently received WhatsApp message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The reply message to send."
                    }
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "whatsapp_status",
            "description": "Check WhatsApp connection status and unread message count.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }
]
