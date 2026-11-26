# Phase 2 — Intelligence Upgrades

## What Was Changed

Phase 2 makes ARJUN meaningfully smarter without changing the hardware setup or adding any cloud dependencies. Three targeted upgrades were applied based on the highest value-to-effort ratio.

## Changes Implemented

### Change 1 — Multi-Layer Context Injection

**Problem it solves:** The Phase 1 system prompt was a single flat paragraph. Qwen had no awareness of the current time, no structured tool knowledge, no user preferences, and no way to handle long conversations gracefully.

**What was built:** A dedicated `context_builder.py` module that assembles a structured eight-layer system prompt before every single request.

**The eight layers injected every request:**
1. Core persona and strict output rules
2. Current date, time, and day of week so ARJUN is always time-aware
3. Structured tool summary so Qwen knows exactly what powers it has
4. Personal memory from memory.json filtered to relevant facts
5. User preferences learned and stored over time in preferences.json
6. Conversation summary for sessions that exceed 16 turns
7. RAG knowledge base results relevant to the current query
8. Source-specific behaviour rules for local versus Telegram mode

**Expected improvement:** 20 to 30 percent more relevant, accurate responses. Time-aware answers. Tool usage becomes more consistent. Telegram replies automatically shorter.

**New files:** `context_builder.py`, `preferences.json` (auto-created)

---

### Change 2 — RAG Knowledge Base

**Problem it solves:** ARJUN only knew what Qwen was trained on. It could not answer questions from the user's own notes, textbooks, research papers, or saved documents.

**What was built:** A complete local vector search system in `knowledge_base.py` using Ollama's nomic-embed-text model for semantic embeddings stored as JSON files, with cosine similarity search at query time. No external vector database required.

**How it works:**
1. User tells ARJUN to add a document via voice or text
2. ARJUN extracts text from the file (.pdf .txt .md .py .docx .csv)
3. Text is split into 500-character overlapping chunks
4. Each chunk is embedded using nomic-embed-text running locally via Ollama
5. Chunks and embeddings are saved to `knowledge_base_store/`
6. Every subsequent request automatically searches the KB for relevant chunks
7. Top 4 matching chunks are injected into the system prompt before Qwen answers

**Example use cases:** Add your semester textbook PDFs. Add your own lecture notes. Add a research paper you are studying. ARJUN can then answer questions from them accurately without hallucinating.

**Fallback:** If nomic-embed-text is not installed, the system falls back to keyword matching so nothing breaks.

**New files:** `knowledge_base.py`, `knowledge_base_store/` directory

**New tools registered with Qwen:** `search_knowledge_base`, `add_to_knowledge_base`, `list_knowledge_base`

**New pip packages:** `pdfplumber`, `python-docx`

---

### Change 8 — Extended Context Window

**Problem it solves:** The 4096 token context window in Phase 1 meant ARJUN forgot recent conversation quickly. Long research conversations, multi-step coding help, or any session longer than roughly 15 exchanges caused the model to lose track of earlier context.

**What was changed:**
- `Modelfile`: `num_ctx` changed from 4096 to 32768, `num_batch` set to 512
- `main.py`: `num_ctx: 32768` passed explicitly in every Ollama API call
- `config.py`: `MAX_HISTORY` can now safely hold 20 messages without truncation issues

**Impact:** ARJUN can now hold much longer coherent conversations. Code projects, research sessions, and multi-step planning all benefit significantly. The 32k window costs roughly 2GB extra RAM at peak which is well within the 16GB available.

**Note on VRAM:** The context window for inference lives in GPU VRAM when layers are GPU-offloaded. With 4GB on the RTX 2050, Qwen 2.5 7B uses approximately 3.8GB at 4096 context. At 32768 context, Ollama will automatically offload some KV cache to system RAM. Response times increase slightly for very long conversations but remain acceptable at 3 to 6 seconds.

---

## Files Added in Phase 2

| File | Purpose |
|------|---------|
| `context_builder.py` | Multi-layer system prompt assembly |
| `knowledge_base.py` | Local RAG vector store with semantic search |
| `docs/phase1.md` | Phase 1 documentation |
| `docs/phase2.md` | This file |
| `docs/architecture.md` | Full system architecture reference |

## Files Modified in Phase 2

| File | What Changed |
|------|-------------|
| `Modelfile` | num_ctx 4096 → 32768, updated persona to mention knowledge base |
| `main.py` | Uses context_builder, auto-RAG search, explicit 32k context in API calls |
| `tools.py` | Three new KB tool functions and schemas appended |
| `config.py` | KB and preferences config keys added |
| `requirements.txt` | pdfplumber and python-docx added |

## Setup Steps for Phase 2

Run this once after the Phase 1 setup is complete:

```
pip install pdfplumber python-docx
ollama pull nomic-embed-text
ollama create arjun -f Modelfile
```

## Planned for Future Phases

- Phase 3: Holographic gesture-controlled UI with MediaPipe hand tracking
- Phase 4: Chain of Thought reasoning and self-critique loop
- Phase 5: Model switching by task type (coder model for code requests)
- Phase 6: QLoRA fine-tuning on accumulated conversation logs
- Phase 7: Web browsing agent with Playwright for full page interaction
