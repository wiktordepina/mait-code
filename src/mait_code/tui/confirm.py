"""Shared yes/no confirmation modal for mait-code TUIs.

:class:`ConfirmScreen` is the modal the settings editor opens before a
re-embed or a data-dir move, and the home hub opens before a reindex —
extracted here so the surfaces stay pixel-consistent instead of each
carrying a copy. Styling rides the shared ``.modal-dialog`` classes in
``app.tcss``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label

__all__ = ["ConfirmScreen"]


class ConfirmScreen(ModalScreen[bool]):
    """A yes/no modal; ``push_screen_wait`` resolves to the chosen bool."""

    BINDINGS = [("escape", "dismiss_no", "No")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(self._question, classes="modal-title")
            with Horizontal(classes="modal-buttons"):
                yield Button("Yes", id="yes", variant="primary")
                yield Button("No", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_dismiss_no(self) -> None:
        self.dismiss(False)
