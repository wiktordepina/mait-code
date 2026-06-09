"""Tests for the pure-data brand helpers (wordmark tiers, glyph, empty state)."""

from __future__ import annotations

from mait_code.tui.brand import (
    GLYPH,
    WORDMARK,
    WORDMARK_COMPACT,
    WORDMARK_COMPACT_WIDTH,
    WORDMARK_PLAIN,
    WORDMARK_WIDTH,
    empty_state,
    wordmark,
)


def test_wordmark_full_when_wide() -> None:
    assert wordmark(WORDMARK_WIDTH) == WORDMARK


def test_wordmark_falls_back_to_plain_when_narrow() -> None:
    assert wordmark(WORDMARK_WIDTH - 1) == WORDMARK_PLAIN


def test_wordmark_compact_when_wide_enough() -> None:
    assert wordmark(WORDMARK_COMPACT_WIDTH, compact=True) == WORDMARK_COMPACT


def test_wordmark_compact_falls_back_to_plain_when_narrow() -> None:
    assert wordmark(WORDMARK_COMPACT_WIDTH - 1, compact=True) == WORDMARK_PLAIN


def test_compact_wordmark_is_three_rows_and_shorter_than_full() -> None:
    compact_rows = WORDMARK_COMPACT.split("\n")
    assert len(compact_rows) == 3
    assert len(WORDMARK.split("\n")) == 6  # the compact is half height
    # All rows share one width so the Static lays out as a clean rectangle.
    assert len({len(row) for row in compact_rows}) == 1
    assert len(compact_rows[0]) == WORDMARK_COMPACT_WIDTH


def test_compact_threshold_is_narrower_than_full() -> None:
    # The whole point: the compact art fits where the full art would wrap.
    assert WORDMARK_COMPACT_WIDTH < WORDMARK_WIDTH


def test_empty_state_leads_with_glyph() -> None:
    assert empty_state("nothing here") == f"{GLYPH} nothing here"
