"""Interactive ``mait-code board`` &mdash; a Textual kanban TUI.

A full-screen, on-demand board: one column-pane per status laid side by side,
every project's cards visible with a project filter, keyboard navigation, and
move / comment / tag / block gestures. It runs in the foreground and exits on ``q``
&mdash; no background process &mdash; mirroring the ``mait-code settings`` editor.

Every query and mutation delegates to
:mod:`mait_code.tools.board.service`, so the done-invariant and the SQL live in
one place; this module owns only presentation. The app holds a single
connection for its lifetime (opened in ``__init__``, closed on unmount).

Requires a TTY; the bare ``board`` command only routes here when attached to
one, falling back to a read-only render otherwise.
"""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    TextArea,
)

from mait_code.tools.board import service
from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    BLOCKED_TAG,
    BOARD_ORDER,
    DONE,
    IN_PROGRESS,
    REFINED,
    label as col_label,
)
from mait_code.tools.board.db import get_connection, get_project
from mait_code.tui.app import SHARED_TCSS, MaitApp

__all__ = ["BoardApp", "run_board_tui"]

#: Every pane shown, in left-to-right order. ``archived`` is the hidden last
#: pane, revealed by the ``a`` toggle.
_PANES: tuple[str, ...] = (*BOARD_ORDER, ARCHIVED)

#: The linear flow the ``<``/``>`` keys move a card along — every real status
#: except the hidden ``archived`` side-state, which is reached only via the CLI.
_MOVE_FLOW: tuple[str, ...] = (BACKLOG, REFINED, IN_PROGRESS, DONE)


def run_board_tui(db_path: Path | None = None) -> None:
    """Launch the Textual board (blocks until the user quits)."""
    BoardApp(db_path=db_path).run()


#: Leading glyph that marks a blocked card. A trailing ``#blocked`` tag is
#: truncated off the narrow column, and the ``bold red`` colour is overridden by
#: the DataTable cursor highlight on the *selected* row — but a leading marker
#: survives both, so a blocked card always reads as blocked.
_BLOCKED_MARK = "⊘ "


def _card_row(card: dict, *, show_project: bool) -> Text:
    """Render one card as a single-column DataTable cell.

    A blocked card gets a leading :data:`_BLOCKED_MARK` and its whole row is
    styled ``bold red``. The marker is the robust signal (it survives truncation
    and the cursor highlight); the colour is the emphasis on top.
    """
    tags = card.get("tags", [])
    blocked = BLOCKED_TAG in tags
    mark = _BLOCKED_MARK if blocked else ""
    text = Text(
        f"{mark}#{card['id']} ({card['priority']}) {card['title']}",
        style="bold red" if blocked else "",
    )
    if show_project:
        text.append(f"  {card['project']}", style="dim")
    for tag in tags:
        style = "bold red" if tag == BLOCKED_TAG else "dim"
        text.append(f" #{tag}", style=style)
    return text


class BoardColumn(DataTable):
    """A status column's card list.

    Routes its navigation/action keys to the parent app so the focused table
    drives the whole board. ``up``/``down`` stay native (row cursor); ``left``/
    ``right`` are rebound off the table's own column-cursor moves onto the app's
    pane focus.
    """

    BINDINGS = [
        Binding("left", "app.focus_prev_col", "Col ←"),
        Binding("right", "app.focus_next_col", "Col →"),
        Binding("less_than_sign", "app.move_left", "Move ←"),
        Binding("greater_than_sign", "app.move_right", "Move →"),
        Binding("enter", "app.detail", "Detail"),
        Binding("n", "app.new", "New"),
        Binding("e", "app.edit", "Edit"),
        Binding("C", "app.complete", "Complete"),
        Binding("c", "app.comment", "Comment"),
        Binding("t", "app.tag", "Tag"),
        Binding("b", "app.block", "Block"),
        Binding("u", "app.unblock", "Unblock"),
        Binding("p", "app.cycle_project", "Project"),
        Binding("a", "app.toggle_archived", "Archived"),
        Binding("r", "app.reload_board", "Reload"),
    ]


class DetailScreen(ModalScreen[None]):
    """Read-only card detail: fields plus the comment thread. Esc closes."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, card: dict, comments: list[dict]) -> None:
        super().__init__()
        self._card = card
        self._comments = comments

    def compose(self) -> ComposeResult:
        card = self._card
        with VerticalScroll(id="detail-dialog", classes="modal-dialog"):
            yield Label(
                escape(f"#{card['id']} ({card['priority']}) {card['title']}"),
                classes="detail-title",
            )
            yield Static(
                escape(
                    f"project: {card['project']}   status: {col_label(card['status'])}"
                ),
                classes="detail-meta",
            )
            if card.get("tags"):
                yield Label("Tags", classes="detail-head")
                yield Static(escape(", ".join(card["tags"])))
            if card["description"]:
                yield Label("Description", classes="detail-head")
                yield Static(escape(card["description"]))
            if card["acceptance_criteria"]:
                yield Label("Acceptance criteria", classes="detail-head")
                yield Static(escape(card["acceptance_criteria"]))
            if card["completion_summary"]:
                yield Label("Completion summary", classes="detail-head")
                yield Static(escape(card["completion_summary"]))
            yield Label(f"Comments ({len(self._comments)})", classes="detail-head")
            if self._comments:
                for comment in self._comments:
                    # Escape so a body or author containing brackets isn't
                    # parsed as Rich console markup (Textual 8's Content system
                    # parses "[...]" even from a Text, dropping the span text).
                    yield Static(escape(f"[{comment['author']}] {comment['body']}"))
            else:
                yield Static("(none)", classes="detail-dim")


class CommentScreen(ModalScreen[str | None]):
    """A single-line comment input; resolves to the body, or ``None`` on cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, card_id: int) -> None:
        super().__init__()
        self._card_id = card_id

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(f"Comment on card #{self._card_id}", classes="modal-title")
            yield Input(placeholder="Your comment…", id="comment-input")
            with Horizontal(classes="modal-buttons"):
                yield Button("Add", id="comment-add", variant="primary")
                yield Button("Cancel", id="comment-cancel")

    def on_mount(self) -> None:
        self.query_one("#comment-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "comment-add":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        body = self.query_one("#comment-input", Input).value.strip()
        self.dismiss(body or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TagScreen(ModalScreen[str | None]):
    """A single-line tag input; resolves to the tag, or ``None`` on cancel.

    The app *toggles* the returned tag: present → removed, absent → added.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, card_id: int) -> None:
        super().__init__()
        self._card_id = card_id

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(f"Tag card #{self._card_id} (toggles)", classes="modal-title")
            yield Input(placeholder="tag…", id="tag-input")
            with Horizontal(classes="modal-buttons"):
                yield Button("Apply", id="tag-apply", variant="primary")
                yield Button("Cancel", id="tag-cancel")

    def on_mount(self) -> None:
        self.query_one("#tag-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tag-apply":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        tag = self.query_one("#tag-input", Input).value.strip()
        self.dismiss(tag or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


#: Priority choices, low→high, as offered in the new/edit modals.
_PRIORITIES: tuple[str, ...] = ("low", "medium", "high")


class NewCardScreen(ModalScreen[dict | None]):
    """Capture a new card's title, project and priority.

    Resolves to a ``{title, project, priority}`` dict, or ``None`` on cancel.
    An empty title keeps the modal open (a titleless card is never created);
    escape always cancels.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, default_project: str) -> None:
        super().__init__()
        self._default_project = default_project

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("New card", classes="modal-title")
            yield Input(placeholder="Title…", id="new-title")
            yield Input(
                value=self._default_project, placeholder="project", id="new-project"
            )
            yield RadioSet(
                *(RadioButton(p, value=(p == "medium")) for p in _PRIORITIES),
                id="new-priority",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Add", id="new-add", variant="primary")
                yield Button("Cancel", id="new-cancel")

    def on_mount(self) -> None:
        self.query_one("#new-title", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-add":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        title = self.query_one("#new-title", Input).value.strip()
        if not title:
            return  # title required; stay open (escape to cancel)
        project = (
            self.query_one("#new-project", Input).value.strip() or self._default_project
        )
        idx = self.query_one("#new-priority", RadioSet).pressed_index
        priority = _PRIORITIES[idx] if idx >= 0 else "medium"
        self.dismiss({"title": title, "project": project, "priority": priority})

    def action_cancel(self) -> None:
        self.dismiss(None)


class EditCardScreen(ModalScreen[dict | None]):
    """Edit the focused card's title/priority/description/acceptance.

    Resolves to a dict of the edited fields, or ``None`` on cancel. Title is
    required; escape cancels.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, card: dict) -> None:
        super().__init__()
        self._card = card

    def compose(self) -> ComposeResult:
        card = self._card
        with Vertical(classes="modal-dialog", id="edit-dialog"):
            yield Label(f"Edit card #{card['id']}", classes="modal-title")
            with VerticalScroll(id="edit-fields"):
                yield Label("Title", classes="field-label")
                yield Input(value=card["title"], id="edit-title")
                yield Label("Priority", classes="field-label")
                yield RadioSet(
                    *(
                        RadioButton(p, value=(p == card["priority"]))
                        for p in _PRIORITIES
                    ),
                    id="edit-priority",
                )
                yield Label("Description", classes="field-label")
                yield TextArea(card.get("description") or "", id="edit-description")
                yield Label("Acceptance criteria", classes="field-label")
                yield TextArea(
                    card.get("acceptance_criteria") or "", id="edit-acceptance"
                )
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", id="edit-save", variant="primary")
                yield Button("Cancel", id="edit-cancel")

    def on_mount(self) -> None:
        self.query_one("#edit-title", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "edit-save":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        title = self.query_one("#edit-title", Input).value.strip()
        if not title:
            return  # title required; stay open
        idx = self.query_one("#edit-priority", RadioSet).pressed_index
        priority = _PRIORITIES[idx] if idx >= 0 else self._card["priority"]
        self.dismiss(
            {
                "title": title,
                "priority": priority,
                "description": self.query_one("#edit-description", TextArea).text,
                "acceptance_criteria": self.query_one(
                    "#edit-acceptance", TextArea
                ).text,
            }
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class CompleteScreen(ModalScreen[str | None]):
    """Prompt for a completion summary; resolves to the summary or ``None``.

    A summary is the whole point of this gesture (vs a bare move into done), so
    an empty summary cancels — done cards are never summary-less.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, card_id: int) -> None:
        super().__init__()
        self._card_id = card_id

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(
                f"Complete card #{self._card_id} — summary", classes="modal-title"
            )
            yield Input(placeholder="What was done…", id="complete-input")
            with Horizontal(classes="modal-buttons"):
                yield Button("Complete", id="complete-ok", variant="primary")
                yield Button("Cancel", id="complete-cancel")

    def on_mount(self) -> None:
        self.query_one("#complete-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "complete-ok":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        summary = self.query_one("#complete-input", Input).value.strip()
        self.dismiss(summary or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BoardApp(MaitApp):
    """Full-screen kanban over every project's cards."""

    TITLE = "mait-code board"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_board.tcss"]

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self._conn = get_connection(db_path)  # one connection for the app's life
        self._project_filter: str | None = None  # None == all projects
        self._projects: list[str] = []
        self._show_archived = False
        self._focused_col = 0
        self._card_status: dict[int, str] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            for status in _PANES:
                with Vertical(classes="col", id=f"col-{status}"):
                    yield Label(
                        col_label(status), classes="col-head", id=f"head-{status}"
                    )
                    yield BoardColumn(
                        id=f"tbl-{status}", cursor_type="row", show_header=False
                    )
        yield Footer()

    def on_mount(self) -> None:
        self._projects = service.list_projects(self._conn)
        for status in _PANES:
            self.query_one(f"#tbl-{status}", BoardColumn).add_column("card")
        # The archived pane stays hidden until the `a` toggle reveals it.
        self.query_one("#col-archived", Vertical).display = False
        self._update_subtitle()
        self._reload()
        self._focus_current()

    def on_unmount(self) -> None:
        self._conn.close()

    # -- layout helpers ----------------------------------------------------

    def _visible_statuses(self) -> list[str]:
        return list(BOARD_ORDER) + ([ARCHIVED] if self._show_archived else [])

    def _update_subtitle(self) -> None:
        self.sub_title = f"project: {self._project_filter or 'all'}  (p to cycle)"

    def _reload(self) -> None:
        """Re-query with the active filter and repaint every pane."""
        cards = service.list_cards(
            self._conn,
            project=self._project_filter,
            include_archived=self._show_archived,
        )
        self._card_status = {c["id"]: c["status"] for c in cards}
        by_status: dict[str, list[dict]] = {}
        for card in cards:
            by_status.setdefault(card["status"], []).append(card)
        show_project = self._project_filter is None
        for status in _PANES:
            table = self.query_one(f"#tbl-{status}", BoardColumn)
            table.clear()
            group = by_status.get(status, [])
            for card in group:
                table.add_row(
                    _card_row(card, show_project=show_project), key=str(card["id"])
                )
            head = self.query_one(f"#head-{status}", Label)
            head.update(f"{col_label(status)} ({len(group)})")

    def _focus_current(self) -> None:
        status = self._visible_statuses()[self._focused_col]
        self.query_one(f"#tbl-{status}", BoardColumn).focus()

    def _focus_status(self, status: str) -> None:
        """Focus the pane for *status* (used by tests and card-following)."""
        statuses = self._visible_statuses()
        self._focused_col = statuses.index(status)
        self._focus_current()

    def _selected_card_id(self) -> int | None:
        status = self._visible_statuses()[self._focused_col]
        table = self.query_one(f"#tbl-{status}", BoardColumn)
        if table.row_count == 0:
            return None
        cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
        value = cell_key.row_key.value
        return int(value) if value is not None else None

    def _select_card(self, card_id: int) -> None:
        """Follow a card to its (possibly new) pane and highlight it."""
        status = self._card_status.get(card_id)
        statuses = self._visible_statuses()
        if status is None or status not in statuses:
            return
        self._focused_col = statuses.index(status)
        table = self.query_one(f"#tbl-{status}", BoardColumn)
        key = str(card_id)
        for idx, row in enumerate(table.ordered_rows):
            if row.key.value == key:
                table.move_cursor(row=idx)
                break
        table.focus()

    # -- navigation --------------------------------------------------------

    def action_focus_prev_col(self) -> None:
        n = len(self._visible_statuses())
        self._focused_col = (self._focused_col - 1) % n
        self._focus_current()

    def action_focus_next_col(self) -> None:
        n = len(self._visible_statuses())
        self._focused_col = (self._focused_col + 1) % n
        self._focus_current()

    # -- moving ------------------------------------------------------------

    def action_move_left(self) -> None:
        self._shift(-1)

    def action_move_right(self) -> None:
        self._shift(1)

    def _shift(self, delta: int) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        status = self._card_status.get(card_id)
        if status not in _MOVE_FLOW:
            self.notify("Archived cards aren't on the move line.")
            return
        idx = _MOVE_FLOW.index(status) + delta
        if idx < 0 or idx >= len(_MOVE_FLOW):
            self.notify("Already at the end of the flow.")
            return
        service.move_card(self._conn, card_id, _MOVE_FLOW[idx])
        self._reload()
        self._select_card(card_id)

    # -- block / unblock ---------------------------------------------------

    def action_block(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        service.block_card(self._conn, card_id)
        self._reload()
        self._select_card(card_id)

    def action_unblock(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        service.unblock_card(self._conn, card_id)
        self._reload()
        self._select_card(card_id)

    # -- filter / archived / reload ---------------------------------------

    def action_cycle_project(self) -> None:
        options: list[str | None] = [None, *self._projects]
        try:
            current = options.index(self._project_filter)
        except ValueError:
            current = 0
        self._project_filter = options[(current + 1) % len(options)]
        self._update_subtitle()
        self._reload()

    def action_toggle_archived(self) -> None:
        self._show_archived = not self._show_archived
        self.query_one("#col-archived", Vertical).display = self._show_archived
        # If archived was focused and we just hid it, fall back to the last pane.
        if not self._show_archived and self._focused_col >= len(BOARD_ORDER):
            self._focused_col = len(BOARD_ORDER) - 1
        self._reload()
        self._focus_current()

    def action_reload_board(self) -> None:
        self._projects = service.list_projects(self._conn)
        self._reload()
        self._focus_current()

    # -- detail / comment --------------------------------------------------

    @work
    async def action_detail(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        card = service.get_card(self._conn, card_id)
        if card is None:
            return
        comments = service.get_comments(self._conn, card_id)
        await self.push_screen_wait(DetailScreen(card, comments))

    @work
    async def action_comment(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        body = await self.push_screen_wait(CommentScreen(card_id))
        if not body:
            return
        service.add_comment(self._conn, card_id, body)
        self._reload()
        self._select_card(card_id)

    @work
    async def action_tag(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        tag = await self.push_screen_wait(TagScreen(card_id))
        if not tag:
            return
        # Toggle: a tag already on the card is removed, otherwise added.
        if tag in service.list_tags(self._conn, card_id):
            service.remove_tag(self._conn, card_id, tag)
        else:
            service.add_tag(self._conn, card_id, tag)
        self._reload()
        self._select_card(card_id)

    # -- mutation modals ---------------------------------------------------

    @work
    async def action_new(self) -> None:
        default = self._project_filter or get_project()
        result = await self.push_screen_wait(NewCardScreen(default))
        if not result:
            return
        card_id = service.add_card(
            self._conn,
            project=result["project"],
            title=result["title"],
            priority=result["priority"],
        )
        self._projects = service.list_projects(self._conn)
        self._reload()
        self._select_card(card_id)
        self.notify(f"Created card #{card_id}")

    @work
    async def action_edit(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        card = service.get_card(self._conn, card_id)
        if card is None:
            return
        result = await self.push_screen_wait(EditCardScreen(card))
        if not result:
            return
        service.edit_card(self._conn, card_id, **result)
        self._reload()
        self._select_card(card_id)
        self.notify(f"Updated card #{card_id}")

    @work
    async def action_complete(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        summary = await self.push_screen_wait(CompleteScreen(card_id))
        if not summary:
            return
        service.complete_card(self._conn, card_id, summary=summary)
        self._reload()
        self._select_card(card_id)
        self.notify(f"Completed card #{card_id}")
