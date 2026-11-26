# ARJUN System Architecture (Updated Phase 4)

## Full Name
**Automated Retrieval, Judgment and Utility Network**

---

## Complete File Map

```
arjun/
├── Modelfile                   Ollama persona, 32k context
├── config.py                   All settings — single source of truth
├── main.py                     Central agent loop (Phase 4)
├── context_builder.py          8-layer system prompt (Phase 2)
├── knowledge_base.py           RAG vector store (Phase 2)
├── briefing.py                 Morning briefing assembler (Phase 4)
├── whatsapp_bridge.py          WhatsApp Web integration (Phase 4)
├── browser_agent.py            Playwright web browser (Phase 4)
├── tools.py                    All tool functions + schemas (all phases)
├── email_tools.py              Gmail IMAP + SMTP (Phase 1)
├── app_launcher.py             Desktop app launcher (Phase 3)
├── gesture_control.py          MediaPipe gesture recognition (Phase 3)
├── holographic_ui.py           Frameless transparent UI (Phase 3)
├── animations.py               Molecule visualizations (Phase 1)
├── ui.py                       Flat UI fallback (Phase 1)
├── voice.py                    Wake word + STT + TTS (Phase 1)
├── telegram_bot.py             Telegram remote interface (Phase 1)
├── launcher.pyw                Silent Windows launcher (Phase 1)
├── startup_listener.py         Always-on wake word (Phase 1)
├── create_shortcut.bat         Desktop icon creator (Phase 1)
├── generate_icon.py            .ico generator (Phase 1)
├── setup.bat                   Windows setup script (Phase 1)
├── memory.json                 Persistent user memory
├── preferences.json            Learned user preferences
├── requirements.txt            All pip dependencies
├── .env                        Credentials
├── arjun.log                   Runtime log
├── whatsapp_session/           WhatsApp Web session (Phase 4)
├── knowledge_base_store/       RAG chunks and embeddings (Phase 2)
└── docs/
    ├── architecture.md         This file
    ├── phase1.md
    ├── phase2.md
    ├── phase3.md
    └── phase4.md
```

---

## Full System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        INPUT SOURCES                         │
│  Voice mic │ UI type │ Telegram │ WhatsApp │ Gesture camera  │
└──────┬─────┴────┬────┴────┬─────┴────┬─────┴────┬────────────┘
       │          │         │          │          │
       ▼          ▼         ▼          ▼          ▼
┌──────────┐ ┌────────┐ ┌───────┐ ┌────────┐ ┌──────────────┐
│ voice.py │ │  UI    │ │  TG   │ │  WA    │ │gesture_      │
│ Whisper  │ │ input  │ │ bot   │ │ bridge │ │control.py    │
│ STT(CPU) │ │ queue  │ │ queue │ │ queue  │ │MediaPipe(CPU)│
└──────────┘ └────────┘ └───────┘ └────────┘ └──────────────┘
       │          │         │          │          │
       └──────────┴────┬────┴──────────┘          │
                       ▼                          ▼
          ┌────────────────────────┐   ┌─────────────────────┐
          │     main.py            │   │  UI events queue    │
          │  - destructive check   │◄──│  gesture callbacks  │
          │  - RAG auto-search     │   └─────────────────────┘
          │  - context assembly    │
          │  - tool dispatch loop  │
          └────────────┬───────────┘
                       │
          ┌────────────▼────────────┐
          │   context_builder.py    │
          │   8-layer prompt        │
          │   + memory + RAG        │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  Ollama localhost:11434 │
          │  Qwen 2.5 7B  32k ctx  │
          │  Tool calling enabled  │
          └────────────┬────────────┘
                       │ tool_calls
          ┌────────────▼────────────────────────────────────┐
          │              tools.py dispatcher                │
          │                                                 │
          │  web_search      deep_research    calc_math     │
          │  save_memory     recall_memory    system_ctrl   │
          │  send_email      check_email      open_app      │
          │  search_kb       add_to_kb        list_kb       │
          │  send_whatsapp   read_whatsapp    reply_wa      │
          │  browse_url      browser_search   fill_form     │
          └────────────┬────────────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │      OUTPUT LAYER       │
          │  voice.py speak()       │
          │  holographic_ui.py      │
          │  telegram reply         │
          │  WhatsApp reply         │
          └─────────────────────────┘
```

---

## Thread Map (Phase 4)

| Thread | Daemon | Responsibility |
|--------|--------|---------------|
| Main | No | PyQt5 UI event loop |
| Voice loop | Yes | Records on wake trigger, STT |
| UI input loop | Yes | Typed messages from UI |
| Telegram agent | Yes | Telegram messages through agent |
| Telegram bot | Yes | Polls Telegram API |
| WhatsApp client | Yes | WhatsApp Web session + polling |
| Wake flag watcher | Yes | Watches .wake_trigger file |
| Gesture controller | Yes | MediaPipe camera loop at 30fps |
| Briefing thread | Yes | Parallel fetch on startup |
| Browser event loop | Yes | Playwright async event loop |
| TTS worker | Yes | Owns pyttsx3 and serializes interruptible speech |
| Wake-word listener | Yes | Keeps its microphone stream open and skips active recording |

TTS is split into sentence/short-length chunks and uses a generation-based
interrupt signal. The wake-word loop stays alive during speech, uses a higher
trigger threshold while ARJUN is speaking, then ignores wake predictions for
450 ms after playback. During speech, bounded local Whisper checks the same
microphone stream for "stop" or "interrupt"; a match stops playback and starts
recording the follow-up. The local UI can select Zira or David, or enable
continuous follow-up listening (off by default). Audio-state transitions are
forwarded to the UI.

---

## Tool Count by Phase

| Phase | Tools Added | Total |
|-------|-------------|-------|
| Phase 1 | web_search, deep_research, calculate_math, save_memory, recall_memory, system_control, send_email, check_email | 8 |
| Phase 2 | search_knowledge_base, add_to_knowledge_base, list_knowledge_base | 11 |
| Phase 3 | open_application, list_applications | 13 |
| Phase 4 | send_whatsapp, read_whatsapp, reply_whatsapp, whatsapp_status, browse_url, browser_search, fill_form, click_and_read | 21 |

Tool schemas are passed to Ollama through `/api/chat`; the Qwen model uses
Ollama's native tool-call support rather than a custom Modelfile chat template.
The UI reports IDLE, LISTENING, THINKING, and SPEAKING states, while the
gesture badge remains independently visible.

---

## Phase Roadmap

| Phase | Status | Focus |
|-------|--------|-------|
| Phase 1 | Complete | Foundation |
| Phase 2 | Complete | RAG + context + 32k window |
| Phase 3 | Complete | Holographic UI + gestures + app launcher |
| Phase 4 | Complete | Briefing + WhatsApp + browser agent |
| Phase 5 | Planned | Chain of Thought + model switching |
| Phase 6 | Planned | QLoRA fine-tuning |
| Phase 7 | Planned | Screen awareness + vision |
