"""Tests for the Rich-text chip helpers."""

from __future__ import annotations

from mait_code.tui import palette as p
from mait_code.tui.render import priority_chip, tag_badge


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
