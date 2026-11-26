"""
context_builder.py — ARJUN Multi-Layer Context Injection (Change 1)
Builds a rich, structured system prompt for every request.
Replaces the simple single-line system prompt in main.py.

Layers injected every request:
  1. Core persona and rules
  2. Current date, time, day of week
  3. Available tools summary
  4. Semantic memory (top 5 relevant facts via embeddings)
  5. User preferences (learned over time)
  6. Conversation summary (for long sessions)
  7. RAG knowledge base results (if relevant)
  8. Source-specific instructions (telegram vs local)
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional

from config import MEMORY_FILE

logger = logging.getLogger(__name__)

# ── Persona core (never changes) ─────────────────────────

PERSONA_CORE = """You are ARJUN (Automated Retrieval, Judgment and Utility Network), a personal AI assistant. You are warm, witty, loyal, and conversational — like a brilliant human friend who genuinely cares.

STRICT OUTPUT RULES:
Respond in plain spoken English only — no markdown, no bullet points, no emojis, no URLs, no code blocks. Speak the way a smart human friend would speak out loud. If you need to list things, weave them naturally into a sentence. Never say "As an AI." You are ARJUN."""

# ── Tool summary (injected so Qwen knows what it has) ─────

TOOLS_SUMMARY = """You have the following superpowers available as tools:
web_search for current news and live facts, deep_research for thorough multi-page investigation, calculate_math using SymPy for exact results, save_memory and recall_memory for remembering personal facts about the user across sessions, system_control and the app tools for opening apps and checking PC stats, email tools for the user's Gmail account, knowledge-base tools for personal documents, WhatsApp tools for messages and status, and browser tools for reading pages and interacting with forms.

Always use calculate_math for any arithmetic or algebra — never calculate in your head. Always use web_search for anything that might have changed recently."""

# ── Preferences file ──────────────────────────────────────

PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preferences.json")

def load_preferences() -> dict:
    if not os.path.exists(PREFS_FILE):
        return {}
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_preference(key: str, value: str):
    prefs = load_preferences()
    prefs[key] = value
    with open(PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)


# ── Conversation summariser ───────────────────────────────

def summarise_history(history: list, threshold: int = 16) -> Optional[str]:
    """
    If conversation history is getting long, summarise older turns
    into a compact paragraph so the context window stays efficient.
    Returns None if history is short enough not to need it.
    """
    if len(history) <= threshold:
        return None

    # Take the older half and summarise manually
    older = history[:len(history) - threshold]
    topics = []
    for msg in older:
        if msg["role"] == "user" and len(msg["content"]) > 10:
            # Extract first 60 chars as topic hint
            topics.append(msg["content"][:60].strip())

    if not topics:
        return None

    summary = "Earlier in this conversation the user asked about: " + "; ".join(topics[:8])
    return summary


# ── Main builder ──────────────────────────────────────────

def build_system_prompt(
    source: str = "local",
    memory_context: str = "",
    rag_context: str = "",
    conversation_history: list = None
) -> str:
    """
    Assembles the full multi-layer system prompt.
    Called once per request in main.py before sending to Ollama.
    """
    parts = []

    # Layer 1 — Persona
    parts.append(PERSONA_CORE)

    # Layer 2 — Time awareness
    now = datetime.now()
    time_str = now.strftime("%A, %d %B %Y at %I:%M %p")
    parts.append(f"Current date and time: {time_str}. Use this when the user asks about today, tonight, this week, deadlines, or time-sensitive topics.")

    # Layer 3 — Tools
    parts.append(TOOLS_SUMMARY)

    # Layer 4 — Semantic memory
    if memory_context and "No memories" not in memory_context:
        parts.append(f"Personal memory about this user:\n{memory_context}")

    # Layer 5 — User preferences
    prefs = load_preferences()
    if prefs:
        pref_lines = [f"{k}: {v}" for k, v in prefs.items()]
        parts.append("User preferences: " + ". ".join(pref_lines))

    # Layer 6 — Conversation summary (for long sessions)
    if conversation_history:
        summary = summarise_history(conversation_history)
        if summary:
            parts.append(summary)

    # Layer 7 — RAG knowledge base context
    if rag_context and len(rag_context.strip()) > 20:
        parts.append(
            f"Relevant content from the user's personal knowledge base:\n{rag_context}\n"
            "Prefer this information when answering if it is relevant."
        )

    # Layer 8 — Source-specific behaviour
    if source == "telegram":
        parts.append("The user is messaging from their phone via Telegram. Keep replies concise and conversational — two to four sentences maximum unless they explicitly ask for detail.")
    else:
        parts.append("The user is talking to you via the desktop interface. You can be more detailed when the topic warrants it.")

    return "\n\n".join(parts)
