"""
config.py — Centralized Configuration

WHY: Single source of truth for all tunables. Every module imports from here
instead of hardcoding values. Changing a model, chunk size, or directory
path requires editing only this file.
"""

import os
from dotenv import load_dotenv

# ── Load environment variables from .env ──────────────────────────────────────
load_dotenv()

# ── LLM Configuration ────────────────────────────────────────────────────────
# Groq provides free, fast inference for open-source models.
# llama-3.3-70b-versatile offers strong reasoning at zero cost.
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
MODEL_NAME: str = "llama-3.3-70b-versatile"
TEMPERATURE: float = 0.3  # Low temperature for factual academic answers

# ── Embedding Configuration ──────────────────────────────────────────────────
# all-MiniLM-L6-v2 runs locally on CPU — no API key, no cost.
# 384-dimensional vectors, good balance of speed and quality.
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

# ── Chunking Configuration ───────────────────────────────────────────────────
# 1000 chars ≈ 200-250 words. Enough context per chunk for academic content.
# 200-char overlap preserves continuity across chunk boundaries.
CHUNK_SIZE: int = 1000
CHUNK_OVERLAP: int = 200

# ── Vector Store Configuration ───────────────────────────────────────────────
# FAISS index files persist here between app restarts.
FAISS_INDEX_DIR: str = "faiss_index"

# ── Retrieval Configuration ──────────────────────────────────────────────────
# Number of most-relevant chunks returned per query.
# 4 is optimal: enough context without overwhelming the LLM's window.
TOP_K: int = 4

# ── File Upload Configuration ────────────────────────────────────────────────
UPLOAD_DIR: str = "uploaded_docs"
ALLOWED_EXTENSIONS: list[str] = [".pdf", ".docx"]
