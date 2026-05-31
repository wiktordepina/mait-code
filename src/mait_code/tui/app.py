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
from typing import Final

from textual.app import App
from textual.binding import Binding
from textual.notifications import SeverityLevel

from mait_code.tui.help import HelpScreen
from mait_code.tui.theme import HOUSE_THEMES

__all__ = ["MaitApp", "SHARED_TCSS", "TOAST_GLYPHS"]

#: Absolute path to the shared stylesheet. Subclasses put this in their
#: ``CSS_PATH`` list alongside their own layout sheet.
SHARED_TCSS = Path(__file__).parent / "app.tcss"

#: Per-severity leading glyph prefixed to a toast's title, so every mait-code
#: notification carries a consistent house marker. Each glyph's colour is the
#: ``.toast--title`` rule for that severity in ``app.tcss``, so it tracks the
#: active theme. Keyed by Textual's three severity levels.
TOAST_GLYPHS: Final[dict[str, str]] = {
    "information": "\N{INFORMATION SOURCE}",
    "warning": "\N{WARNING SIGN}",
    "error": "\N{HEAVY BALLOT X}",
}


class MaitApp(App[None]):
    """Base App for mait-code TUIs: house theme + shared stylesheet."""

    CSS_PATH = SHARED_TCSS
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
    ]

    #: The house theme applied by default; override to ship a different default.
    HOUSE_THEME = "mait-dark"

    def __init__(self) -> None:
        super().__init__()
        for theme in HOUSE_THEMES:
            self.register_theme(theme)
        self.theme = self.HOUSE_THEME

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None:
        """Show a toast, prefixing its title with a per-severity house glyph.

        Extends :meth:`textual.app.App.notify` so every mait-code toast carries a
        consistent leading marker (``\N{INFORMATION SOURCE}``/``\N{WARNING SIGN}``/``\N{HEAVY BALLOT X}``).
        The glyph's colour comes from the per-severity ``.toast--title`` rules in
        ``app.tcss``, so it re-skins with the active theme like the rest of the
        TUI. Behaviour is otherwise identical to the base method.
        """
        glyph = TOAST_GLYPHS.get(severity, "")
        if glyph:
            title = f"{glyph} {title}".rstrip()
        super().notify(
            message, title=title, severity=severity, timeout=timeout, markup=markup
        )

    def action_help(self) -> None:
        """Show a cheat-sheet of the currently active key-bindings.

        Rows are captured from the live ``active_bindings`` *before* the modal is
        pushed (pushing it would replace them with the help screen's own), and
        de-duplicated to the user-facing ones the footer would show.
        """
        rows: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for active in self.active_bindings.values():
            binding = active.binding
            if not (active.enabled and binding.show and binding.description):
                continue
            # Use the app's friendly key display (← / < / ?), like the footer —
            # not binding.key_display, which is usually the raw key name.
            key = self.get_key_display(binding)
            sig = (key, binding.description)
            if sig in seen:
                continue
            seen.add(sig)
            rows.append(sig)
        self.push_screen(HelpScreen(rows))
