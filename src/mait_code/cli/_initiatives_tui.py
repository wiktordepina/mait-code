"""The board's Initiatives view &mdash; epics and their members.

A :class:`~textual.screen.Screen` inside :class:`~mait_code.cli._board_tui.BoardApp`
rather than an app of its own: it shares the board's connection, its card
screen and edit forms, and ``i`` flips between it and the kanban. Epics never
appear on the kanban, so this is where they live.

Left, every open epic with its progress; right, a table of the highlighted
epic's members across every project, sorted so what can move comes first -
or, behind ``g``, a dependency diagram of the epic's ``blocks`` links.
The board's project and search filters don't apply here - an initiative spans
projects, and hiding half of one would misstate its progress.

Kept out of ``_board_tui`` (already ~1,800 lines). This module imports that
one; the board imports this one lazily, inside the actions that need it.
"""

from __future__ import annotations

import textwrap
from collections.abc import Hashable
from typing import Any

from netext import ArrowTip, EdgeRoutingMode, EdgeSegmentDrawingMode
from netext.layout_engines import LayoutDirection, SugiyamaLayout
from rich.console import RenderableType
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import ContentSwitcher, DataTable, Footer, Label, OptionList
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
from mait_code.tui.graph import ThemedGraphView

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
    anything held up - waiting on a blocker or tagged ``blocked``, in any open
    column; then the remaining refined and backlog cards, including a refined
    card that a live session is bound to (it isn't free to pick up); done
    last.
    """
    if card["id"] in ready:
        return _BUCKETS.index("ready")
    if card["status"] != DONE and _is_blocked(card):
        return _BUCKETS.index("blocked")
    return _BUCKETS.index(card["status"])


#: Width a diagram node's title wraps to; two lines at most, then an ellipsis glyph.
_NODE_WIDTH = 24

#: The two right-hand panes the ``g`` key switches between.
_TABLE_PANE = "members-table-pane"
_GRAPH_PANE = "members-graph-pane"


def _node_content(node: str, data: dict[str, Any], style: Style) -> RenderableType:
    """A diagram node's box content: ``#id`` (and a stub's project), then the
    title wrapped to :data:`_NODE_WIDTH` and clipped to two lines.

    netext's ``$content-renderer`` hook; it renders into an unbounded panel, so
    the wrapping has to happen here rather than being left to Rich.
    """
    text = Text(f"#{node}", style=style + Style(bold=True))
    if data["stub"]:
        text.append(f" · {data['project']}", style=style)
    lines = textwrap.wrap(data["title"], _NODE_WIDTH) or [""]
    if len(lines) > 2:
        lines = [lines[0], lines[1][: _NODE_WIDTH - 1] + "…"]
    for line in lines:
        text.append("\n" + line, style=style)
    return text


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
    screen on it; anything changed there - or by the CLI underneath, through
    the board's live poll - re-reads both panes. ``i`` returns to the kanban;
    ``escape`` leaves the board app, which from the hub lands back there.

    ``g`` swaps the member table for a read-only dependency diagram: the
    epic's linked members and the cards one link outside it (dimmed stubs),
    laid out top-down so blockers sit above what they block. Members with no
    links are counted under it rather than drawn, so a long tail of loose
    cards doesn't bury the chains.
    """

    BINDINGS = [
        Binding("left", "focus_epics", "Epics", show=False),
        Binding("right", "focus_members", "Members", show=False),
        # One key, two gated bindings: check_action() enables exactly the one
        # that leaves the current view, so the footer names the destination.
        Binding("g", "show_graph", "Graph"),
        Binding("g", "show_table", "Table"),
        Binding("R", "toggle_ready", "Ready only"),
        Binding("d", "toggle_done", "Done epics"),
        Binding("r", "reload", "Reload"),
        # No escape binding: the app's own (quit) applies, as on the kanban.
        Binding("i", "kanban", "Board"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._show_done = False
        self._ready_only = False
        self._epic_id: int | None = None  # the highlighted epic
        self._view = _TABLE_PANE
        # The diagram the graph view should show. netext drops set_graph()
        # while the widget is hidden or unsized, so it's held here and applied
        # once the view has real dimensions (see _apply_graph).
        self._graph_data: tuple[dict, list] | None = None
        self._graph_applied = False

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
                # Containers, not the widgets themselves: _fill_members toggles
                # the table's own display, which must never un-hide it over
                # the diagram.
                with ContentSwitcher(initial=_TABLE_PANE, id="members-switcher"):
                    with Vertical(id=_TABLE_PANE):
                        yield DataTable(
                            cursor_type="row", zebra_stripes=True, id="members"
                        )
                        yield Label("", classes="detail-dim", id="members-empty")
                    with Vertical(id=_GRAPH_PANE):
                        # Zoom 1.0, not AutoZoom.FIT: FIT scales node positions
                        # per axis but draws boxes full-size, so a long chain
                        # collides. At 1.0 a big graph scrolls instead.
                        yield ThemedGraphView(
                            id="deps",
                            zoom=1.0,
                            layout_engine=SugiyamaLayout(LayoutDirection.TOP_DOWN),
                        )
                        yield Label("", classes="detail-dim", id="deps-note")
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
            message = empty_state("Create one with mc-tool-board add --epic.")
            empty.update(message)
            empty.display = True
            self._set_diagram(None, message)
            return
        conn = self.board.conn
        all_members = service.list_cards(conn, parent_id=epic["id"])
        ready = {
            c["id"] for c in service.list_cards(conn, parent_id=epic["id"], ready=True)
        }
        self._fill_diagram(epic, all_members, ready)
        members = all_members
        if self._ready_only:
            members = [c for c in members if c["id"] in ready]
        members.sort(key=lambda c: _bucket(c, ready))  # stable: keeps priority order
        title = (
            f"#{epic['id']} {epic['title']} — {export.progress_text(epic['progress'])}"
        )
        if self._ready_only and self._view == _TABLE_PANE:
            title += "  · ready only"
        # Text, not str: Label and DataTable parse a str as markup, and a
        # title may well contain "[...]".
        head.update(Text(title))
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
        ready takes the theme's success role.
        """
        return self._role("success", p.SUCCESS), self.board.chip_colours().blocked

    def _role(self, role: str, fallback: str) -> str:
        """The active theme's *role* colour, or *fallback* when it isn't hex.

        Checked per role: an ANSI theme names colours (``ansi_green``) that are
        valid CSS but not Rich styles, and building a ``Style`` from one raises.
        """
        value = getattr(self.app.current_theme, role, None) or ""
        return value if value.startswith("#") else fallback

    # -- dependency diagram --------------------------------------------------

    def _fill_diagram(self, epic: dict, members: list[dict], ready: set[int]) -> None:
        """Build the epic's diagram from its ``blocks`` graph.

        Drawn: members on either end of a link, plus the one-hop stubs outside
        the epic. Members with no link - done ones included, and any whose
        only link was to an archived card - are counted under the diagram.
        Member state comes from *members* (``dependency_graph`` carries none).
        """
        graph = service.dependency_graph(self.board.conn, epic_id=epic["id"])
        if not members:
            self._set_diagram(None, empty_state("No members yet."))
            return
        if not graph["edges"]:
            self._set_diagram(
                None,
                empty_state(
                    "No links in this epic yet — press l on a card to add one."
                ),
            )
            return
        linked = {e["from"] for e in graph["edges"]} | {e["to"] for e in graph["edges"]}
        by_id = {c["id"]: c for c in members}
        nodes: dict[Hashable, dict[str, Any]] = {}
        for node in graph["nodes"]:
            if node["id"] not in linked:
                continue
            card = by_id.get(node["id"])
            style = (
                Style(dim=True)
                if node["stub"] or card is None
                else self._node_style(card, ready)
            )
            nodes[node["id"]] = {
                "title": node["title"],
                "project": node["project"],
                "stub": node["stub"],
                "$content-renderer": _node_content,
                "$style": style,
                "$content-style": style,
                "$margin": 1,
            }
        edges = [
            (
                edge["from"],
                edge["to"],
                {
                    "$end-arrow-tip": ArrowTip.ARROW,
                    "$start-arrow-tip": ArrowTip.NONE,
                    "$edge-routing-mode": EdgeRoutingMode.ORTHOGONAL,
                    "$edge-segment-drawing-mode": EdgeSegmentDrawingMode.BOX,
                },
            )
            for edge in graph["edges"]
        ]
        unlinked = len(set(by_id) - linked)
        note = (
            f"{unlinked} member{'s' if unlinked != 1 else ''} without links"
            if unlinked
            else ""
        )
        self._set_diagram((nodes, edges), note)

    def _node_style(self, card: dict, ready: set[int]) -> Style:
        """A member node's colour: done, then held up, then ready, then status."""
        if card["status"] == DONE:
            return Style(dim=True)
        if _is_blocked(card):
            return Style(color=self.board.chip_colours().blocked)
        if card["id"] in ready:
            return Style(color=self._role("success", p.SUCCESS))
        if card["status"] in (IN_PROGRESS, IN_REVIEW):
            return Style(color=self._role("primary", p.PRIMARY))
        return Style(color=self._role("foreground", p.FOREGROUND))

    def _set_diagram(self, data: tuple[dict, list] | None, note: str) -> None:
        """Hold the diagram to draw (``None`` for none) and the line under it."""
        self._graph_data = data
        self.query_one("#deps", ThemedGraphView).display = data is not None
        label = self.query_one("#deps-note", Label)
        label.update(Text(note))
        label.display = bool(note)
        self._graph_applied = False
        if self._view == _GRAPH_PANE:
            self._apply_graph()

    def _apply_graph(self) -> None:
        """Push the held diagram into the graph view, once it can take it.

        ``set_graph()`` against a hidden or zero-sized widget builds nothing,
        so until the view has its real size this waits: the view's
        :class:`~mait_code.tui.graph.ThemedGraphView.Sized` brings it back.
        """
        if self._graph_data is None or self._graph_applied:
            return
        view = self.query_one("#deps", ThemedGraphView)
        if view.size.width and view.size.height:
            view.set_graph(*self._graph_data)
            self._graph_applied = True

    def on_themed_graph_view_sized(self, event: ThemedGraphView.Sized) -> None:
        if self._view == _GRAPH_PANE:
            self._apply_graph()

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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Gate ``g`` to the view it leaves, and ready-only to the table."""
        if action == "show_graph":
            return self._view == _TABLE_PANE
        if action == "show_table":
            return self._view == _GRAPH_PANE
        if action == "toggle_ready":
            return self._view == _TABLE_PANE
        return True

    def action_show_graph(self) -> None:
        self._switch(_GRAPH_PANE)
        # The table's cursor is out of sight; arrow through epics instead.
        self.query_one("#epics", OptionList).focus()
        # After this layout pass, so a size left from before the switch isn't
        # mistaken for the shown view's; Sized covers a view still unsized.
        self.call_after_refresh(self._apply_graph)

    def action_show_table(self) -> None:
        self._switch(_TABLE_PANE)

    def _switch(self, pane: str) -> None:
        self._view = pane
        self.query_one("#members-switcher", ContentSwitcher).current = pane
        self.refresh_bindings()
        self.refresh_data()  # the head line says "ready only" only on the table

    def action_focus_epics(self) -> None:
        self.query_one("#epics", OptionList).focus()

    def action_focus_members(self) -> None:
        """The right arrow key focuses the right pane: the table, or the diagram (whose arrow
        keys then scroll a graph bigger than the pane)."""
        if self._view == _GRAPH_PANE:
            self.query_one("#deps", ThemedGraphView).focus()
        else:
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
