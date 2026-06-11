"""Shared filter modals for mait-code TUIs.

:class:`ChoiceFilterScreen` is the generic pick-one-value ``Select`` modal;
:class:`ProjectFilterScreen` is its project-flavoured face — the one the
observations and memory browsers open on ``p``, kept here so the surfaces stay
pixel-consistent instead of each carrying a copy (the board's filter is the
same gesture, built into its column layout). The log viewer reuses the generic
screen for its tool and day filters.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Select

__all__ = ["ALL_CHOICES", "ALL_PROJECTS", "ChoiceFilterScreen", "ProjectFilterScreen"]

#: Sentinel ``Select`` value for the "everything" option in a filter modal —
#: kept distinct from the ``None`` that escape/cancel dismisses with.
ALL_CHOICES = object()

#: The same sentinel under its original, project-flavoured name.
ALL_PROJECTS = ALL_CHOICES


class ChoiceFilterScreen(ModalScreen[object | None]):
    """Pick one value to filter a browser by, via a ``Select``.

    Resolves to one of three outcomes, kept distinct so "all" never collapses
    into the cancel ``None``:

    * a choice — filter to that value;
    * :data:`ALL_CHOICES` — clear the filter;
    * ``None`` — escape/cancel, leave the active filter untouched.

    The dropdown auto-expands and applies on selection (no Apply button). The
    one wrinkle is that ``Select`` posts a :class:`Select.Changed` for its
    *initial* value on mount, which would dismiss instantly — so a change back
    to the value we opened with is ignored (the board's filter, verbatim).
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        choices: list[str],
        current: str | None = None,
        *,
        all_label: str = "All",
    ) -> None:
        super().__init__()
        self._title = title
        self._choices = choices
        self._all_label = all_label
        self._initial: object = ALL_CHOICES if current is None else current

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(self._title, classes="modal-title")
            yield Select(
                [
                    (self._all_label, ALL_CHOICES),
                    *((choice, choice) for choice in self._choices),
                ],
                value=self._initial,
                allow_blank=False,
                id="choice-select",
            )

    def on_mount(self) -> None:
        select = self.query_one("#choice-select", Select)
        select.focus()
        select.expanded = True  # open the dropdown so picking is one gesture

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value == self._initial:
            return
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ProjectFilterScreen(ChoiceFilterScreen):
    """The project filter the memory and observations browsers share."""

    def __init__(self, projects: list[str], current: str | None = None) -> None:
        super().__init__(
            "Filter by project", projects, current, all_label="All projects"
        )
