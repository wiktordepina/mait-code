"""Shared filter modals for mait-code TUIs.

:class:`ProjectFilterScreen` is the project ``Select`` the observations and
memory browsers both open on ``p`` — extracted here so the surfaces stay
pixel-consistent instead of each carrying a copy (the board's filter is the
same gesture, built into its column layout).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Select

__all__ = ["ALL_PROJECTS", "ProjectFilterScreen"]

#: Sentinel ``Select`` value for the "every project" option in the project
#: filter modal — kept distinct from the ``None`` that escape/cancel
#: dismisses with (mirrors the board's filter).
ALL_PROJECTS = object()


class ProjectFilterScreen(ModalScreen[object | None]):
    """Pick the project to filter a browser by, via a ``Select``.

    Resolves to one of three outcomes, kept distinct so "all" never collapses
    into the cancel ``None``:

    * a project name — filter to that project;
    * :data:`ALL_PROJECTS` — clear the filter;
    * ``None`` — escape/cancel, leave the active filter untouched.

    The dropdown auto-expands and applies on selection (no Apply button). The
    one wrinkle is that ``Select`` posts a :class:`Select.Changed` for its
    *initial* value on mount, which would dismiss instantly — so a change back
    to the value we opened with is ignored (the board's filter, verbatim).
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, projects: list[str], current: str | None = None) -> None:
        super().__init__()
        self._projects = projects
        self._initial: object = ALL_PROJECTS if current is None else current

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("Filter by project", classes="modal-title")
            yield Select(
                [
                    ("All projects", ALL_PROJECTS),
                    *((proj, proj) for proj in self._projects),
                ],
                value=self._initial,
                allow_blank=False,
                id="project-select",
            )

    def on_mount(self) -> None:
        select = self.query_one("#project-select", Select)
        select.focus()
        select.expanded = True  # open the dropdown so picking is one gesture

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value == self._initial:
            return
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)
