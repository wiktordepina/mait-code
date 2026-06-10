"""Tests for the pure-data brand helpers (wordmark tiers, painter, glyph)."""

from __future__ import annotations

from rich.text import Text

from mait_code.tui import palette
from mait_code.tui.brand import (
    GLYPH,
    WORDMARK,
    WORDMARK_COMPACT,
    WORDMARK_COMPACT_WIDTH,
    WORDMARK_PLAIN,
    WORDMARK_WIDTH,
    empty_state,
    wordmark,
    wordmark_text,
)


def style_at(painted: Text, index: int) -> str:
    """The span style covering character *index* ('' if unstyled)."""
    for span in painted.spans:
        if span.start <= index < span.end:
            return str(span.style)
    return ""


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


# -- wordmark_text (the horizon + depth painter) -------------------------------


def test_wordmark_text_preserves_the_art() -> None:
    assert wordmark_text(WORDMARK_WIDTH).plain == WORDMARK
    assert wordmark_text(WORDMARK_COMPACT_WIDTH, compact=True).plain == WORDMARK_COMPACT


def test_wordmark_text_gradient_spans_primary_to_accent() -> None:
    painted = wordmark_text(WORDMARK_WIDTH)
    # Column 0 is a fill glyph at the gradient's start: exactly primary.
    assert style_at(painted, 0) == palette.PRIMARY
    # The last column of row 0 is a shadow glyph at the gradient's end:
    # accent blended toward the background — violet-ish, but darker than
    # both the accent and the column-0 primary.
    last = len(WORDMARK.split("\n")[0]) - 1
    end_style = style_at(painted, last)
    assert end_style not in (palette.PRIMARY, palette.ACCENT)
    assert int(end_style[1:3], 16) < int(palette.ACCENT[1:3], 16)


def test_wordmark_text_shadow_is_darker_than_fill() -> None:
    painted = wordmark_text(WORDMARK_WIDTH)
    # Row 0 opens "███╗" — fill at column 2, shadow at column 3, adjacent
    # columns so the gradient barely moves; the dimming must dominate.
    fill, shadow = style_at(painted, 2), style_at(painted, 3)
    assert sum(int(shadow[i : i + 2], 16) for i in (1, 3, 5)) < sum(
        int(fill[i : i + 2], 16) for i in (1, 3, 5)
    )


def test_wordmark_text_spaces_are_unstyled() -> None:
    painted = wordmark_text(WORDMARK_WIDTH)
    assert style_at(painted, WORDMARK.index(" ")) == ""


def test_wordmark_text_plain_fallback_still_painted() -> None:
    painted = wordmark_text(WORDMARK_WIDTH - 1)
    assert painted.plain == WORDMARK_PLAIN
    assert style_at(painted, 0) == palette.PRIMARY
    assert style_at(painted, len(WORDMARK_PLAIN) - 1) == palette.ACCENT


def test_wordmark_text_non_hex_slots_fall_back_to_house_palette() -> None:
    # Ansi themes hand Rich-only names ("cyan") the blend maths can't touch.
    painted = wordmark_text(WORDMARK_WIDTH, primary="cyan", background="black")
    assert style_at(painted, 0) == palette.PRIMARY
