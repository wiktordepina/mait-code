"""Rich-text render helpers for domain chips in the TUIs.

Rich-only (no Textual import), so this is cheap and &mdash; crucially &mdash; usable
inside ``DataTable`` cells and ``OptionList`` options, which render Rich ``Text``
and cannot read CSS ``$``-variables. Because those cells can't read the theme,
the colours have to be supplied as plain hexes at render time.

Every helper takes an optional :class:`ChipColours` bundle. It defaults to
:data:`PALETTE_CHIPS` &mdash; the canonical :mod:`mait_code.tui.palette` colours, so
a bare call renders exactly as it always has. A TUI that wants the chips to
track the *active* theme (rather than the static palette) builds a bundle from
its live theme and passes it in &mdash; this is how the board keeps its chips in
step with a ``Ctrl+P`` theme switch.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from mait_code.tui import palette as p

__all__ = ["ChipColours", "PALETTE_CHIPS", "priority_chip", "tag_badge"]


@dataclass(frozen=True, slots=True)
class ChipColours:
    """The hexes a chip resolves to, by semantic slot.

    Decoupled from theme *role* names on purpose: the board maps ``tag`` to its
    theme's secondary hue (so tags read distinct from the primary frame), while
    the default bundle keeps ``tag`` on primary &mdash; the heat scale
    (``high``/``medium``/``low``) and ``blocked`` are the same idea.
    """

    high: str
    medium: str
    low: str
    tag: str
    blocked: str


#: The default bundle: the canonical palette. A helper called without a bundle
#: renders exactly as before this slot existed, so nothing that doesn't opt in
#: changes. ``low`` doubles as the unknown-priority fallback (as it always has).
PALETTE_CHIPS = ChipColours(
    high=p.ERROR,
    medium=p.WARNING,
    low=p.SECONDARY,
    tag=p.PRIMARY,
    blocked=p.ERROR,
)

#: Priority level → the :class:`ChipColours` slot it reads from.
_PRIORITY_SLOT = {"high": "high", "medium": "medium", "low": "low"}


def priority_chip(priority: str, colours: ChipColours = PALETTE_CHIPS) -> Text:
    """A one-word priority chip, coloured by level (unknown → the ``low`` hue)."""
    slot = _PRIORITY_SLOT.get(priority, "low")
    return Text(priority, style=getattr(colours, slot))


def tag_badge(
    tag: str, *, blocked: bool = False, colours: ChipColours = PALETTE_CHIPS
) -> Text:
    """A ``#tag`` badge; the blocked tag stands out bold in the ``blocked`` hue."""
    style = f"bold {colours.blocked}" if blocked else colours.tag
    return Text(f"#{tag}", style=style)
