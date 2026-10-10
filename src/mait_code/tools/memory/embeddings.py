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
import math
import sqlite3
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

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


# ---------------------------------------------------------------------------
# Embedding record — which provider/model built ``memory_vec``
# ---------------------------------------------------------------------------

#: ``memory_meta`` keys holding the embedding record.
_RECORD_KEYS = ("embedding-provider", "embedding-model", "embedding-dim")

#: Cosine similarity a re-embedded sample must reach to count as the same model.
ADOPT_THRESHOLD = 0.99

#: How many stored vectors :func:`verify_and_adopt` re-embeds.
ADOPT_SAMPLE = 5


@dataclass(frozen=True)
class EmbeddingRecord:
    """The provider, model and width an embedding was (or would be) made with."""

    provider: str
    model: str
    dim: int

    def __str__(self) -> str:
        return f"{self.provider} '{self.model}' ({self.dim}d)"


VectorState = Literal["absent", "empty", "unknown", "match", "dimension", "model"]


@dataclass(frozen=True)
class VectorStatus:
    """Whether ``memory_vec`` can be queried and written with the configured model.

    Attributes:
        usable: ``True`` when vector search, dedup and writes may proceed.
        state: ``"match"`` (record agrees with configuration), ``"unknown"``
            (vectors but no record — permissive, as before the record
            existed), ``"empty"`` (no vectors yet), ``"absent"`` (no
            ``memory_vec`` table), ``"dimension"`` (stored or declared width
            differs) or ``"model"`` (recorded provider/model differs).
        reason: A one-line human explanation.
        configured: What the current settings would embed with.
        recorded: The stored record, or ``None`` if there is none.
    """

    usable: bool
    state: VectorState
    reason: str
    configured: EmbeddingRecord
    recorded: EmbeddingRecord | None


def configured_record() -> EmbeddingRecord:
    """Return the provider/model/width the current settings embed with.

    Read live from configuration — never the import-time constants, and
    never by instantiating the provider (which can load a local model).
    """
    return EmbeddingRecord(
        _get_provider_name(), _get_embedding_model(), _get_embedding_dim()
    )


def read_embedding_record(conn: sqlite3.Connection) -> EmbeddingRecord | None:
    """Return the record of what built ``memory_vec``, or ``None`` if unknown.

    A database that predates ``memory_meta``, or one whose vectors were never
    built under a recording release, has no record.
    """
    try:
        rows = dict(
            conn.execute(
                "SELECT key, value FROM memory_meta WHERE key IN (?, ?, ?)",
                _RECORD_KEYS,
            ).fetchall()
        )
    except sqlite3.Error:
        return None
    try:
        return EmbeddingRecord(
            rows["embedding-provider"],
            rows["embedding-model"],
            int(rows["embedding-dim"]),
        )
    except (KeyError, ValueError):
        return None


def write_embedding_record(
    conn: sqlite3.Connection, record: EmbeddingRecord | None = None
) -> None:
    """Record what built ``memory_vec`` — the configured model by default.

    Does not commit: callers write the record in the same transaction that
    empties the table or inserts its first vector, so the record and the
    vectors never disagree.
    """
    record = record or configured_record()
    conn.executemany(
        "INSERT OR REPLACE INTO memory_meta(key, value) VALUES (?, ?)",
        zip(_RECORD_KEYS, (record.provider, record.model, str(record.dim))),
    )


def vectors_usable(conn: sqlite3.Connection) -> VectorStatus:
    """Check that ``memory_vec`` was built by the configured provider and model.

    Vectors from different models live in different spaces, so comparing a
    query embedded by one against vectors stored by another yields
    meaningless similarities — even at the same width. Search, dedup and
    writes therefore consult this before embedding anything.

    An empty table is usable whatever the record says (nothing to disagree
    with), unless its declared width differs. Vectors with no record are
    usable too, keeping pre-record databases working; ``doctor`` nudges
    those toward :func:`verify_and_adopt`.

    Args:
        conn: Open memory database connection (read-only is fine).

    Returns:
        The :class:`VectorStatus`.
    """
    configured = configured_record()
    recorded = read_embedding_record(conn)

    def status(usable: bool, state: VectorState, reason: str) -> VectorStatus:
        return VectorStatus(usable, state, reason, configured, recorded)

    try:
        row = conn.execute("SELECT embedding FROM memory_vec LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        return status(False, "absent", f"memory_vec is not queryable ({exc})")

    if row is None:
        declared = _parse_vec_table_dim(conn)
        if declared is not None and declared != configured.dim:
            return status(
                False,
                "dimension",
                f"memory_vec is declared {declared}d, "
                f"{configured} embeds {configured.dim}d",
            )
        return status(True, "empty", "no vectors stored yet")

    stored_dim = len(row[0]) // 4  # 4 bytes per float32
    if stored_dim != configured.dim:
        built_by = recorded or f"a {stored_dim}d model"
        return status(
            False,
            "dimension",
            f"vectors were built by {built_by}, configured is {configured}",
        )
    if recorded is None:
        return status(True, "unknown", "no record of which model built the vectors")
    if (recorded.provider, recorded.model) != (configured.provider, configured.model):
        return status(
            False,
            "model",
            f"vectors were built by {recorded}, configured is {configured}",
        )
    return status(True, "match", f"vectors built by {recorded}")


_warned: set[str] = set()


def warn_unusable_once(status: VectorStatus, consequence: str) -> None:
    """Log *status* at warning level, once per process per reason.

    A long-lived host would otherwise log the same mismatch on every query.
    """
    key = f"{status.reason}|{consequence}"
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(
        "Vectors unusable: %s — %s; run 'mc-tool-memory reindex'",
        status.reason,
        consequence,
    )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _sample_vectors(conn: sqlite3.Connection, n: int) -> list[tuple[str, bytes]]:
    """Return ``(content, stored vector)`` for *n* vectors spread across ids.

    Both ends are always included: a model switched mid-life leaves the
    oldest vectors from one model and the newest from the other, so a spread
    sample catches the mix that a random one could miss.
    """
    ids = [r[0] for r in conn.execute("SELECT rowid FROM memory_vec ORDER BY rowid")]
    if not ids:
        return []
    if len(ids) > n:
        step = (len(ids) - 1) / (n - 1)
        ids = sorted({ids[round(i * step)] for i in range(n)})
    rows = []
    for entry_id in ids:
        row = conn.execute(
            """SELECT m.content, v.embedding
               FROM memory_vec v JOIN memory_entries m ON m.id = v.rowid
               WHERE v.rowid = ?""",
            (entry_id,),
        ).fetchone()
        if row:
            rows.append((row[0], row[1]))
    return rows


AdoptOutcome = Literal["adopted", "differs", "unavailable"]


def verify_and_adopt(
    conn: sqlite3.Connection,
    *,
    sample: int = ADOPT_SAMPLE,
    threshold: float = ADOPT_THRESHOLD,
) -> AdoptOutcome:
    """Record the configured model if it demonstrably built the stored vectors.

    Re-embeds a spread sample of stored entries and compares each against
    its stored vector. The same model reproduces its vectors (cosine ~1.0);
    a different one embeds into an unrelated space and lands nowhere near.
    This settles an unknown record without re-embedding everything.

    Commits the record on success; writes nothing otherwise.

    Args:
        conn: Open, writable memory database connection.
        sample: How many stored vectors to re-embed.
        threshold: Minimum cosine similarity every sampled vector must reach.

    Returns:
        ``"adopted"`` if the record was written, ``"differs"`` if any sampled
        vector disagrees (or there is nothing to compare), ``"unavailable"``
        if the provider could not embed.
    """
    rows = _sample_vectors(conn, sample)
    if not rows:
        return "differs"
    vectors = embed_texts([content for content, _ in rows], prefix="search_document")
    if vectors is None:
        return "unavailable"
    for (_, blob), fresh in zip(rows, vectors):
        stored = list(struct.unpack(f"{len(blob) // 4}f", blob))
        if len(stored) != len(fresh) or _cosine(stored, fresh) < threshold:
            return "differs"
    write_embedding_record(conn)
    conn.commit()
    return "adopted"
