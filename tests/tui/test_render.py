"""Tests for the Rich-text chip helpers."""

from __future__ import annotations

from mait_code.tui import palette as p
from mait_code.tui.render import ChipColours, PALETTE_CHIPS, priority_chip, tag_badge


def test_priority_chip_colours_by_level() -> None:
    assert priority_chip("high").plain == "high"
    assert str(priority_chip("high").style) == p.ERROR
    assert str(priority_chip("medium").style) == p.WARNING
    assert str(priority_chip("low").style) == p.SECONDARY


def test_priority_chip_unknown_falls_back() -> None:
    assert str(priority_chip("urgent").style) == p.SECONDARY


def test_tag_badge_marks_blocked() -> None:
    assert tag_badge("wip").plain == "#wip"
    assert str(tag_badge("wip").style) == p.PRIMARY
    blocked = tag_badge("blocked", blocked=True)
    assert "bold" in str(blocked.style)
    assert p.ERROR in str(blocked.style)


def test_default_bundle_matches_static_palette() -> None:
    """The default bundle is the canonical palette, so a bare call is unchanged."""
    assert PALETTE_CHIPS.high == p.ERROR
    assert PALETTE_CHIPS.medium == p.WARNING
    assert PALETTE_CHIPS.low == p.SECONDARY
    assert PALETTE_CHIPS.tag == p.PRIMARY
    assert PALETTE_CHIPS.blocked == p.ERROR


def test_custom_bundle_overrides_colours() -> None:
    """A passed bundle wins, so chips can track an active theme."""
    bubblegum = ChipColours(
        high="#FF5C7A",
        medium="#FFC857",
        low="#9D7CFF",
        tag="#9D7CFF",
        blocked="#FF5C7A",
    )
    assert str(priority_chip("high", bubblegum).style) == "#FF5C7A"
    assert str(priority_chip("low", bubblegum).style) == "#9D7CFF"
    assert str(tag_badge("ui", colours=bubblegum).style) == "#9D7CFF"
    blocked = tag_badge("blocked", blocked=True, colours=bubblegum)
    assert "#FF5C7A" in str(blocked.style)
    assert "bold" in str(blocked.style)
