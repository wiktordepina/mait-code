"""Shared base :class:`App` for mait-code's Textual TUIs.

:class:`MaitApp` wires the house theme and the shared stylesheet into every
TUI, so the board, the settings editor and any future surface share one
identity. Textual's built-in themes stay registered, so the Ctrl+P command
palette's "Change theme" lists the house theme alongside them &mdash; the
middle-path theming model (a curated default, plus built-ins, plus whatever a
user drops in).

Subclasses include the shared sheet *and* their own layout sheet in
``CSS_PATH`` (Textual reads ``CSS_PATH`` only from the most-derived class, so it
must be repeated explicitly &mdash; it does not merge across the MRO)::

    from pathlib import Path
    from mait_code.tui.app import MaitApp, SHARED_TCSS

    class BoardApp(MaitApp):
        CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_board.tcss"]

Theme registration happens in ``__init__`` (not ``on_mount``) so subclasses that
override ``on_mount`` don't have to remember to call ``super()``.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.binding import Binding

from mait_code.tui.theme import HOUSE_THEMES

__all__ = ["MaitApp", "SHARED_TCSS"]

#: Absolute path to the shared stylesheet. Subclasses put this in their
#: ``CSS_PATH`` list alongside their own layout sheet.
SHARED_TCSS = Path(__file__).parent / "app.tcss"


class MaitApp(App[None]):
    """Base App for mait-code TUIs: house theme + shared stylesheet."""

    CSS_PATH = SHARED_TCSS
    BINDINGS = [Binding("q", "quit", "Quit")]

    #: The house theme applied by default; override to ship a different default.
    HOUSE_THEME = "mait-dark"

    def __init__(self) -> None:
        super().__init__()
        for theme in HOUSE_THEMES:
            self.register_theme(theme)
        self.theme = self.HOUSE_THEME
