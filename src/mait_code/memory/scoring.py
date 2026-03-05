"""
Composite scoring for memory entries.

Combines recency, importance, and relevance into a single score
for ranking memory retrieval results.

    score = W_recency * recency + W_importance * importance + W_relevance * relevance

Where:
    recency:    exponential decay, half-life depends on memory_class
                  - episodic (events, tasks): 3-day half-life (fast decay)
                  - semantic (facts, preferences, insights): 90-day half-life (slow decay)
                  - fallback: 7-day half-life
    importance: normalized to 0.0-1.0 from the 1-10 scale
    relevance:  0.0-1.0, from FTS5 BM25 or semantic similarity (caller provides)
"""

import math
from datetime import UTC, datetime

# Default weights
W_RECENCY = 0.3
W_IMPORTANCE = 0.3
W_RELEVANCE = 0.4

# Per-class decay half-lives (days)
HALF_LIFE_DAYS: dict[str, float] = {
    "episodic": 3.0,  # Events/tasks: ~50% at 3 days, ~6% at 12 days
    "semantic": 90.0,  # Facts/preferences/insights: ~50% at 90 days
}
DEFAULT_HALF_LIFE = 7.0  # Fallback when memory_class is unknown


def recency_score(
    created_at: str | datetime,
    now: datetime | None = None,
    *,
    memory_class: str | None = None,
) -> float:
    """
    Compute recency score using exponential decay.

    Half-life depends on memory_class:
    - episodic: 3 days (events decay fast)
    - semantic: 90 days (facts persist)
    - None/unknown: 7 days (fallback)
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

    half_life = HALF_LIFE_DAYS.get(memory_class, DEFAULT_HALF_LIFE)
    age_days = max(0, (now - created_at).total_seconds() / 86400)
    return math.exp(-math.log(2) * age_days / half_life)


def importance_score(importance: int) -> float:
    """Normalize importance (1-10) to 0.0-1.0."""
    return max(0.0, min(1.0, (importance - 1) / 9.0))


def composite_score(
    created_at: str | datetime,
    importance: int,
    relevance: float = 0.5,
    *,
    memory_class: str | None = None,
    w_recency: float = W_RECENCY,
    w_importance: float = W_IMPORTANCE,
    w_relevance: float = W_RELEVANCE,
    now: datetime | None = None,
) -> float:
    """
    Compute composite score for a memory entry.

    Args:
        created_at: When the entry was created (ISO string or datetime).
        importance: Importance level 1-10.
        relevance: Relevance score 0.0-1.0 (from search or default 0.5).
        memory_class: 'episodic' or 'semantic' (controls decay rate).
        w_recency: Weight for recency component.
        w_importance: Weight for importance component.
        w_relevance: Weight for relevance component.
        now: Override current time (for testing).

    Returns:
        Composite score between 0.0 and 1.0.
    """
    r = recency_score(created_at, now, memory_class=memory_class)
    i = importance_score(importance)
    return w_recency * r + w_importance * i + w_relevance * relevance
