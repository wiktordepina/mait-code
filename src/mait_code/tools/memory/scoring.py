"""Composite scoring for memory entries.

Combines recency, importance, and relevance into a single score for ranking
memory retrieval results::

    score = W_recency * recency + W_importance * importance + W_relevance * relevance

Where:

* ``recency`` — exponential decay; half-life depends on ``memory_class``:

  - episodic (events, tasks): 3-day half-life (fast decay)
  - semantic (facts, preferences, insights): 90-day half-life (slow decay)
  - procedural (workflows, how-tos): 180-day half-life (slowest decay)
  - fallback: 7-day half-life

* ``importance`` — normalised to 0.0-1.0 from the 1-10 scale.
* ``relevance`` — 0.0-1.0, from FTS5 BM25 or semantic similarity (caller
  provides).
"""

import logging
import math
from datetime import UTC, datetime

from mait_code import config

logger = logging.getLogger(__name__)

# Default weights, used when the configured weights don't sum to 1.0.
_DEFAULT_WEIGHTS = (0.3, 0.3, 0.4)


def _load_weights() -> tuple[float, float, float]:
    """Resolve the three scoring weights, falling back if they don't sum to 1.0.

    Reading once at import time mirrors the previous module-level constants.
    ``doctor`` surfaces a bad sum loudly; here we degrade gracefully so a
    skewed settings file can't silently distort every retrieval.
    """
    weights = (
        config.get_float("score-weight-recency"),
        config.get_float("score-weight-importance"),
        config.get_float("score-weight-relevance"),
    )
    total = sum(weights)
    if abs(total - 1.0) > 1e-6:
        logger.warning(
            "scoring weights sum to %.3f, not 1.0; using defaults %s",
            total,
            _DEFAULT_WEIGHTS,
        )
        return _DEFAULT_WEIGHTS
    return weights


W_RECENCY, W_IMPORTANCE, W_RELEVANCE = _load_weights()

# Per-class decay half-lives (days)
HALF_LIFE_DAYS: dict[str, float] = {
    "episodic": config.get_float("half-life-episodic"),  # ~50% at 3 days
    "semantic": config.get_float("half-life-semantic"),  # ~50% at 90 days
    "procedural": config.get_float("half-life-procedural"),  # ~50% at 180 days
}
DEFAULT_HALF_LIFE = 7.0  # Fallback when memory_class is unknown

# Relevance multipliers by scope match (project match 0.85 / branch 1.0 fixed).
SCOPE_BOOST_GLOBAL = config.get_float("scope-boost-global")
SCOPE_BOOST_CROSS_PROJECT = config.get_float("scope-boost-cross-project")


def recency_score(
    created_at: str | datetime,
    now: datetime | None = None,
    *,
    memory_class: str | None = None,
) -> float:
    """Compute the recency score using exponential decay.

    Half-life depends on ``memory_class``:

    * ``episodic``: 3 days (events decay fast).
    * ``semantic``: 90 days (facts persist).
    * ``procedural``: 180 days (workflows go stale when superseded, not with time).
    * ``None``/unknown: 7 days (fallback).

    Args:
        created_at: When the entry was created (ISO string or datetime).
        now: Override current time (for testing); defaults to UTC now.
        memory_class: Memory class controlling the decay rate.

    Returns:
        A score in ``[0.0, 1.0]``; returns ``0.0`` if ``created_at`` cannot
        be parsed.
    """
    if now is None:
        now = datetime.now(UTC)

    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except ValueError:
            return 0.0

    # Ensure timezone-aware comparison
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    half_life = HALF_LIFE_DAYS.get(memory_class or "", DEFAULT_HALF_LIFE)
    age_days = max(0, (now - created_at).total_seconds() / 86400)
    return math.exp(-math.log(2) * age_days / half_life)


def importance_score(importance: int) -> float:
    """Normalise an importance value (1-10) to ``[0.0, 1.0]``."""
    return max(0.0, min(1.0, (importance - 1) / 9.0))


def scope_boost(
    entry_scope: str,
    entry_project: str | None,
    entry_branch: str | None,
    *,
    query_project: str | None = None,
    query_branch: str | None = None,
) -> float:
    """Compute a multiplicative boost based on scope match.

    Args:
        entry_scope: The entry's scope (``"global"``, ``"project"``,
            ``"branch"``).
        entry_project: The entry's project, or ``None``.
        entry_branch: The entry's branch, or ``None``.
        query_project: Project context for the query, or ``None``.
        query_branch: Branch context for the query, or ``None``.

    Returns:
        ``1.0`` for a branch match, ``0.85`` for a project match,
        ``SCOPE_BOOST_GLOBAL`` (default ``0.7``) for global entries,
        ``SCOPE_BOOST_CROSS_PROJECT`` (default ``0.3``) across projects, and
        ``1.0`` when no query context is provided (backward compat).
    """
    # No query context — no boost applied
    if query_project is None:
        return 1.0

    if entry_scope == "global" or entry_project is None:
        return SCOPE_BOOST_GLOBAL

    if entry_project != query_project:
        # Shouldn't happen given search filtering, but defensive
        return SCOPE_BOOST_CROSS_PROJECT

    if (
        entry_scope == "branch"
        and entry_branch is not None
        and query_branch is not None
        and entry_branch == query_branch
    ):
        return 1.0

    return 0.85  # Project match


def composite_score(
    created_at: str | datetime,
    importance: int,
    relevance: float = 0.5,
    *,
    memory_class: str | None = None,
    entry_scope: str | None = None,
    entry_project: str | None = None,
    entry_branch: str | None = None,
    query_project: str | None = None,
    query_branch: str | None = None,
    w_recency: float = W_RECENCY,
    w_importance: float = W_IMPORTANCE,
    w_relevance: float = W_RELEVANCE,
    now: datetime | None = None,
) -> float:
    """Compute the composite score for a memory entry.

    Args:
        created_at: When the entry was created (ISO string or datetime).
        importance: Importance level 1-10.
        relevance: Relevance score 0.0-1.0 (from search or default 0.5).
        memory_class: ``"episodic"``, ``"semantic"``, or ``"procedural"``
            (controls decay rate).
        entry_scope: Scope of the entry (``"global"``, ``"project"``,
            ``"branch"``).
        entry_project: Project of the entry.
        entry_branch: Branch of the entry.
        query_project: Project context for the query.
        query_branch: Branch context for the query.
        w_recency: Weight for the recency component.
        w_importance: Weight for the importance component.
        w_relevance: Weight for the relevance component.
        now: Override current time (for testing).

    Returns:
        Composite score, roughly in ``[0.0, 1.0]``.
    """
    r = recency_score(created_at, now, memory_class=memory_class)
    i = importance_score(importance)
    base = w_recency * r + w_importance * i + w_relevance * relevance

    if entry_scope is not None:
        boost = scope_boost(
            entry_scope,
            entry_project,
            entry_branch,
            query_project=query_project,
            query_branch=query_branch,
        )
        return base * boost

    return base
