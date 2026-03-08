"""
Vector embeddings for semantic search using fastembed.

Wraps nomic-embed-text-v1.5 behind a lazy-loading singleton.
Degrades gracefully if fastembed is not installed or the model
fails to load — callers always get None instead of exceptions.
"""

import logging
import struct

from mait_code.tools.memory.db import get_data_dir

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIM = 768

_embedder = None
_embedder_failed = False


def get_embedder():
    """
    Return a lazily-initialised TextEmbedding instance, or None.

    The model is downloaded on first use into the data directory.
    If fastembed is not installed or initialisation fails, returns
    None on this and all subsequent calls.
    """
    global _embedder, _embedder_failed

    if _embedder is not None:
        return _embedder
    if _embedder_failed:
        return None

    try:
        from fastembed import TextEmbedding

        cache_dir = str(get_data_dir() / "models")
        _embedder = TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=cache_dir)
        return _embedder
    except Exception as e:
        _embedder_failed = True
        logger.warning("Failed to load embedding model: %s", e)
        return None


def embed_text(text: str, *, prefix: str = "search_document") -> list[float] | None:
    """
    Embed a single text string.

    Args:
        text: The text to embed.
        prefix: Task prefix for nomic-embed. Use "search_document" when
                storing/indexing, "search_query" when searching.

    Returns:
        List of 768 floats, or None if embeddings are unavailable.
    """
    embedder = get_embedder()
    if embedder is None:
        return None

    try:
        prefixed = f"{prefix}: {text}"
        result = list(embedder.embed([prefixed]))
        return result[0].tolist()
    except Exception as e:
        logger.warning("Embedding failed: %s", e)
        return None


def embed_texts(
    texts: list[str], *, prefix: str = "search_document"
) -> list[list[float]] | None:
    """
    Embed a batch of texts.

    Args:
        texts: List of texts to embed.
        prefix: Task prefix for nomic-embed.

    Returns:
        List of embedding vectors, or None if unavailable.
    """
    embedder = get_embedder()
    if embedder is None:
        return None

    try:
        prefixed = [f"{prefix}: {t}" for t in texts]
        results = list(embedder.embed(prefixed))
        return [r.tolist() for r in results]
    except Exception as e:
        logger.warning("Batch embedding failed: %s", e)
        return None


def serialize_f32(vec: list[float]) -> bytes:
    """Serialize a float vector to raw bytes for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


def is_available() -> bool:
    """Check whether the embedding model can be loaded."""
    return get_embedder() is not None
