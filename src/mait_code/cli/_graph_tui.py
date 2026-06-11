"""Interactive ``mait-code graph`` &mdash; the knowledge-graph explorer.

An ego-centric, read-only explorer over the entity/relationship graph the
observation pipeline accumulates in the memory store. A filterable entity
list on the left (mention-ordered, noise hidden by default), the selected
entity's 1-hop neighbourhood in the centre &mdash; rendered either as a netext
:class:`~netext.textual_widget.widget.GraphView` node-link diagram or as a
flat, glyph-annotated relationship table (``t`` swaps) &mdash; and a detail pane
on the right showing entity metadata and each relationship's ``context``
text, the richest field the graph holds.

Design constraints from prototyping: depth 1 only; edge labels render only
for small neighbourhoods (the renderer has no label collision avoidance);
the force-directed layout is interactive-only &mdash; it is unseeded, so the
deterministic Sugiyama engine backs the snapshot tests instead.

The app holds a single connection for its lifetime, mirroring the memory
browser. Requires a TTY; the bare ``graph`` command only routes here when
attached to one, falling back to a text summary otherwise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Hashable

from netext import ArrowTip, AutoZoom, EdgeRoutingMode, EdgeSegmentDrawingMode
from netext.layout_engines import ForceDirectedLayout, LayoutDirection, SugiyamaLayout
from netext.textual_widget.widget import GraphView
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.strip import Strip
from textual.timer import Timer
from textual.widgets import (
    ContentSwitcher,
    DataTable,
    Footer,
    Input,
    Label,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option

from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.entities import get_ego_graph, list_graph_entities
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.banner import BrandBanner
from mait_code.tui.brand import empty_state

__all__ = ["GraphApp", "run_graph_tui"]


def run_graph_tui(db_path: Path | None = None) -> None:
    """Launch the Textual graph explorer (blocks until the user quits)."""
    GraphApp(db_path=db_path).run()


#: One glyph per entity type, leading every list row and table cell so the
#: type reads at a glance even where colour is ambiguous.
_TYPE_GLYPHS: dict[str, str] = {
    "person": "●",
    "project": "◆",
    "tool": "▲",
    "service": "■",
    "concept": "○",
    "org": "★",
    "unknown": "·",
}

#: Edge labels render only at or below this neighbourhood size: netext draws
#: them with no collision avoidance, so at hub density they overdraw each
#: other and the node boxes.
_LABEL_LIMIT = 15

#: Context strings are clipped to this width in table cells; the detail pane
#: shows them in full.
_CONTEXT_WIDTH = 70

#: Zoom keys step by this much, and never below the floor.
_ZOOM_STEP = 0.25
_ZOOM_FLOOR = 0.25


#: How long the list cursor must rest on an entity before the centre pane
#: re-lays-out around it. Hub neighbourhoods take ~0.3-0.5 s to lay out, so
#: re-centring on every arrow press would make scrolling the list crawl.
_RECENTRE_DELAY = 0.3


def _clip(text: str, width: int = _CONTEXT_WIDTH) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if len(first_line) > width:
        return first_line[: width - 1] + "…"
    return first_line


class _ThemedGraphView(GraphView):
    """A GraphView whose canvas wears the theme background.

    netext emits its strips (and blank filler rows) with no background
    colour, and rendered lines bypass the CSS compositor — unstyled cells
    fall through to the *terminal's* default background instead of the
    theme's, leaving mismatched rectangles around the rendered graph.
    Laying the widget's resolved background under every line closes the gap.
    """

    def render_line(self, y: int) -> Strip:
        base = Style(bgcolor=self.rich_style.bgcolor)
        return super().render_line(y).apply_style(base)


class GraphApp(MaitApp):
    """Ego-centric, read-only explorer over the entity knowledge graph."""

    TITLE = "mait-code graph"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_graph.tcss"]

    BINDINGS = [
        ("slash", "focus_filter", "Filter"),
        # One key, two gated bindings: check_action() enables exactly the one
        # that leaves the current view, so the footer reads as the destination.
        ("t", "show_table", "Table"),
        ("t", "show_graph", "Graph"),
        ("a", "toggle_all", "All/Connected"),
        ("r", "reload", "Reload"),
        ("escape", "escape", "Back"),
        ("plus,equals_sign", "zoom(1)", "Zoom in"),
        ("minus", "zoom(-1)", "Zoom out"),
        Binding("1", "focus_list", "List", show=False),
        Binding("2", "focus_centre", "Centre", show=False),
        Binding("3", "focus_detail", "Detail", show=False),
    ]

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        deterministic: bool = False,
    ) -> None:
        """Args:
        db_path: Memory database path; ``None`` resolves the configured one.
        deterministic: Lay the graph out with the deterministic Sugiyama
            engine at a fixed zoom instead of the (unseeded) force-directed
            engine with auto-fit. For snapshot tests.
        """
        super().__init__()
        self._conn = get_connection(db_path)  # one connection for the app's life
        self._deterministic = deterministic
        self._entities: list[dict] = []
        self._ego: dict | None = None
        self._query = ""
        self._show_all = False  # False → hide degree-0 / single-mention noise
        self._view = "graph"
        # The graph the GraphView should be showing. netext drops set_graph()
        # calls made while the widget is unsized (pre-layout, or hidden behind
        # the ContentSwitcher), so the app re-applies this whenever the view
        # gains real dimensions.
        self._graph_data: tuple[dict, list] | None = None
        self._graph_applied = False
        self._recentre_timer: Timer | None = None

    def on_unmount(self) -> None:
        super().on_unmount()  # persists the active theme (MaitApp)
        self._conn.close()

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Graph")
        with Horizontal(id="body"):
            with Vertical(id="nav"):
                yield Input(placeholder="filter entities…", id="filter")
                yield OptionList(id="entities")
            with ContentSwitcher(initial="graph", id="centre"):
                yield _ThemedGraphView(
                    id="graph",
                    zoom=1.0 if self._deterministic else AutoZoom.FIT,
                    layout_engine=(
                        SugiyamaLayout(LayoutDirection.TOP_DOWN)
                        if self._deterministic
                        else ForceDirectedLayout()
                    ),
                )
                yield DataTable(id="table", zebra_stripes=True, cursor_type="row")
            yield VerticalScroll(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("entity", "relationship", "entity", "context")
        self._load_entities()
        self._rebuild_list()
        self.query_one("#entities", OptionList).focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "show_table":
            return self._view == "graph"
        if action == "show_graph":
            return self._view == "table"
        return True

    # -- theme-aware styling ---------------------------------------------------

    def _type_styles(self) -> dict[str, Style]:
        """Entity-type colours drawn from the active theme's roles.

        Resolved per render (not cached): the palette follows the user
        through Ctrl+P theme switches on the next rebuild.
        """
        theme = self.current_theme
        return {
            "person": Style(color=theme.accent, bold=True),
            "project": Style(color=theme.primary, bold=True),
            "tool": Style(color=theme.success),
            "service": Style(color=theme.warning),
            "concept": Style(color=theme.foreground),
            "org": Style(color=theme.error),
            # No Rich-safe "muted" role on the theme; dimmed foreground reads
            # as the de-emphasis the unknown type wants.
            "unknown": Style(color=theme.foreground, dim=True),
        }

    def _entity_text(
        self, name: str, entity_type: str, *, centre: bool = False
    ) -> Text:
        """Glyph + name for a list row, table cell, or detail title.

        Only the glyph carries the type colour: rows render on cursor bars
        whose background is the same theme role, so a coloured *name* can
        vanish into the highlight. The glyph keeps the signal either way.
        """
        styles = self._type_styles()
        style = styles.get(entity_type, styles["unknown"])
        text = Text(no_wrap=True)
        text.append(f"{_TYPE_GLYPHS.get(entity_type, '·')} ", style=style)
        text.append(name, style=Style(underline=True) if centre else "")
        return text

    # -- data --------------------------------------------------------------------

    def _load_entities(self) -> None:
        """(Re)read the entity list under the active noise filter."""
        self._entities = list_graph_entities(
            self._conn,
            self._query,
            min_mentions=1 if self._show_all else 2,
            require_relationship=not self._show_all,
        )

    def _centre_name(self) -> str | None:
        return self._ego["centre"]["name"] if self._ego else None

    # -- entity list ---------------------------------------------------------------

    def _rebuild_list(self) -> None:
        """Re-populate the entity list; landing re-centres on the first row."""
        options = self.query_one("#entities", OptionList)
        options.clear_options()
        for entity in self._entities:
            label = self._entity_text(entity["name"], entity["entity_type"])
            label.append(f"  {entity['mention_count']}", style="dim")
            options.add_option(Option(label, id=entity["name"]))
        self._update_subtitle()
        if self._entities:
            options.highlighted = 0
            self._set_centre(self._entities[0]["name"])
        else:
            self._show_empty()

    def _update_subtitle(self) -> None:
        text = f"Graph — {len(self._entities)} entities"
        if self._ego:
            text += f" · {self._centre_name()} ({len(self._ego['relationships'])})"
        if self._query:
            text += f" · filter {self._query!r}"
        if self._show_all:
            text += " · all"
        self.query_one(BrandBanner).set_subtitle(text)

    # -- centre (graph + table) ----------------------------------------------------

    def _set_centre(self, name: str) -> None:
        """Load *name*'s ego graph and refresh both centre views."""
        ego = get_ego_graph(self._conn, name)
        if ego is None:
            self.notify(f"Entity {name!r} not found", title="Graph", severity="warning")
            return
        self._ego = ego
        self._graph_data = self._netext_graph(ego)
        self._apply_graph()
        self._populate_table(ego)
        self._show_entity_detail(ego["centre"])
        self._update_subtitle()

    def _apply_graph(self) -> None:
        """Push the held graph into the GraphView, once it can take it.

        ``set_graph()`` against a zero-sized widget builds nothing and a later
        resize only re-measures the old (empty) graph, so calls made before
        first layout or while the table hides the view must be retried —
        ``call_after_refresh`` lands after the next layout pass, when the
        widget has its real size.
        """
        if self._graph_data is None:
            return
        view = self.query_one(GraphView)
        if view.size.width and view.size.height:
            view.set_graph(*self._graph_data)
            self._graph_applied = True
        else:
            self._graph_applied = False
            if self._view == "graph":
                self.call_after_refresh(self._apply_graph)

    def _netext_graph(
        self, ego: dict
    ) -> tuple[dict[Hashable, dict[str, Any]], list[tuple]]:
        """The ego dict as netext node/edge data, styled from the theme."""
        styles = self._type_styles()
        centre = ego["centre"]["name"]
        show_labels = len(ego["entities"]) <= _LABEL_LIMIT
        theme = self.current_theme

        # The centre node inverts: theme background text on the foreground
        # colour. Both $style and $content-style must invert — leaving the
        # content on the type colour makes foreground-coloured types
        # (concept, unknown) invisible against the inverted box.
        inverted = Style(color=theme.background, bgcolor=theme.foreground, bold=True)
        nodes: dict[Hashable, dict[str, Any]] = {}
        for entity in ego["entities"]:
            style = styles.get(entity["entity_type"], styles["unknown"])
            is_centre = entity["name"] == centre
            nodes[entity["name"]] = {
                "$style": inverted if is_centre else style,
                "$content-style": inverted if is_centre else style,
                "$margin": 1,
            }
        edges = [
            (
                rel["source_name"],
                rel["target_name"],
                {
                    **({"$label": rel["relationship_type"]} if show_labels else {}),
                    "$end-arrow-tip": ArrowTip.ARROW,
                    "$start-arrow-tip": ArrowTip.NONE,
                    "$edge-routing-mode": EdgeRoutingMode.ORTHOGONAL,
                    "$edge-segment-drawing-mode": EdgeSegmentDrawingMode.BOX,
                },
            )
            for rel in ego["relationships"]
        ]
        return nodes, edges

    def _populate_table(self, ego: dict) -> None:
        """One table row per relationship, keyed by its index in the ego dict."""
        types = {e["name"]: e["entity_type"] for e in ego["entities"]}
        centre = ego["centre"]["name"]
        table = self.query_one(DataTable)
        table.clear()
        for index, rel in enumerate(ego["relationships"]):
            table.add_row(
                self._entity_text(
                    rel["source_name"],
                    types.get(rel["source_name"], "unknown"),
                    centre=rel["source_name"] == centre,
                ),
                Text(f"─{rel['relationship_type']}─▶", style="dim"),
                self._entity_text(
                    rel["target_name"],
                    types.get(rel["target_name"], "unknown"),
                    centre=rel["target_name"] == centre,
                ),
                Text(_clip(rel["context"]), style="dim italic"),
                key=str(index),
            )

    # -- detail ---------------------------------------------------------------------

    def _show_entity_detail(self, entity: dict) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        detail.remove_children()
        degree = (
            len(self._ego["relationships"])
            if self._ego and self._ego["centre"]["id"] == entity["id"]
            else entity.get("degree")
        )
        meta = f"{entity['entity_type']} · {entity['mention_count']} mentions"
        if degree is not None:
            meta += f" · {degree} link{'s' if degree != 1 else ''}"
        detail.mount(
            Static(
                self._entity_text(entity["name"], entity["entity_type"]),
                classes="title",
            ),
            Label(meta, classes="help"),
            # Two lines, not one: the detail pane is the narrow share and a
            # combined seen-window line clips on sane splits.
            Label(f"first seen {str(entity['first_seen'])[:10]}", classes="help"),
            Label(f"last seen {str(entity['last_seen'])[:10]}", classes="help"),
        )

    def _show_relationship_detail(self, rel: dict) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        detail.remove_children()
        types = (
            {e["name"]: e["entity_type"] for e in self._ego["entities"]}
            if self._ego
            else {}
        )
        title = self._entity_text(
            rel["source_name"], types.get(rel["source_name"], "unknown")
        )
        title.append(f" ─{rel['relationship_type']}─▶ ", style="dim")
        title.append_text(
            self._entity_text(
                rel["target_name"], types.get(rel["target_name"], "unknown")
            )
        )
        detail.mount(
            Static(title, classes="title"),
            Label(f"first seen {str(rel['first_seen'])[:10]}", classes="help"),
            Label(f"last seen {str(rel['last_seen'])[:10]}", classes="help"),
            Static(rel["context"], classes="context"),
        )

    def _show_empty(self) -> None:
        self._ego = None
        self._graph_data = ({}, [])
        self._apply_graph()
        self.query_one(DataTable).clear()
        detail = self.query_one("#detail", VerticalScroll)
        detail.remove_children()
        if self._query:
            message = f"No entities matching {self._query!r}."
        elif not self._show_all:
            message = "No connected entities yet — press a to show everything."
        else:
            message = "No entities yet — the graph grows as sessions are observed."
        detail.mount(Static(empty_state(message), classes="help"))
        self._update_subtitle()

    # -- events -----------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        self._query = event.value.strip()
        self._load_entities()
        self._rebuild_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter in the filter lands on the results, ready to arrow through.
        self.query_one("#entities", OptionList).focus()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        # Highlight previews the entity at once and re-centres the whole
        # surface after the cursor rests — debounced, because re-laying-out
        # a hub neighbourhood on every arrow press would make the list crawl.
        # Enter (OptionSelected) still re-centres immediately.
        index = event.option_index
        if not (0 <= index < len(self._entities)):
            return
        entity = self._entities[index]
        self._show_entity_detail(entity)
        if self._recentre_timer is not None:
            self._recentre_timer.stop()
            self._recentre_timer = None
        name = entity["name"]
        if name != self._centre_name():
            self._recentre_timer = self.set_timer(
                _RECENTRE_DELAY, lambda: self._recentre_if_still(name)
            )

    def _recentre_if_still(self, name: str) -> None:
        """The debounce target: re-centre unless the cursor has moved on."""
        self._recentre_timer = None
        if name != self._centre_name():
            self._set_centre(name)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is not None:
            self._set_centre(event.option.id)

    def on_graph_view_element_click(self, event: GraphView.ElementClick) -> None:
        ref = event.element_reference
        if ref.type == "node":
            name = str(ref.ref)
            if name != self._centre_name():
                self._set_centre(name)
        elif ref.type == "edge" and self._ego:
            # netext keys edges by node pair (typed Hashable; a 2-tuple here).
            if not (isinstance(ref.ref, tuple) and len(ref.ref) == 2):
                return
            endpoints = {str(end) for end in ref.ref}
            for rel in self._ego["relationships"]:
                if {rel["source_name"], rel["target_name"]} == endpoints:
                    self._show_relationship_detail(rel)
                    break

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # The hidden table also fires this while being (re)populated from a
        # graph-view re-centre; reacting then would overwrite the freshly
        # rendered entity detail.
        if self._view != "table":
            return
        rel = self._rel_for_row(event.row_key.value)
        if rel is not None:
            self._show_relationship_detail(rel)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Enter on a row walks the graph: re-centre on the row's other end.
        rel = self._rel_for_row(event.row_key.value)
        if rel is None:
            return
        centre = self._centre_name()
        other = (
            rel["target_name"] if rel["source_name"] == centre else rel["source_name"]
        )
        self._set_centre(other)

    def _rel_for_row(self, key: str | None) -> dict | None:
        if key is None or self._ego is None:
            return None
        index = int(key)
        rels = self._ego["relationships"]
        return rels[index] if 0 <= index < len(rels) else None

    # -- actions ------------------------------------------------------------------------

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_focus_list(self) -> None:
        self.query_one("#entities", OptionList).focus()

    def action_focus_centre(self) -> None:
        widget_id = "#table" if self._view == "table" else "#graph"
        self.query_one(widget_id).focus()

    def action_focus_detail(self) -> None:
        self.query_one("#detail", VerticalScroll).focus()

    def action_escape(self) -> None:
        """Escape steps back to the list; pressed on the list itself, it quits."""
        if self.query_one("#entities", OptionList).has_focus:
            self.exit()
        else:
            self.action_focus_list()

    def action_show_table(self) -> None:
        self._view = "table"
        self.query_one("#centre", ContentSwitcher).current = "table"
        self.refresh_bindings()  # the t binding swaps Table ⇄ Graph

    def action_show_graph(self) -> None:
        self._view = "graph"
        self.query_one("#centre", ContentSwitcher).current = "graph"
        if not self._graph_applied:
            # A re-centre issued from the table view hit a hidden, zero-sized
            # GraphView; apply it now the view is coming back.
            self.call_after_refresh(self._apply_graph)
        self.refresh_bindings()

    def action_toggle_all(self) -> None:
        """Toggle the noise filter: connected-and-mentioned only ⇄ everything."""
        self._show_all = not self._show_all
        self._load_entities()
        self._rebuild_list()
        self.action_focus_list()

    def action_zoom(self, direction: int) -> None:
        view = self.query_one(GraphView)
        view.zoom = max(
            _ZOOM_FLOOR, self._effective_zoom(view) + direction * _ZOOM_STEP
        )

    def _effective_zoom(self, view: GraphView) -> float:
        """The numeric zoom factor, even while ``zoom`` holds an AutoZoom enum.

        netext exposes no public accessor for the factor auto-fit resolved
        to, so this falls back to the console graph's internal computation
        (upstream issue material).
        """
        if isinstance(view.zoom, (int, float)):
            return float(view.zoom)
        if view._console_graph is not None:  # noqa: SLF001 — no public accessor
            zoom_x, _zoom_y = view._console_graph._compute_current_zoom()
            return zoom_x
        return 1.0

    def action_reload(self) -> None:
        """Re-read the graph — picks up entities observed since launch."""
        self._load_entities()
        self._rebuild_list()
        self.notify("Graph reloaded", title="Graph")

    def get_system_commands(self, screen: Screen):
        """Expose the explorer's actions in the Ctrl+P command palette."""
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Filter", "Jump to the filter input", self.action_focus_filter
        )
        if self._view == "graph":
            yield SystemCommand(
                "Table view", "Flat relationship table", self.action_show_table
            )
        else:
            yield SystemCommand(
                "Graph view", "Node-link neighbourhood", self.action_show_graph
            )
        yield SystemCommand(
            "Show everything",
            "Toggle the noise filter (single-mention and orphan entities)",
            self.action_toggle_all,
        )
        yield SystemCommand("Reload", "Re-read the graph", self.action_reload)
