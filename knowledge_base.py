"""
knowledge_base.py — ARJUN RAG Knowledge Base (Change 2)
Local vector store using ChromaDB + Ollama embeddings.
Lets ARJUN search through the user's own documents, notes,
textbooks, research papers, and saved web pages.

Supported input formats: .txt .md .pdf .py .json .csv

Usage:
  kb = KnowledgeBase()
  kb.add_document("path/to/notes.pdf")
  kb.add_document("path/to/my_notes.txt")
  results = kb.search("what is gradient descent", n=5)
"""

import os
import json
import logging
import hashlib
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

KB_DIR        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base_store")
KB_INDEX_FILE = os.path.join(KB_DIR, "index.json")
EMBED_MODEL   = "nomic-embed-text"   # pulled via: ollama pull nomic-embed-text
OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
CHUNK_SIZE    = 500    # characters per chunk
CHUNK_OVERLAP = 50     # overlap between chunks


# ── Embedding via Ollama ──────────────────────────────────

def get_embedding(text: str) -> Optional[List[float]]:
    """Get a vector embedding for a piece of text using Ollama."""
    try:
        import requests
        response = requests.post(
            OLLAMA_EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=30
        )
        response.raise_for_status()
        return response.json().get("embedding", None)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return None


# ── Text extraction ───────────────────────────────────────

def extract_text(filepath: str) -> str:
    """Extract plain text from various file formats."""
    ext = os.path.splitext(filepath)[1].lower()

    if ext in (".txt", ".md", ".py", ".json", ".csv"):
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    elif ext == ".pdf":
        try:
            import pdfplumber
            text = ""
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
            return text
        except ImportError:
            logger.warning("pdfplumber not installed. Run: pip install pdfplumber")
            return ""
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return ""

    elif ext in (".docx",):
        try:
            import docx
            doc = docx.Document(filepath)
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            logger.warning("python-docx not installed. Run: pip install python-docx")
            return ""

    else:
        logger.warning(f"Unsupported file type: {ext}")
        return ""


# ── Chunking ──────────────────────────────────────────────

def chunk_text(text: str, source: str) -> List[Dict]:
    """Split text into overlapping chunks for embedding."""
    chunks = []
    text   = text.strip()
    start  = 0
    idx    = 0

    while start < len(text):
        end   = min(start + CHUNK_SIZE, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({
                "id":      f"{hashlib.md5(source.encode()).hexdigest()[:8]}_{idx}",
                "text":    chunk,
                "source":  source,
                "chunk":   idx,
                "created": datetime.now().isoformat()
            })
            idx += 1
        start = end - CHUNK_OVERLAP if end < len(text) else len(text)

    return chunks


# ── Knowledge Base ────────────────────────────────────────

class KnowledgeBase:

    def __init__(self):
        os.makedirs(KB_DIR, exist_ok=True)
        self._index = self._load_index()
        self._chunks: List[Dict] = []
        self._embeddings: List[List[float]] = []
        self._load_all_chunks()

    # ── Index management ──────────────────────────────────

    def _load_index(self) -> Dict:
        if os.path.exists(KB_INDEX_FILE):
            with open(KB_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"documents": {}}

    def _save_index(self):
        with open(KB_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2)

    def _chunk_file(self, doc_hash: str) -> str:
        return os.path.join(KB_DIR, f"{doc_hash}_chunks.json")

    def _embedding_file(self, doc_hash: str) -> str:
        return os.path.join(KB_DIR, f"{doc_hash}_embeddings.json")

    def _load_all_chunks(self):
        """Load all stored chunks and embeddings into memory."""
        self._chunks = []
        self._embeddings = []

        for doc_hash, doc_info in self._index["documents"].items():
            cf = self._chunk_file(doc_hash)
            ef = self._embedding_file(doc_hash)

            if os.path.exists(cf) and os.path.exists(ef):
                with open(cf, "r", encoding="utf-8") as f:
                    chunks = json.load(f)
                with open(ef, "r", encoding="utf-8") as f:
                    embeddings = json.load(f)

                if len(chunks) == len(embeddings):
                    self._chunks.extend(chunks)
                    self._embeddings.extend(embeddings)

        logger.info(f"Knowledge base loaded: {len(self._chunks)} chunks from {len(self._index['documents'])} documents.")

    # ── Add document ──────────────────────────────────────

    def add_document(self, filepath: str) -> str:
        """
        Add a document to the knowledge base.
        Extracts text, chunks it, embeds each chunk, and stores everything.
        Returns a status message.
        """
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"

        # Hash the file path + size as a unique ID
        stat     = os.stat(filepath)
        doc_hash = hashlib.md5(f"{filepath}{stat.st_size}".encode()).hexdigest()[:16]
        filename = os.path.basename(filepath)

        if doc_hash in self._index["documents"]:
            return f"{filename} is already in the knowledge base."

        logger.info(f"Adding document: {filename}")

        # Extract text
        text = extract_text(filepath)
        if not text.strip():
            return f"Could not extract text from {filename}."

        # Chunk
        chunks = chunk_text(text, filepath)
        if not chunks:
            return f"Could not create chunks from {filename}."

        # Embed each chunk
        logger.info(f"Embedding {len(chunks)} chunks from {filename}...")
        embeddings = []
        failed     = 0

        for i, chunk in enumerate(chunks):
            emb = get_embedding(chunk["text"])
            if emb:
                embeddings.append(emb)
            else:
                embeddings.append([0.0] * 768)  # zero vector fallback
                failed += 1

        # Save to disk
        with open(self._chunk_file(doc_hash), "w", encoding="utf-8") as f:
            json.dump(chunks, f)
        with open(self._embedding_file(doc_hash), "w", encoding="utf-8") as f:
            json.dump(embeddings, f)

        # Update index
        self._index["documents"][doc_hash] = {
            "filename": filename,
            "filepath": filepath,
            "chunks":   len(chunks),
            "added":    datetime.now().isoformat()
        }
        self._save_index()

        # Reload into memory
        self._load_all_chunks()

        warn = f" ({failed} chunks failed to embed)" if failed else ""
        return f"Added {filename} to knowledge base with {len(chunks)} chunks{warn}."

    # ── Remove document ───────────────────────────────────

    def remove_document(self, filename: str) -> str:
        """Remove a document from the knowledge base by filename."""
        target_hash = None
        for doc_hash, info in self._index["documents"].items():
            if info["filename"] == filename:
                target_hash = doc_hash
                break

        if not target_hash:
            return f"{filename} not found in the knowledge base."

        for f in [self._chunk_file(target_hash), self._embedding_file(target_hash)]:
            if os.path.exists(f):
                os.remove(f)

        del self._index["documents"][target_hash]
        self._save_index()
        self._load_all_chunks()
        return f"Removed {filename} from the knowledge base."

    # ── List documents ────────────────────────────────────

    def list_documents(self) -> str:
        """Return a plain-text list of all documents in the knowledge base."""
        docs = self._index.get("documents", {})
        if not docs:
            return "The knowledge base is empty. Add documents using the add_to_knowledge_base tool."
        lines = [f"{info['filename']} ({info['chunks']} chunks, added {info['added'][:10]})"
                 for info in docs.values()]
        return "Documents in knowledge base: " + ", ".join(lines)

    # ── Search ────────────────────────────────────────────

    def search(self, query: str, n: int = 5) -> str:
        """
        Semantic search over all stored documents.
        Returns the top n most relevant chunks as plain text.
        """
        if not self._chunks:
            return ""

        query_emb = get_embedding(query)
        if not query_emb:
            # Fallback: keyword search
            return self._keyword_search(query, n)

        # Cosine similarity
        import math

        def cosine_sim(a: List[float], b: List[float]) -> float:
            dot   = sum(x * y for x, y in zip(a, b))
            mag_a = math.sqrt(sum(x * x for x in a))
            mag_b = math.sqrt(sum(x * x for x in b))
            if mag_a == 0 or mag_b == 0:
                return 0.0
            return dot / (mag_a * mag_b)

        scored = [
            (cosine_sim(query_emb, emb), chunk)
            for emb, chunk in zip(self._embeddings, self._chunks)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:n]

        if not top or top[0][0] < 0.3:
            return ""  # Nothing relevant enough

        results = []
        seen_sources = set()
        for score, chunk in top:
            source = os.path.basename(chunk["source"])
            results.append(f"[From {source}]: {chunk['text']}")
            seen_sources.add(source)

        return "\n\n".join(results)

    def _keyword_search(self, query: str, n: int) -> str:
        """Simple keyword fallback when embeddings fail."""
        keywords = query.lower().split()
        scored   = []
        for chunk in self._chunks:
            text_lower = chunk["text"].lower()
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [f"[From {os.path.basename(c['source'])}]: {c['text']}"
                   for _, c in scored[:n]]
        return "\n\n".join(results)

    # ── Stats ─────────────────────────────────────────────

    @property
    def document_count(self) -> int:
        return len(self._index.get("documents", {}))

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)


# ── Singleton ─────────────────────────────────────────────
# Loaded once at startup and shared across all modules.
_kb_instance: Optional[KnowledgeBase] = None

def get_knowledge_base() -> KnowledgeBase:
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    return _kb_instance
