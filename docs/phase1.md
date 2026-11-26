# Phase 1 — Foundation

## What Was Built

Phase 1 is the complete working foundation of ARJUN (Automated Retrieval, Judgment and Utility Network). It delivers a fully local, fully private AI assistant that runs entirely on the user's laptop with no cloud dependencies.

## Files Introduced in Phase 1

| File | Purpose |
|------|---------|
| `Modelfile` | Custom Ollama persona with strict plain-English TTS rules |
| `config.py` | Central configuration — all settings in one place |
| `tools.py` | All agent tool functions and Ollama JSON schemas |
| `voice.py` | Wake word, microphone recording, Whisper STT, Piper TTS |
| `main.py` | Central agent loop — conversation, tool dispatch, threading |
| `email_tools.py` | Gmail send and receive via IMAP and SMTP |
| `telegram_bot.py` | Remote phone control via Telegram bot |
| `ui.py` | PyQt5 interactive conversation window |
| `animations.py` | Molecule visualizations — thinking and speaking states |
| `launcher.pyw` | Silent Windows launcher, no terminal window |
| `startup_listener.py` | Always-on wake word listener, starts with Windows |
| `create_shortcut.bat` | Creates desktop icon and startup entry |
| `generate_icon.py` | Generates the orange molecule .ico desktop icon |
| `memory.json` | Persistent user memory store |
| `requirements.txt` | All pip dependencies |
| `setup.bat` | One-click Windows setup script |
| `.env` | Credentials template for Telegram and Gmail |

## Core Capabilities

**Voice Pipeline (CPU only)**
OpenWakeWord listens passively for "Hey Jarvis" in the background. On detection, Faster-Whisper (base.en, int8, CPU) transcribes speech. While ARJUN speaks, the existing microphone stream also checks for local "stop" or "interrupt" commands and starts recording the follow-up. A dedicated worker serializes pyttsx3 speech and supports interruption; a local Piper CLI/model is used when both are installed. The local UI can switch between installed Zira and David voices, and its optional continuous-conversation toggle (off by default) listens for another turn after each reply. The entire audio pipeline never touches the RTX 2050 VRAM.

**LLM Brain**
Qwen 2.5 7B runs via Ollama at localhost:11434. The Modelfile locks in the ARJUN persona with strict no-markdown rules so TTS reads cleanly. Context window set to 4096 tokens in Phase 1.

**Agentic Tools**
Qwen has native function calling enabled with six tool schemas registered. Tool dispatch is handled by a central dispatcher in tools.py. Tools include web search, deep research, math engine, memory, system control, and email.

**Dual Interface**
Local PyQt5 window with animated molecule visualization. Remote Telegram interface so the user can message ARJUN from their phone while the laptop does all processing.

**Windows Integration**
Frameless icon on the desktop. Startup listener registered in the Windows registry. Silent launch via .pyw file. Arjun is reachable by voice the moment Windows boots.

## Hardware Targets

- Laptop: HP Victus
- GPU: NVIDIA RTX 2050 (4GB VRAM) — used exclusively for Qwen inference
- CPU: handles all voice, tools, scraping, threading
- RAM: 16GB system RAM

## Known Limitations at End of Phase 1

- System prompt is a single flat string with no structure
- Context window limited to 4096 tokens
- Memory stored as flat JSON facts, all injected every request
- No personal document search capability
- No semantic relevance filtering for memory
