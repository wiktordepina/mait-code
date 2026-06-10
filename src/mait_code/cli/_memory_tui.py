"""Interactive ``mait-code memory`` &mdash; a read-only Textual memory browser.

A full-screen master&ndash;detail browser over the memory store: a filter input
and a tree of memories grouped by entry type on the left, a detail pane
rendering the selected memory's body (as markdown &mdash; plain text is a subset)
plus its metadata on the right. Pure presentation over the same code paths as
``mc-tool-memory`` (:func:`~mait_code.tools.memory.search.list_entries`); the
browser performs no mutations &mdash; nothing here writes, edits, or deletes.

``n`` switches to a second, equally read-only view over **Claude Code's
native auto memory** (:mod:`mait_code.tools.memory.native`): every project's
``~/.claude/projects/<slug>/memory/`` files, grouped by project, regardless of
where the browser was launched. Both views filter live with ``/`` and narrow
to one project with ``p`` &mdash; the two curated memory layers, one cockpit.

The app holds a single connection for its lifetime (opened in ``__init__``,
closed on unmount), mirroring the board. Requires a TTY; the bare ``memory``
command only routes here when attached to one, falling back to a read-only
grouped summary otherwise.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Markdown, Static, Tree
from textual.widgets.tree import TreeNode

from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.native import list_native_memories
from mait_code.tools.memory.search import list_entries, list_projects
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.banner import BrandBanner
from mait_code.tui.brand import empty_state
from mait_code.tui.filters import ProjectFilterScreen
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


def _clip(line: str) -> str:
    """Clip a leaf's text to :data:`_LEAF_WIDTH` with an ellipsis."""
    if len(line) > _LEAF_WIDTH:
        return line[: _LEAF_WIDTH - 1] + "…"
    return line


def _leaf_label(entry: dict) -> Text:
    """One tree row for a memory: dimmed date + the first line of its content."""
    first_line = entry["content"].strip().splitlines()[0] if entry["content"] else ""
    label = Text(no_wrap=True)
    # The gap rides inside the dim run (not as a separate unstyled segment), so
    # renderers that trim leading run whitespace can't swallow it.
    label.append(f"{str(entry['created_at'])[:10]}  ", style="dim")
    label.append(_clip(first_line))
    return label


def _native_leaf_label(file: dict) -> Text:
    """One tree row for a native memory file: dimmed modified date + name."""
    label = Text(no_wrap=True)
    label.append(f"{file['modified']}  ", style="dim")
    label.append(_clip(file["name"]))
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
    """Master–detail, read-only browser over both curated memory layers."""

    TITLE = "mait-code memory"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_memory.tcss"]

    BINDINGS = [
        ("slash", "focus_filter", "Filter"),
        # One key, two gated bindings: check_action() enables exactly the one
        # that leaves the current view, so the footer reads as the destination.
        Binding("n", "show_native", "Native"),
        Binding("n", "show_store", "Store"),
        ("p", "filter_project", "Project"),
        ("escape", "escape", "Back"),
        ("r", "reload", "Reload"),
        Binding("1", "focus_list", "List", show=False),
        Binding("2", "focus_detail", "Detail", show=False),
    ]

    def __init__(
        self, db_path: Path | None = None, native_dir: Path | None = None
    ) -> None:
        super().__init__()
        self._conn = get_connection(db_path)  # one connection for the app's life
        self._native_dir = native_dir  # None → Claude Code's real projects dir
        self._view = "store"
        self._entries: list[dict] = []
        self._native_projects: list[dict] = []
        self._native_text_cache: dict[Path, str] = {}
        self._query = ""
        self._project: str | None = None  # store-view project filter
        self._native_project: str | None = None  # native-view project filter

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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "show_native":
            return self._view == "store"
        if action == "show_store":
            return self._view == "native"
        return True

    # -- data ----------------------------------------------------------------

    def _load_entries(self) -> None:
        """(Re)read the store — everything, unless narrowed to one project."""
        self._entries = list_entries(
            self._conn, limit=_FETCH_LIMIT, project=self._project
        )

    def _load_native(self) -> None:
        """(Re)scan every project's native memory files."""
        self._native_projects = list_native_memories(self._native_dir)

    def _native_text(self, path: Path) -> str:
        """A native file's content, cached until reload (the live filter
        re-reads the visible set on every keystroke otherwise)."""
        cached = self._native_text_cache.get(path)
        if cached is None:
            try:
                cached = path.read_text(encoding="utf-8")
            except OSError:
                cached = ""
            self._native_text_cache[path] = cached
        return cached

    def _filtered(self) -> list[dict]:
        """The entries the active filter leaves visible (all, when no filter)."""
        if not self._query:
            return self._entries
        needle = self._query.casefold()
        return [e for e in self._entries if needle in e["content"].casefold()]

    def _filtered_native(self) -> list[dict]:
        """The native projects/files the active filters leave visible.

        The project filter keeps whole projects; the text filter matches a
        file's name or content and drops projects it empties.
        """
        projects = self._native_projects
        if self._native_project:
            projects = [p for p in projects if p["label"] == self._native_project]
        if not self._query:
            return projects
        needle = self._query.casefold()
        narrowed = []
        for project in projects:
            files = [
                f
                for f in project["files"]
                if needle in f["name"].casefold()
                or needle in self._native_text(f["path"]).casefold()
            ]
            if files:
                narrowed.append({**project, "files": files})
        return narrowed

    # -- tree ----------------------------------------------------------------

    def _rebuild_tree(self) -> None:
        if self._view == "native":
            self._rebuild_native_tree()
        else:
            self._rebuild_store_tree()

    def _rebuild_store_tree(self) -> None:
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
        self._land_cursor(tree, first_leaf, self._show_detail)

    def _rebuild_native_tree(self) -> None:
        """Re-populate the tree from the filtered native projects.

        Same expansion policy as the store view: first project open, the rest
        collapsed behind their file counts; everything expands under a filter.
        """
        tree: Tree[dict] = self.query_one("#list", Tree)
        tree.root.remove_children()

        visible = self._filtered_native()
        filtering = bool(self._query)
        first_leaf: TreeNode[dict] | None = None
        for index, project in enumerate(visible):
            group = tree.root.add(
                f"{project['label']} ({len(project['files'])})",
                data=project,
                expand=filtering or index == 0,
            )
            for file in project["files"]:
                # Leaves carry their project's label so the detail pane can
                # show which project a file belongs to without re-deriving it.
                leaf = group.add_leaf(
                    _native_leaf_label(file),
                    data={**file, "project": project["label"]},
                )
                if first_leaf is None:
                    first_leaf = leaf

        self._update_native_subtitle(visible)
        self._land_cursor(tree, first_leaf, self._show_native_file_detail)

    def _land_cursor(self, tree: Tree[dict], first_leaf, show) -> None:
        if first_leaf is not None:
            # Deferred until after the first refresh: the tree's visible-line
            # map (which move_cursor indexes into) isn't built until then. The
            # detail render is explicit, not left to the highlight event — when
            # a rebuild lands the cursor on the same line index, Tree emits no
            # NodeHighlighted and the pane would go stale.
            self.call_after_refresh(tree.move_cursor, first_leaf)
            self.call_after_refresh(show, first_leaf.data)
        else:
            self.call_after_refresh(self._show_empty)

    def _update_subtitle(self, shown: int) -> None:
        # The masthead carries the view name and its live state (the stock header
        # the count used to live in is gone). Filtering shows the match count;
        # otherwise the plain total beside the "Memory" name.
        total = len(self._entries)
        text = f"Memory — {total}"
        if self._project:
            text += f" · {self._project}"
        if self._query:
            text = f"Memory — {shown}/{total} match"
        self.query_one(BrandBanner).set_subtitle(text)

    def _update_native_subtitle(self, visible: list[dict]) -> None:
        # The native view's masthead leads with the layer name, then the same
        # live state the store view carries: totals, the project narrowing,
        # the match count while a text filter is active.
        total = sum(len(p["files"]) for p in self._native_projects)
        projects = len(self._native_projects)
        text = (
            f"Memory — native · {total} file{'s' if total != 1 else ''}"
            f" · {projects} project{'s' if projects != 1 else ''}"
        )
        if self._native_project:
            text += f" · {self._native_project}"
        if self._query:
            shown = sum(len(p["files"]) for p in visible)
            text += f" · {shown}/{total} match"
        self.query_one(BrandBanner).set_subtitle(text)

    # -- detail --------------------------------------------------------------

    async def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = event.node.data
        if self._view == "native":
            # Project nodes carry their project dict (it has "files"); leaves
            # carry a file dict augmented with the project label.
            if data is None:
                return
            if "files" in data:
                await self._show_native_project_detail(data)
            else:
                await self._show_native_file_detail(data)
        else:
            # Leaves carry their entry dict as node data; group nodes carry
            # None and get a read-only summary instead of a body.
            if data is None:
                await self._show_group_detail(event.node)
            else:
                await self._show_detail(data)

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

    async def _show_native_file_detail(self, file: dict) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        content = self._native_text(file["path"])
        await detail.mount(
            Label(file["name"], classes="title"),
            Label(
                f"{file['project']} · modified {file['modified']} · native",
                classes="help",
            ),
            Markdown(
                content or "*This file is empty or could not be read.*",
                parser_factory=md_parser,
                open_links=False,
            ),
        )

    async def _show_native_project_detail(self, project: dict) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        count = len(project["files"])
        await detail.mount(
            Label(project["label"], classes="title"),
            Label(
                f"{count} file{'s' if count != 1 else ''} — "
                "expand and pick one to read.",
                classes="help",
            ),
            # The resolved path when the de-munge found one; the raw slug
            # otherwise — either way, where this memory actually lives.
            Label(str(project["memory_dir"]), classes="help"),
        )

    async def _show_empty(self) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        if self._view == "native":
            if self._query:
                message = f"Nothing in native memory matching {self._query!r}."
            elif self._native_project:
                message = f"No native memory for {self._native_project} yet."
            else:
                message = "No native memory yet — Claude Code writes it as you work."
        elif self._query:
            message = f"I don't remember anything matching {self._query!r}."
        elif self._project:
            message = f"I don't remember anything about {self._project} yet."
        else:
            message = "Nothing remembered yet — we're just getting started."
        await detail.mount(Static(empty_state(message), classes="help"))

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

    def action_show_native(self) -> None:
        """Switch to the native auto-memory view (fresh scan on entry)."""
        self._view = "native"
        self._load_native()
        self.query_one("#filter", Input).placeholder = "filter native memory…"
        self._rebuild_tree()
        self.refresh_bindings()  # the n binding swaps Native ⇄ Store
        self.action_focus_list()

    def action_show_store(self) -> None:
        """Switch back to the mait-code store view."""
        self._view = "store"
        self.query_one("#filter", Input).placeholder = "filter memories…"
        self._rebuild_tree()
        self.refresh_bindings()
        self.action_focus_list()

    @work
    async def action_filter_project(self) -> None:
        # Each view narrows independently: the store by its entries' project
        # scope (judged against the live store, so a project remembered this
        # session shows), the native view by its scanned project labels.
        if self._view == "native":
            projects = [p["label"] for p in self._native_projects]
            current = self._native_project
        else:
            projects = list_projects(self._conn)
            current = self._project
        result = await self.push_screen_wait(ProjectFilterScreen(projects, current))
        if result is None:
            return  # escape/cancel — leave the active filter as-is
        # A project name filters to it; the ALL_PROJECTS sentinel clears it.
        choice = result if isinstance(result, str) else None
        if self._view == "native":
            self._native_project = choice
        else:
            self._project = choice
            self._load_entries()
        self._rebuild_tree()
        self.action_focus_list()

    def action_reload(self) -> None:
        """Re-read the active layer — picks up memories written since launch."""
        if self._view == "native":
            self._native_text_cache.clear()
            self._load_native()
            self._rebuild_tree()
            self.notify("Native memory rescanned", title="Memory")
        else:
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
            "Filter by project", "Narrow to one project", self.action_filter_project
        )
        if self._view == "store":
            yield SystemCommand(
                "Native memory",
                "Browse Claude Code's per-project auto memory",
                self.action_show_native,
            )
        else:
            yield SystemCommand(
                "Store memory",
                "Back to the mait-code memory store",
                self.action_show_store,
            )
        yield SystemCommand(
            "Focus list", "Jump to the memory tree", self.action_focus_list
        )
        yield SystemCommand("Reload", "Re-read the active layer", self.action_reload)
