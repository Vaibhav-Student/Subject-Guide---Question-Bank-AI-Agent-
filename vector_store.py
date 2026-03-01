"""
vector_store.py — FAISS Vector Store Manager

WHY THIS MODULE EXISTS:
    The retrieval step in RAG depends on finding the most semantically
    similar chunks to the user's question. This module:
    1. Converts text chunks into vector embeddings
    2. Stores them in a FAISS index for fast similarity search
    3. Persists the index to disk so data survives app restarts
    4. Supports incremental updates (add new docs without rebuilding)

WHY FAISS:
    - Blazing fast similarity search (Facebook AI Research)
    - Works entirely on CPU — no GPU required
    - Simple persistence (save/load to files)
    - Scales to millions of vectors
    - No external database server needed

WHY HuggingFace Embeddings (all-MiniLM-L6-v2):
    - Runs 100% locally — no API key, no cost, no rate limits
    - 384-dimensional vectors — compact and fast
    - Strong performance on semantic similarity benchmarks
    - Perfect for academic text domains
"""

import os
import logging
from pathlib import Path

from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

from config import EMBEDDING_MODEL, FAISS_INDEX_DIR, TOP_K

logger = logging.getLogger(__name__)

# ── Embedding Model Singleton ────────────────────────────────────────────────
# WHY singleton: The model loads ~80MB into memory. Loading it once and
# reusing avoids redundant memory allocation and startup latency.

_embeddings: HuggingFaceEmbeddings | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    """
    Lazily initialize and return the embedding model.

    WHY lazy init: Only loads the model when first needed,
    not at import time. Keeps startup fast.
    """
    global _embeddings
    if _embeddings is None:
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        logger.info("Embedding model loaded successfully")
    return _embeddings


# ── Vector Store Operations ──────────────────────────────────────────────────


def create_or_update_vector_store(
    documents: list[Document],
) -> FAISS:
    """
    Create a new FAISS index from documents, or merge into an existing one.

    WHY merge instead of rebuild:
        Rebuilding from scratch every time is wasteful for large corpora.
        FAISS's merge_from() lets us add new documents incrementally,
        preserving all previously indexed content.

    Flow:
        1. Generate embeddings for new documents
        2. If existing index on disk → load it and merge new vectors in
        3. If no existing index → create fresh
        4. Save updated index to disk

    Args:
        documents: List of LangChain Document objects to index.

    Returns:
        The updated FAISS vector store instance.
    """
    embeddings = _get_embeddings()

    # Build a new FAISS index from the incoming documents
    new_store = FAISS.from_documents(documents, embeddings)
    logger.info("Created FAISS index with %d new document chunks", len(documents))

    # Check if a persisted index already exists
    index_path = Path(FAISS_INDEX_DIR)
    if index_path.exists() and (index_path / "index.faiss").exists():
        logger.info("Found existing FAISS index — merging new documents")
        existing_store = FAISS.load_local(
            FAISS_INDEX_DIR,
            embeddings,
            allow_dangerous_deserialization=True,
        )
        existing_store.merge_from(new_store)
        existing_store.save_local(FAISS_INDEX_DIR)
        logger.info("Merged and saved updated index to '%s'", FAISS_INDEX_DIR)
        return existing_store

    # No existing index — save the new one
    new_store.save_local(FAISS_INDEX_DIR)
    logger.info("Saved new FAISS index to '%s'", FAISS_INDEX_DIR)
    return new_store


def load_vector_store() -> FAISS | None:
    """
    Load a previously persisted FAISS index from disk.

    WHY separate from create: Keeps read and write operations distinct.
    On app startup, we try to load; only create when new docs arrive.

    Returns:
        FAISS vector store if index exists, None otherwise.
    """
    index_path = Path(FAISS_INDEX_DIR)
    if not index_path.exists() or not (index_path / "index.faiss").exists():
        logger.info("No existing FAISS index found at '%s'", FAISS_INDEX_DIR)
        return None

    embeddings = _get_embeddings()
    store = FAISS.load_local(
        FAISS_INDEX_DIR,
        embeddings,
        allow_dangerous_deserialization=True,
    )
    logger.info("Loaded existing FAISS index from '%s'", FAISS_INDEX_DIR)
    return store


def get_retriever(vector_store: FAISS):
    """
    Create a retriever from the vector store.

    WHY a retriever wrapper: LangChain's RetrievalQA chain expects a
    retriever interface. This bridges FAISS → LangChain's chain API.

    Args:
        vector_store: An initialized FAISS vector store.

    Returns:
        A LangChain retriever configured with top_k search.
    """
    return vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": TOP_K},
    )


def delete_vector_store() -> bool:
    """
    Delete the persisted FAISS index from disk.

    WHY: Allows users to reset the knowledge base and start fresh.

    Returns:
        True if index was deleted, False if it didn't exist.
    """
    index_path = Path(FAISS_INDEX_DIR)
    if index_path.exists():
        import shutil

        shutil.rmtree(index_path)
        logger.info("Deleted FAISS index at '%s'", FAISS_INDEX_DIR)
        return True
    return False
