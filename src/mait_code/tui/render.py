"""Rich-text render helpers for domain chips in the TUIs.

Rich-only (no Textual import), so this is cheap and &mdash; crucially &mdash; usable
inside ``DataTable`` cells and ``OptionList`` options, which render Rich ``Text``
and cannot read CSS ``$``-variables. Colours come from
:mod:`mait_code.tui.palette`: this is the one
sanctioned place palette hexes flow into Rich text, and because it reads the same
palette as the Textual theme, the chips stay in step with the active identity.
"""

from __future__ import annotations

from rich.text import Text

from mait_code.tui import palette as p

__all__ = ["priority_chip", "tag_badge"]

#: Priority → colour, a heat scale: high screams, medium warns, low recedes.
_PRIORITY_COLOUR = {
    "high": p.ERROR,
    "medium": p.WARNING,
    "low": p.SECONDARY,
}


def priority_chip(priority: str) -> Text:
    """A one-word priority chip, coloured by level (unknown → secondary)."""
    return Text(priority, style=_PRIORITY_COLOUR.get(priority, p.SECONDARY))


def tag_badge(tag: str, *, blocked: bool = False) -> Text:
    """A ``#tag`` badge; the blocked tag stands out bold in the error colour."""
    style = f"bold {p.ERROR}" if blocked else p.PRIMARY
    return Text(f"#{tag}", style=style)
