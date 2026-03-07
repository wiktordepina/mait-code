"""Tests for composite scoring system."""

from datetime import UTC, datetime, timedelta

from mait_code.tools.memory.scoring import (
    DEFAULT_HALF_LIFE,
    HALF_LIFE_DAYS,
    composite_score,
    importance_score,
    recency_score,
)


class TestRecencyScore:
    def test_just_created(self):
        """A just-created entry should score ~1.0."""
        now = datetime.now(UTC)
        score = recency_score(now, now)
        assert score > 0.99

    def test_episodic_half_life(self):
        """At the half-life, score should be ~0.5."""
        now = datetime.now(UTC)
        created = now - timedelta(days=HALF_LIFE_DAYS["episodic"])
        score = recency_score(created, now, memory_class="episodic")
        assert abs(score - 0.5) < 0.01

    def test_semantic_half_life(self):
        """Semantic memories decay much slower."""
        now = datetime.now(UTC)
        created = now - timedelta(days=HALF_LIFE_DAYS["semantic"])
        score = recency_score(created, now, memory_class="semantic")
        assert abs(score - 0.5) < 0.01

    def test_default_half_life(self):
        """Unknown memory_class uses default half-life."""
        now = datetime.now(UTC)
        created = now - timedelta(days=DEFAULT_HALF_LIFE)
        score = recency_score(created, now, memory_class=None)
        assert abs(score - 0.5) < 0.01

    def test_old_episodic_very_low(self):
        """A 30-day-old episodic entry should score near zero."""
        now = datetime.now(UTC)
        created = now - timedelta(days=30)
        score = recency_score(created, now, memory_class="episodic")
        assert score < 0.001

    def test_string_timestamp(self):
        """Should accept ISO string timestamps."""
        now = datetime.now(UTC)
        created_str = now.isoformat()
        score = recency_score(created_str, now)
        assert score > 0.99

    def test_invalid_string_returns_zero(self):
        """Invalid timestamp strings should return 0."""
        assert recency_score("not-a-date") == 0.0

    def test_naive_datetime_handled(self):
        """Naive datetimes (no tzinfo) should still work."""
        now = datetime.now(UTC)
        created = datetime.now()  # naive
        score = recency_score(created, now)
        assert 0.0 <= score <= 1.0


class TestImportanceScore:
    def test_minimum(self):
        assert importance_score(1) == 0.0

    def test_maximum(self):
        assert importance_score(10) == 1.0

    def test_midpoint(self):
        score = importance_score(5)
        assert abs(score - 4.0 / 9.0) < 0.001

    def test_below_minimum_clamped(self):
        assert importance_score(0) == 0.0

    def test_above_maximum_clamped(self):
        assert importance_score(15) == 1.0


class TestCompositeScore:
    def test_weights_sum(self):
        """Default weights should sum to 1.0."""
        from mait_code.tools.memory.scoring import W_IMPORTANCE, W_RECENCY, W_RELEVANCE

        assert abs(W_RECENCY + W_IMPORTANCE + W_RELEVANCE - 1.0) < 0.001

    def test_perfect_entry(self):
        """Brand new, max importance, max relevance should score ~1.0."""
        now = datetime.now(UTC)
        score = composite_score(now, importance=10, relevance=1.0, now=now)
        assert score > 0.95

    def test_default_relevance(self):
        """Default relevance is 0.5."""
        now = datetime.now(UTC)
        score = composite_score(now, importance=5, now=now)
        assert 0.0 < score < 1.0

    def test_custom_weights(self):
        """Custom weights should be respected."""
        now = datetime.now(UTC)
        created = now - timedelta(days=30)

        # All weight on importance
        score = composite_score(
            created,
            importance=10,
            relevance=0.0,
            w_recency=0.0,
            w_importance=1.0,
            w_relevance=0.0,
            now=now,
        )
        assert abs(score - 1.0) < 0.01

    def test_score_in_range(self):
        """Score should always be between 0 and 1."""
        now = datetime.now(UTC)
        for days_ago in [0, 1, 7, 30, 365]:
            for imp in [1, 5, 10]:
                created = now - timedelta(days=days_ago)
                score = composite_score(created, imp, now=now)
                assert 0.0 <= score <= 1.0
