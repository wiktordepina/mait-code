"""Vector embeddings for semantic search.

Supports two providers:

* ``local``: fastembed with HuggingFace models (default, for personal use).
* ``bedrock``: AWS Bedrock Titan/Cohere models (for corporate environments).

The provider is configured via the ``MAIT_CODE_EMBEDDING_PROVIDER``
environment variable. Degrades gracefully if the provider fails to load —
callers always receive ``None`` instead of exceptions.
"""

import json
import logging
import sqlite3
import struct
from abc import ABC, abstractmethod

from mait_code.config import (
    DEFAULT_BEDROCK_MODEL_ID,
    DEFAULT_BEDROCK_REGION,
    DEFAULT_EMBEDDING_MODEL,
    get as config_get,
)
from mait_code.tools.memory.db import get_data_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------


class EmbeddingProvider(ABC):
    """Internal interface for embedding providers."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts and return one float vector per input."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension for this provider/model."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the human-readable model identifier."""
        ...


class LocalProvider(EmbeddingProvider):
    """fastembed/HuggingFace local embeddings."""

    KNOWN_MODELS = {
        "nomic-ai/nomic-embed-text-v1.5": 768,
    }
    DEFAULT_MODEL = DEFAULT_EMBEDDING_MODEL

    def __init__(self):
        from fastembed import TextEmbedding

        model = config_get("embedding-model")
        self._model_name = model
        self._dim = self.KNOWN_MODELS.get(model, 768)
        cache_dir = str(get_data_dir() / "models")
        self._embedder = TextEmbedding(model_name=model, cache_dir=cache_dir)

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        results = list(self._embedder.embed(texts))
        return [r.tolist() for r in results]


class BedrockProvider(EmbeddingProvider):
    """AWS Bedrock embedding provider."""

    KNOWN_MODELS = {
        "amazon.titan-embed-text-v2:0": 1024,
        "amazon.titan-embed-text-v1": 1536,
        "cohere.embed-english-v3": 1024,
        "cohere.embed-multilingual-v3": 1024,
    }
    DEFAULT_MODEL = DEFAULT_BEDROCK_MODEL_ID
    DEFAULT_REGION = DEFAULT_BEDROCK_REGION

    def __init__(self):
        from mait_code.ssl import setup_ssl

        setup_ssl()

        import boto3

        model_id = config_get("bedrock-model-id")
        region = config_get("bedrock-region")
        self._model_id = model_id
        self._dim = self.KNOWN_MODELS.get(model_id, 1024)
        self._is_titan = "titan" in model_id.lower()
        self._client = boto3.client("bedrock-runtime", region_name=region)

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_id

    def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            if self._is_titan:
                body = json.dumps({"inputText": text, "dimensions": self._dim})
            else:
                body = json.dumps({"texts": [text], "input_type": "search_document"})

            response = self._client.invoke_model(modelId=self._model_id, body=body)
            result = json.loads(response["body"].read())

            if self._is_titan:
                results.append(result["embedding"])
            else:
                results.append(result["embeddings"][0])

        return results


# ---------------------------------------------------------------------------
# Configuration helpers (no provider instantiation needed)
# ---------------------------------------------------------------------------


def _get_provider_name() -> str:
    """Return the configured provider name (env → settings file → default)."""
    return config_get("embedding-provider").lower()


def _get_embedding_dim() -> int:
    """Return the expected embedding dimension derived from configuration."""
    provider_name = _get_provider_name()
    if provider_name == "bedrock":
        model_id = config_get("bedrock-model-id")
        return BedrockProvider.KNOWN_MODELS.get(model_id, 1024)
    model = config_get("embedding-model")
    return LocalProvider.KNOWN_MODELS.get(model, 768)


def _get_embedding_model() -> str:
    """Return the configured embedding model name."""
    provider_name = _get_provider_name()
    if provider_name == "bedrock":
        return config_get("bedrock-model-id")
    return config_get("embedding-model")


# Module-level "constants" — computed from env vars at import time.
EMBEDDING_DIM: int = _get_embedding_dim()
EMBEDDING_MODEL: str = _get_embedding_model()


# ---------------------------------------------------------------------------
# Provider singleton
# ---------------------------------------------------------------------------

_provider: EmbeddingProvider | None = None
_provider_failed: bool = False


def get_provider() -> EmbeddingProvider | None:
    """Return the lazily-initialised embedding provider, or ``None``.

    On first call, instantiates the provider configured by
    ``MAIT_CODE_EMBEDDING_PROVIDER``. If instantiation fails, returns
    ``None`` on this and all subsequent calls.

    Returns:
        The provider instance, or ``None`` if initialisation failed.
    """
    global _provider, _provider_failed

    if _provider is not None:
        return _provider
    if _provider_failed:
        return None

    provider_name = _get_provider_name()

    try:
        if provider_name == "bedrock":
            _provider = BedrockProvider()
        else:
            _provider = LocalProvider()
        return _provider
    except ImportError as e:
        _provider_failed = True
        dep = "boto3" if provider_name == "bedrock" else "fastembed"
        logger.warning(
            "Embedding provider '%s' unavailable (missing %s): %s",
            provider_name,
            dep,
            e,
        )
        return None
    except Exception as e:
        _provider_failed = True
        logger.warning("Failed to load embedding provider '%s': %s", provider_name, e)
        return None


def _needs_prefix() -> bool:
    """Return whether the current provider uses text prefixes.

    nomic-style models require ``search_document:`` / ``search_query:``
    prefixes; Bedrock providers do not.
    """
    return _get_provider_name() != "bedrock"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_text(text: str, *, prefix: str = "search_document") -> list[float] | None:
    """Embed a single text string.

    Args:
        text: The text to embed.
        prefix: Task prefix for nomic-embed. Use ``"search_document"`` when
            storing/indexing, ``"search_query"`` when searching. Ignored for
            Bedrock providers.

    Returns:
        The embedding vector, or ``None`` if embeddings are unavailable.
    """
    provider = get_provider()
    if provider is None:
        return None

    try:
        input_text = f"{prefix}: {text}" if _needs_prefix() else text
        results = provider.embed([input_text])
        return results[0]
    except Exception as e:
        logger.warning("Embedding failed: %s", e)
        return None


def embed_texts(
    texts: list[str], *, prefix: str = "search_document"
) -> list[list[float]] | None:
    """Embed a batch of texts.

    Args:
        texts: The texts to embed.
        prefix: Task prefix for nomic-embed. Ignored for Bedrock providers.

    Returns:
        The list of embedding vectors, or ``None`` if unavailable.
    """
    provider = get_provider()
    if provider is None:
        return None

    try:
        if _needs_prefix():
            input_texts = [f"{prefix}: {t}" for t in texts]
        else:
            input_texts = texts
        return provider.embed(input_texts)
    except Exception as e:
        logger.warning("Batch embedding failed: %s", e)
        return None


def serialize_f32(vec: list[float]) -> bytes:
    """Serialise a float vector to raw bytes for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


def is_available() -> bool:
    """Return ``True`` if the embedding provider can be loaded."""
    return get_provider() is not None


def _parse_vec_table_dim(conn) -> int | None:
    """Return the declared dimension from the ``memory_vec`` CREATE statement."""
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='memory_vec'"
        ).fetchone()
        if row and row[0]:
            import re

            m = re.search(r"float\[(\d+)\]", row[0])
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


def check_dimension_match(conn: sqlite3.Connection) -> tuple[bool, int | None, int]:
    """Check whether the vec table dimension matches the configured provider.

    Args:
        conn: Open memory database connection.

    Returns:
        A tuple ``(matches, table_dim, expected_dim)``. ``table_dim`` is
        ``None`` if the vec table doesn't exist.
    """
    expected = _get_embedding_dim()
    try:
        row = conn.execute("SELECT embedding FROM memory_vec LIMIT 1").fetchone()
        if row is None:
            # Table exists but is empty — check the declared dimension
            table_dim = _parse_vec_table_dim(conn)
            if table_dim is None:
                return True, None, expected
            return table_dim == expected, table_dim, expected
        table_dim = len(row[0]) // 4  # 4 bytes per float32
        return table_dim == expected, table_dim, expected
    except Exception:
        return True, None, expected
