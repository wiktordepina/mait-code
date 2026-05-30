"""A shared, context-aware help screen for mait-code TUIs.

:class:`HelpScreen` renders a key→description cheat-sheet from rows the app
captures off its *live* active bindings (see
:meth:`~mait_code.tui.app.MaitApp.action_help`). Because the rows come from the
real bindings rather than a hand-kept list, every app — and every new binding —
shows up automatically and never drifts.
"""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from mait_code.tui import palette as p

__all__ = ["HelpScreen"]


class HelpScreen(ModalScreen[None]):
    """Modal cheat-sheet of the active key-bindings. Esc or ``?`` closes."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("question_mark", "dismiss", "Close"),
    ]

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        super().__init__()
        self._rows = rows

    def compose(self) -> ComposeResult:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(justify="right", no_wrap=True)
        grid.add_column()
        for key, description in self._rows:
            grid.add_row(Text(key, style=f"bold {p.PRIMARY}"), description)
        with VerticalScroll(id="help-dialog", classes="modal-dialog"):
            yield Label("Keys", classes="modal-title")
            yield Static(grid)
