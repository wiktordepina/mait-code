"""The board's Initiatives view &mdash; epics and their members.

A :class:`~textual.screen.Screen` inside :class:`~mait_code.cli._board_tui.BoardApp`
rather than an app of its own: it shares the board's connection, its card
screen and edit forms, and ``i`` flips between it and the kanban. Epics never
appear on the kanban, so this is where they live.

Left, every open epic with its progress; right, a table of the highlighted
epic's members across every project, sorted so what can move comes first.
The board's project and search filters don't apply here — an initiative spans
projects, and hiding half of one would misstate its progress.

Kept out of ``_board_tui`` (already ~1,800 lines). This module imports that
one; the board imports this one lazily, inside the actions that need it.
"""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Label, OptionList
from textual.widgets.data_table import CellDoesNotExist, RowDoesNotExist
from textual.widgets.option_list import Option

from mait_code.cli._board_tui import BoardApp
from mait_code.tools.board import export, service
from mait_code.tools.board.columns import (
    BACKLOG,
    BLOCKED_TAG,
    DONE,
    IN_PROGRESS,
    IN_REVIEW,
    REFINED,
    label as col_label,
)
from mait_code.tui import palette as p
from mait_code.tui.banner import BrandBanner
from mait_code.tui.brand import empty_state

__all__ = ["InitiativesScreen"]

#: Glyphs for the member table's first column: ready to pick up, or held up.
_READY_MARK = "●"
_BLOCKED_MARK = "◼"

#: Member-table buckets, in display order. ``ready`` and ``blocked`` are
#: derived states; the rest are statuses. See :func:`_bucket`.
_BUCKETS: tuple[str, ...] = (
    "ready",
    IN_PROGRESS,
    IN_REVIEW,
    "blocked",
    REFINED,
    BACKLOG,
    DONE,
)


def _is_blocked(card: dict) -> bool:
    return bool(card["waiting_on"]) or BLOCKED_TAG in card["tags"]


def _bucket(card: dict, ready: set[int]) -> int:
    """Where *card* sorts in the member table.

    Ready first (what can be picked up now); then work in flight; then
    anything held up — waiting on a blocker or tagged ``blocked``, in any open
    column; then the remaining refined and backlog cards; done last.
    """
    if card["id"] in ready:
        return _BUCKETS.index("ready")
    if card["status"] != DONE and _is_blocked(card):
        return _BUCKETS.index("blocked")
    return _BUCKETS.index(card["status"])


def _blocked_cell(card: dict) -> str:
    """``#76, #80`` for a waiting card, ``blocked`` for a tagged one, or both."""
    parts = []
    if BLOCKED_TAG in card["tags"]:
        parts.append("blocked")
    if card["waiting_on"]:
        parts.append(", ".join(f"#{i}" for i in card["waiting_on"]))
    return " · ".join(parts)


class InitiativesScreen(Screen[None]):
    """Epics with progress on the left, the highlighted epic's members right.

    Selecting an epic or a member (``enter`` or a click) opens the board's card
    screen on it; anything changed there — or by the CLI underneath, through
    the board's live poll — re-reads both panes. ``i`` or ``escape`` returns to
    the kanban.
    """

    BINDINGS = [
        Binding("left", "focus_epics", "Epics", show=False),
        Binding("right", "focus_members", "Members", show=False),
        Binding("R", "toggle_ready", "Ready only"),
        Binding("d", "toggle_done", "Done epics"),
        Binding("r", "reload", "Reload"),
        Binding("i", "kanban", "Board"),
        Binding("escape", "kanban", "Board", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._show_done = False
        self._ready_only = False
        self._epic_id: int | None = None  # the highlighted epic

    @property
    def board(self) -> BoardApp:
        app = self.app
        assert isinstance(app, BoardApp)
        return app

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Initiatives · every project")
        with Horizontal(id="initiatives-body"):
            with Vertical(id="initiatives-epics"):
                yield Label("Initiatives", classes="col-head", id="epics-head")
                yield OptionList(id="epics")
            with Vertical(id="initiatives-members"):
                yield Label("", classes="col-head", id="members-head")
                yield DataTable(cursor_type="row", zebra_stripes=True, id="members")
                yield Label("", classes="detail-dim", id="members-empty")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#members", DataTable)
        table.add_column("", key="mark")
        table.add_column("#", key="id")
        table.add_column("Title", key="title")
        table.add_column("Project", key="project")
        table.add_column("Status", key="status")
        table.add_column("Blocked", key="blocked")
        self.refresh_data()
        self.query_one("#epics", OptionList).focus()

    # -- data ---------------------------------------------------------------

    def refresh_data(self) -> None:
        """Re-read the epics and the highlighted epic's members, in place.

        Keeps the highlighted epic (or falls back to the first) and the member
        cursor's card, so a refresh under the user doesn't move them.
        """
        epics = service.list_epics(self.board.conn, include_done=self._show_done)
        ids = [e["id"] for e in epics]
        if self._epic_id not in ids:
            self._epic_id = ids[0] if ids else None
        option_list = self.query_one("#epics", OptionList)
        option_list.clear_options()
        if epics:
            option_list.add_options(self._epic_option(e) for e in epics)
            assert self._epic_id is not None
            option_list.highlighted = ids.index(self._epic_id)
        else:
            option_list.add_option(
                Option(
                    Text(empty_state("No initiatives yet."), style="dim"), disabled=True
                )
            )
        head = "Initiatives (all)" if self._show_done else "Initiatives"
        self.query_one("#epics-head", Label).update(f"{head} ({len(epics)})")
        self._fill_members({e["id"]: e for e in epics}.get(self._epic_id))

    def _epic_option(self, epic: dict) -> Option:
        text = Text()
        text.append(f"#{epic['id']} ", style="bold")
        text.append(epic["title"])
        text.append("\n")
        meta = export.progress_text(epic["progress"])
        if epic["status"] == DONE:
            meta = f"{meta} · epic done"
        text.append(meta, style="dim")
        return Option(text, id=str(epic["id"]))

    def _fill_members(self, epic: dict | None) -> None:
        table = self.query_one("#members", DataTable)
        empty = self.query_one("#members-empty", Label)
        head = self.query_one("#members-head", Label)
        cursor = self._cursor_card_id()
        table.clear()
        if epic is None:
            head.update("")
            table.display = False
            empty.update(empty_state("Create one with mc-tool-board add --epic."))
            empty.display = True
            return
        conn = self.board.conn
        members = service.list_cards(conn, parent_id=epic["id"])
        ready = {
            c["id"] for c in service.list_cards(conn, parent_id=epic["id"], ready=True)
        }
        if self._ready_only:
            members = [c for c in members if c["id"] in ready]
        members.sort(key=lambda c: _bucket(c, ready))  # stable: keeps priority order
        title = (
            f"#{epic['id']} {epic['title']} — {export.progress_text(epic['progress'])}"
        )
        # Text, not str: Label and DataTable parse a str as markup, and a
        # title may well contain "[...]".
        head.update(Text(f"{title}  · ready only" if self._ready_only else title))
        ready_hue, blocked_hue = self._mark_hues()
        for card in members:
            if card["id"] in ready:
                mark = Text(_READY_MARK, style=f"bold {ready_hue}")
            elif card["status"] != DONE and _is_blocked(card):
                mark = Text(_BLOCKED_MARK, style=f"bold {blocked_hue}")
            else:
                mark = Text("")
            table.add_row(
                mark,
                Text(str(card["id"])),
                Text(card["title"]),
                Text(card["project"], style="dim"),
                Text(col_label(card["status"])),
                Text(_blocked_cell(card)),
                key=str(card["id"]),
            )
        table.display = bool(members)
        empty.display = not members
        if not members:
            empty.update(
                empty_state("Nothing ready in this epic.")
                if self._ready_only
                else empty_state("No members yet.")
            )
        elif cursor is not None:
            try:
                table.move_cursor(row=table.get_row_index(str(cursor)))
            except RowDoesNotExist:  # the card left the table: cursor stays at 0
                pass

    def _cursor_card_id(self) -> int | None:
        table = self.query_one("#members", DataTable)
        if not table.row_count:
            return None
        try:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except CellDoesNotExist:
            return None
        return int(key.value) if key.value is not None else None

    def _mark_hues(self) -> tuple[str, str]:
        """The ready and blocked glyph hues for the active theme.

        Blocked matches the kanban's blocked border (the board's chip bundle);
        ready takes the theme's success role, falling back to the canonical
        hex under an ANSI theme, whose named colours aren't Rich styles.
        """
        success = self.app.current_theme.success or ""
        ready = success if success.startswith("#") else p.SUCCESS
        return ready, self.board.chip_colours().blocked

    # -- events -------------------------------------------------------------

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option.id is None:
            return
        epic_id = int(event.option.id)
        if epic_id != self._epic_id:
            self._epic_id = epic_id
            self.refresh_data()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is not None:
            self._open(int(event.option.id))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value is not None:
            self._open(int(event.row_key.value))

    @work
    async def _open(self, card_id: int) -> None:
        """Open *card_id* in the board's card screen, then re-read both panes."""
        await self.board.open_card(card_id)
        self.refresh_data()

    # -- actions ------------------------------------------------------------

    def action_focus_epics(self) -> None:
        self.query_one("#epics", OptionList).focus()

    def action_focus_members(self) -> None:
        self.query_one("#members", DataTable).focus()

    def action_toggle_ready(self) -> None:
        self._ready_only = not self._ready_only
        self.refresh_data()

    def action_toggle_done(self) -> None:
        self._show_done = not self._show_done
        self.refresh_data()

    def action_reload(self) -> None:
        self.refresh_data()

    def action_kanban(self) -> None:
        self.board.show_kanban()
