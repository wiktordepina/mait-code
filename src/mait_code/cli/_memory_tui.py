"""Interactive ``mait-code memory`` &mdash; a read-only Textual memory browser.

A full-screen master&ndash;detail browser over the memory store: a filter input
and a tree of memories grouped by entry type on the left, a detail pane
rendering the selected memory's body (as markdown &mdash; plain text is a subset)
plus its metadata on the right. Pure presentation over the same code paths as
``mc-tool-memory`` (:func:`~mait_code.tools.memory.search.list_entries`); the
browser performs no mutations &mdash; nothing here writes, edits, or deletes.

The app holds a single connection for its lifetime (opened in ``__init__``,
closed on unmount), mirroring the board. Requires a TTY; the bare ``memory``
command only routes here when attached to one, falling back to a read-only
grouped summary otherwise.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Markdown, Static, Tree
from textual.widgets.tree import TreeNode

from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.search import list_entries
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.banner import BrandBanner
from mait_code.tui.brand import empty_state
from mait_code.tui.markdown import md_parser

__all__ = ["MemoryApp", "run_memory_tui"]


def run_memory_tui(db_path: Path | None = None) -> None:
    """Launch the Textual memory browser (blocks until the user quits)."""
    MemoryApp(db_path=db_path).run()


#: Entry types in display order — the semantic, long-lived kinds first, the
#: episodic ones after. Types the store grows later (or unexpected historical
#: values) still render: they're appended alphabetically after these.
_TYPE_ORDER: tuple[str, ...] = (
    "fact",
    "preference",
    "decision",
    "insight",
    "event",
    "task",
    "relationship",
)

#: Effectively "everything": the browser shows the whole store, so the list
#: query just needs a bound that no real store approaches.
_FETCH_LIMIT = 100_000

#: A leaf renders "<date>  <first content line>"; the line is clipped to this
#: width so the tree never forces a horizontal scroll on a sane split.
_LEAF_WIDTH = 64


def _leaf_label(entry: dict) -> Text:
    """One tree row for a memory: dimmed date + the first line of its content."""
    first_line = entry["content"].strip().splitlines()[0] if entry["content"] else ""
    if len(first_line) > _LEAF_WIDTH:
        first_line = first_line[: _LEAF_WIDTH - 1] + "…"
    label = Text(no_wrap=True)
    # The gap rides inside the dim run (not as a separate unstyled segment), so
    # renderers that trim leading run whitespace can't swallow it.
    label.append(f"{str(entry['created_at'])[:10]}  ", style="dim")
    label.append(first_line)
    return label


def _scope_label(entry: dict) -> str:
    """Format an entry's scope for display, matching ``mc-tool-memory``'s style:
    ``global``, ``<project>``, or ``<project>:<branch>``."""
    scope = entry.get("scope") or "global"
    project = entry.get("project")
    branch = entry.get("branch")
    if scope == "global" or not project:
        return "global"
    if scope == "branch" and branch:
        return f"{project}:{branch}"
    return project


def _group_entries(entries: list[dict]) -> dict[str, list[dict]]:
    """Bucket entries by type, ordered per :data:`_TYPE_ORDER` (unknown types
    appended alphabetically). Entry order within a group is preserved — the
    list query already sorts newest-first."""
    by_type: dict[str, list[dict]] = {}
    for entry in entries:
        by_type.setdefault(entry["entry_type"], []).append(entry)
    known = [t for t in _TYPE_ORDER if t in by_type]
    extra = sorted(t for t in by_type if t not in _TYPE_ORDER)
    return {t: by_type[t] for t in (*known, *extra)}


class MemoryApp(MaitApp):
    """Master–detail, read-only browser over the memory store."""

    TITLE = "mait-code memory"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_memory.tcss"]

    BINDINGS = [
        ("slash", "focus_filter", "Filter"),
        ("escape", "escape", "Back"),
        ("r", "reload", "Reload"),
        Binding("1", "focus_list", "List", show=False),
        Binding("2", "focus_detail", "Detail", show=False),
    ]

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self._conn = get_connection(db_path)  # one connection for the app's life
        self._entries: list[dict] = []
        self._query = ""

    def on_unmount(self) -> None:
        super().on_unmount()  # persists the active theme (MaitApp)
        self._conn.close()

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Memory")
        with Horizontal(id="body"):
            with Vertical(id="nav"):
                yield Input(placeholder="filter memories…", id="filter")
                yield Tree("memories", id="list")
            yield VerticalScroll(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        # Unlike the settings editor, the detail pane here holds no focusable
        # editor widget — the *container* keeps focus so a long body can be
        # scrolled from the keyboard (Tab or `2` to reach it, arrows to read).
        tree: Tree[dict] = self.query_one("#list", Tree)
        tree.show_root = False
        tree.guide_depth = 2
        self._load_entries()
        self._rebuild_tree()
        tree.focus()

    # -- data ----------------------------------------------------------------

    def _load_entries(self) -> None:
        """(Re)read the whole store, unscoped — a browser shows everything."""
        self._entries = list_entries(self._conn, limit=_FETCH_LIMIT)

    def _filtered(self) -> list[dict]:
        """The entries the active filter leaves visible (all, when no filter)."""
        if not self._query:
            return self._entries
        needle = self._query.casefold()
        return [e for e in self._entries if needle in e["content"].casefold()]

    # -- tree ----------------------------------------------------------------

    def _rebuild_tree(self) -> None:
        """Re-populate the tree from the filtered entries.

        Without a filter, the first group opens with the cursor on its newest
        memory so the detail pane shows content on boot; the rest stay
        collapsed behind their counts. With a filter, every group expands —
        the matches are the point.
        """
        tree: Tree[dict] = self.query_one("#list", Tree)
        tree.root.remove_children()

        visible = self._filtered()
        groups = _group_entries(visible)
        filtering = bool(self._query)
        first_leaf: TreeNode[dict] | None = None
        for index, (entry_type, entries) in enumerate(groups.items()):
            group = tree.root.add(
                f"{entry_type} ({len(entries)})",
                expand=filtering or index == 0,
            )
            for entry in entries:
                leaf = group.add_leaf(_leaf_label(entry), data=entry)
                if first_leaf is None:
                    first_leaf = leaf

        self._update_subtitle(len(visible))
        if first_leaf is not None:
            # Deferred until after the first refresh: the tree's visible-line
            # map (which move_cursor indexes into) isn't built until then. The
            # detail render is explicit, not left to the highlight event — when
            # a rebuild lands the cursor on the same line index, Tree emits no
            # NodeHighlighted and the pane would go stale.
            self.call_after_refresh(tree.move_cursor, first_leaf)
            self.call_after_refresh(self._show_detail, first_leaf.data)
        else:
            self.call_after_refresh(self._show_empty)

    def _update_subtitle(self, shown: int) -> None:
        # The masthead carries the view name and its live state (the stock header
        # the count used to live in is gone). Filtering shows the match count;
        # otherwise the plain total beside the "Memory" name.
        total = len(self._entries)
        if self._query:
            text = f"Memory — {shown}/{total} match"
        else:
            text = f"Memory — {total}"
        self.query_one(BrandBanner).set_subtitle(text)

    # -- detail --------------------------------------------------------------

    async def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        # Leaves carry their entry dict as node data; group nodes carry None
        # and get a read-only summary instead of a body.
        entry = event.node.data
        if entry is None:
            await self._show_group_detail(event.node)
        else:
            await self._show_detail(entry)

    async def _show_detail(self, entry: dict) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        meta = (
            f"created {str(entry['created_at'])[:10]}"
            f" · importance {entry['importance']}"
            f" · scope {_scope_label(entry)}"
            f" · {entry['memory_class']}"
        )
        await detail.mount(
            Label(f"#{entry['id']} · {entry['entry_type']}", classes="title"),
            Label(meta, classes="help"),
            # Markdown, not Static: plain text is valid markdown, and stored
            # content that *is* markdown renders properly. md_parser keeps
            # single newlines as line breaks, like the board's card bodies.
            Markdown(entry["content"], parser_factory=md_parser, open_links=False),
        )

    async def _show_group_detail(self, node: TreeNode[dict]) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        count = len(node.children)
        await detail.mount(
            Label(str(node.label), classes="title"),
            Label(
                f"{count} memor{'y' if count == 1 else 'ies'} — "
                "expand and pick one to read.",
                classes="help",
            ),
        )

    async def _show_empty(self) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        message = empty_state(
            f"I don't remember anything matching {self._query!r}."
            if self._query
            else "Nothing remembered yet — we're just getting started."
        )
        await detail.mount(Static(message, classes="help"))

    # -- filtering -----------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        self._query = event.value.strip()
        self._rebuild_tree()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter in the filter lands on the results, ready to arrow through.
        self.query_one("#list", Tree).focus()

    # -- actions ---------------------------------------------------------------

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_focus_list(self) -> None:
        self.query_one("#list", Tree).focus()

    def action_escape(self) -> None:
        """Escape steps back to the list; pressed on the list itself, it quits.

        The hierarchical escape: from the filter or the detail pane it returns
        focus to the tree, and from the tree (nothing left to back out of) it
        exits — so escape always eventually leaves, like ``q``.
        """
        if self.query_one("#list", Tree).has_focus:
            self.exit()
        else:
            self.action_focus_list()

    def action_focus_detail(self) -> None:
        self.query_one("#detail", VerticalScroll).focus()

    def action_reload(self) -> None:
        """Re-read the store — picks up memories written since launch."""
        self._load_entries()
        self._rebuild_tree()
        self.notify("Memory store reloaded", title="Memory")

    def get_system_commands(self, screen: Screen):
        """Expose the browser's actions in the Ctrl+P command palette."""
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Filter", "Jump to the filter input", self.action_focus_filter
        )
        yield SystemCommand(
            "Focus list", "Jump to the memory tree", self.action_focus_list
        )
        yield SystemCommand("Reload", "Re-read the memory store", self.action_reload)
