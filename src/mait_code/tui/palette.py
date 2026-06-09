"""Canonical mait-code colour palette &mdash; the single source of truth.

Pure data: this module imports nothing from Textual or the rest of
``mait_code``, so :mod:`mait_code.console` (which sits on the hot CLI path) can
import it without dragging Textual in. Both the Rich CLI theme
(:mod:`mait_code.console`) and the Textual TUI theme
(:mod:`mait_code.tui.theme`) derive their colours from here, so plain CLI
output and the TUIs read as one product.

Every role clears WCAG AA (>=4.5:1) for body text against ``BACKGROUND``,
``SURFACE`` and ``PANEL``. Tune a colour here and both surfaces follow.
"""

from __future__ import annotations

__all__ = [
    # Brand
    "PRIMARY",
    "SECONDARY",
    "ACCENT",
    # Neutrals
    "FOREGROUND",
    "BACKGROUND",
    "SURFACE",
    "PANEL",
    # Semantic
    "SUCCESS",
    "WARNING",
    "ERROR",
    # Helpers
    "rich_colour",
]

# -- Brand -------------------------------------------------------------------
PRIMARY = "#4fb6c7"  # cyan — the house accent, seeded from the original console.py
SECONDARY = "#7aa2f7"  # blue
ACCENT = "#c792ea"  # violet — secondary emphasis

# -- Neutrals ----------------------------------------------------------------
FOREGROUND = "#d7dae0"
BACKGROUND = "#0f1218"  # soft dark, not pure black (avoids halation)
SURFACE = "#161b25"
PANEL = "#1d2230"

# -- Semantic ----------------------------------------------------------------
SUCCESS = "#87d96c"
WARNING = "#f9c560"
ERROR = "#ef6b6b"


# -- Helpers -------------------------------------------------------------------


def rich_colour(value: str | None, fallback: str) -> str:
    """A theme colour string Rich can parse as a ``Text`` span style.

    House and built-in themes store ``#rrggbb`` (Rich-safe as-is). Textual's
    *ansi* themes store names like ``ansi_yellow`` that Rich rejects with a
    ``MissingStyle`` — strip the prefix to Rich's own ``yellow`` / ``green`` /
    ``red``, which render through the terminal's ANSI palette, exactly what an
    ansi theme intends. Anything missing or otherwise unrecognised falls back to
    the given house hex, so a span style is never malformed.
    """
    if not value:
        return fallback
    if value.startswith("#"):
        return value
    if value.startswith("ansi_"):
        return value[len("ansi_") :]
    return fallback
