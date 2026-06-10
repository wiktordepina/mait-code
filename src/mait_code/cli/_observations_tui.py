"""Interactive ``mait-code observations`` &mdash; browse the raw extraction tier.

A full-screen master&ndash;detail browser over the observation backlog: a tree
of observations grouped by capture day on the left (newest day first, each
entry flagged pending or reflected against the reflection watermark), a detail
pane rendering the selected observation's body plus its metadata on the right.
Highlighting a day shows that day's capture batches &mdash; when the observe
hook ran, what triggered it, and how much it extracted &mdash; read from the
daily JSONL logs.

Pure presentation over :mod:`mait_code.tools.memory.observations`; the browser
performs no mutations &mdash; nothing here writes, reflects, or deletes.
``memory.db`` is the source of truth (the watermark is defined over its entry
IDs); the JSONL logs only contribute per-capture metadata.

The app holds a single connection for its lifetime (opened in ``__init__``,
closed on unmount), mirroring the memory browser. Requires a TTY; the bare
``observations`` command only routes here when attached to one, falling back
to a read-only grouped summary otherwise.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Markdown, Static, Tree
from textual import work
from textual.widgets.tree import TreeNode

from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.observations import (
    daily_batches,
    list_observations,
    observation_projects,
)
from mait_code.tui import palette
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.banner import BrandBanner
from mait_code.tui.brand import empty_state
from mait_code.tui.filters import ProjectFilterScreen
from mait_code.tui.markdown import md_parser

__all__ = ["ObservationsApp", "run_observations_tui"]


def run_observations_tui(db_path: Path | None = None) -> None:
    """Launch the Textual observations browser (blocks until the user quits)."""
    ObservationsApp(db_path=db_path).run()


#: A leaf renders "<marker> <type>  <first content line>"; the line is clipped
#: to this width so the tree never forces a horizontal scroll on a sane split.
_LEAF_WIDTH = 56

#: Markers for an observation's standing against the reflection watermark.
_PENDING_MARK = "●"
_REFLECTED_MARK = "✓"


def _scope_label(entry: dict) -> str:
    """Format an entry's scope for display: ``global``, ``<project>``, or
    ``<project>:<branch>`` (the memory browser's convention)."""
    scope = entry.get("scope") or "global"
    project = entry.get("project")
    branch = entry.get("branch")
    if scope == "global" or not project:
        return "global"
    if scope == "branch" and branch:
        return f"{project}:{branch}"
    return project


def _group_by_day(entries: list[dict]) -> dict[str, list[dict]]:
    """Bucket entries by capture day (newest day first).

    Entry order within a day is preserved — the list query already sorts
    newest-first — and the day keys are sorted descending rather than trusting
    insertion order, so a backfilled timestamp can't misplace a group.
    """
    by_day: dict[str, list[dict]] = {}
    for entry in entries:
        by_day.setdefault(str(entry["created_at"])[:10], []).append(entry)
    return {day: by_day[day] for day in sorted(by_day, reverse=True)}


class ObservationsApp(MaitApp):
    """Master–detail, read-only browser over the raw observation tier."""

    TITLE = "mait-code observations"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_observations.tcss"]

    BINDINGS = [
        ("slash", "focus_filter", "Filter"),
        ("p", "filter_project", "Project"),
        ("escape", "escape", "Back"),
        ("r", "reload", "Reload"),
        Binding("1", "focus_list", "List", show=False),
        Binding("2", "focus_detail", "Detail", show=False),
    ]

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self._conn = get_connection(db_path)  # one connection for the app's life
        self._observations: list[dict] = []
        self._query = ""
        self._project: str | None = None

    def on_unmount(self) -> None:
        super().on_unmount()  # persists the active theme (MaitApp)
        self._conn.close()

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Observations")
        with Horizontal(id="body"):
            with Vertical(id="nav"):
                yield Input(placeholder="filter observations…", id="filter")
                yield Tree("observations", id="list")
            yield VerticalScroll(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        # As in the memory browser: the detail pane holds no focusable editor
        # widget — the container keeps focus so a long body can be scrolled
        # from the keyboard (Tab or `2` to reach it, arrows to read).
        tree: Tree[dict | str] = self.query_one("#list", Tree)
        tree.show_root = False
        tree.guide_depth = 2
        self._load_observations()
        self._rebuild_tree()
        tree.focus()

    # -- data ----------------------------------------------------------------

    def _load_observations(self) -> None:
        """(Re)read the tier, honouring the active project filter."""
        self._observations = list_observations(self._conn, project=self._project)

    def _filtered(self) -> list[dict]:
        """The observations the active text filter leaves visible."""
        if not self._query:
            return self._observations
        needle = self._query.casefold()
        return [o for o in self._observations if needle in o["content"].casefold()]

    # -- theme helpers ---------------------------------------------------------

    def _marker_colours(self) -> dict[bool, str]:
        """``reflected`` → a Rich-safe marker colour from the active theme."""
        theme = self.get_theme(self.theme)
        return {
            False: palette.rich_colour(
                theme.warning if theme else None, palette.WARNING
            ),
            True: palette.rich_colour(
                theme.success if theme else None, palette.SUCCESS
            ),
        }

    # -- tree ----------------------------------------------------------------

    def _leaf_label(self, entry: dict, colours: dict[bool, str]) -> Text:
        """One tree row: standing marker, dimmed type, first content line.

        No project here — a leaf is already the row most prone to clipping in
        the narrow nav pane, and its scope renders in the detail pane the
        moment it's highlighted. The day node carries the project instead.
        """
        first_line = (
            entry["content"].strip().splitlines()[0] if entry["content"] else ""
        )
        if len(first_line) > _LEAF_WIDTH:
            first_line = first_line[: _LEAF_WIDTH - 1] + "…"
        reflected = entry["reflected"]
        label = Text(no_wrap=True)
        mark = _REFLECTED_MARK if reflected else _PENDING_MARK
        # The gaps ride inside the styled runs (not as separate unstyled
        # segments), so renderers that trim leading run whitespace can't
        # swallow them.
        label.append(f"{mark} ", style=colours[reflected])
        label.append(f"{entry['entry_type']}  ", style="dim")
        label.append(first_line, style="dim" if reflected else "")
        return label

    def _rebuild_tree(self) -> None:
        """Re-populate the tree from the filtered observations.

        Days with anything pending open expanded — the backlog is the point of
        this surface; fully-reflected days stay collapsed behind their counts.
        With a text filter every day expands, since the matches are the point.
        Boot lands the cursor on the newest observation so the detail pane
        shows content immediately.
        """
        tree: Tree[dict | str] = self.query_one("#list", Tree)
        tree.root.remove_children()

        visible = self._filtered()
        days = _group_by_day(visible)
        colours = self._marker_colours()
        filtering = bool(self._query)
        first_leaf: TreeNode[dict | str] | None = None
        for day, entries in days.items():
            pending = sum(not e["reflected"] for e in entries)
            # A single-project day wears its project on the row (unless the
            # view is already narrowed to one); mixed days leave it to the
            # detail pane, where each entry's scope renders in full.
            day_projects = {e["project"] for e in entries if e["project"]}
            project = (
                next(iter(day_projects))
                if self._project is None and len(day_projects) == 1
                else ""
            )
            # The gap before the project rides the end of the count run — the
            # tree renderer trims a styled run's leading whitespace.
            gap = "  " if project else ""
            label = Text(no_wrap=True)
            label.append(f"{day}  ")
            if pending and pending < len(entries):
                label.append(f"{pending} pending", style=colours[False])
                label.append(f" of {len(entries)}{gap}", style="dim")
            elif pending:
                label.append(f"{pending} pending{gap}", style=colours[False])
            else:
                label.append(f"{len(entries)} reflected{gap}", style="dim")
            if project:
                label.append(project, style="dim")
            # Day nodes carry their date string as data; leaves carry their
            # entry dict — the highlight handler tells them apart by type.
            group = tree.root.add(label, data=day, expand=filtering or pending > 0)
            for entry in entries:
                leaf = group.add_leaf(self._leaf_label(entry, colours), data=entry)
                if first_leaf is None:
                    first_leaf = leaf

        self._update_subtitle(len(visible))
        if first_leaf is not None:
            # Deferred until after the first refresh: the tree's visible-line
            # map isn't built until then, and an explicit detail render covers
            # the rebuild-lands-on-the-same-line case where Tree emits no
            # NodeHighlighted (the memory browser's reasoning, verbatim).
            self.call_after_refresh(tree.move_cursor, first_leaf)
            self.call_after_refresh(self._show_detail, first_leaf.data)
        else:
            self.call_after_refresh(self._show_empty)

    def _update_subtitle(self, shown: int) -> None:
        # The masthead carries the view name and its live state: the pending
        # backlog first (it's why you're here), the project scope when
        # filtered, the match count while a text filter narrows the list.
        total = len(self._observations)
        pending = sum(not o["reflected"] for o in self._observations)
        text = f"Observations — {pending} pending of {total}"
        if self._project:
            text += f" · {self._project}"
        if self._query:
            text += f" · {shown}/{total} match"
        self.query_one(BrandBanner).set_subtitle(text)

    # -- detail --------------------------------------------------------------

    async def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        # Leaves carry their entry dict as node data; day nodes carry their
        # date string and get the day's capture batches instead of a body.
        data = event.node.data
        if isinstance(data, dict):
            await self._show_detail(data)
        elif isinstance(data, str):
            await self._show_day_detail(data, event.node)

    async def _show_detail(self, entry: dict) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        standing = "reflected" if entry["reflected"] else "pending reflection"
        meta = (
            f"captured {str(entry['created_at'])[:10]}"
            f" · importance {entry['importance']}"
            f" · scope {_scope_label(entry)}"
            f" · {standing}"
        )
        await detail.mount(
            Label(f"#{entry['id']} · {entry['entry_type']}", classes="title"),
            Label(meta, classes="help"),
            # Markdown, not Static: plain text is valid markdown, and extracted
            # content that *is* markdown renders properly. md_parser keeps
            # single newlines as line breaks, like the memory browser.
            Markdown(entry["content"], parser_factory=md_parser, open_links=False),
        )

    async def _show_day_detail(self, day: str, node: TreeNode[dict | str]) -> None:
        """The day's capture batches — the JSONL metadata the rows don't carry."""
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        count = len(node.children)
        widgets: list[Static] = [
            Label(day, classes="title"),
            Label(
                f"{count} observation{'s' if count != 1 else ''} — "
                "expand and pick one to read.",
                classes="help",
            ),
        ]
        batches = daily_batches(day)
        if batches:
            widgets.append(Label("Capture sessions", classes="subhead"))
            for batch in batches:
                line = Text(no_wrap=True)
                timestamp = batch["timestamp"] or ""
                line.append(f"{str(timestamp)[11:16] or '--:--'}  ", style="dim")
                counts = " · ".join(
                    f"{n} {category}" for category, n in batch["counts"].items()
                )
                # Project and counts merge into a single dim run that starts
                # with a word, with the gap riding the end of the trigger run —
                # a run that *begins* with whitespace gets it trimmed (the
                # run-whitespace gotcha).
                tail = " — ".join(p for p in (batch["project"], counts) if p)
                trigger = batch["trigger"] or "unknown trigger"
                line.append(f"{trigger}  " if tail else trigger)
                if tail:
                    line.append(tail, style="dim")
                widgets.append(Label(line))
        else:
            widgets.append(
                Label(
                    empty_state("No capture log for this day — entries only."),
                    classes="hint",
                )
            )
        await detail.mount_all(widgets)

    async def _show_empty(self) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        if self._query:
            message = f"Nothing observed matching {self._query!r}."
        elif self._project:
            message = f"Nothing observed for {self._project} yet."
        else:
            message = "Nothing observed yet — observations accrue as we work."
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

    def action_focus_detail(self) -> None:
        self.query_one("#detail", VerticalScroll).focus()

    def action_escape(self) -> None:
        """Escape steps back to the list; pressed on the list itself, it quits.

        The hierarchical escape, as in the memory browser: from the filter or
        the detail pane it returns focus to the tree, and from the tree
        (nothing left to back out of) it exits — so escape always eventually
        leaves, like ``q``.
        """
        if self.query_one("#list", Tree).has_focus:
            self.exit()
        else:
            self.action_focus_list()

    @work
    async def action_filter_project(self) -> None:
        # Refresh the project list first, so a project observed this session
        # shows; judged against the live store, not the loaded snapshot.
        projects = observation_projects(self._conn)
        result = await self.push_screen_wait(
            ProjectFilterScreen(projects, self._project)
        )
        if result is None:
            return  # escape/cancel — leave the active filter as-is
        # A project name filters to it; the ALL_PROJECTS sentinel clears it.
        self._project = result if isinstance(result, str) else None
        self._load_observations()
        self._rebuild_tree()
        self.action_focus_list()

    def action_reload(self) -> None:
        """Re-read the store — picks up observations captured since launch."""
        self._load_observations()
        self._rebuild_tree()
        self.notify("Observations reloaded", title="Observations")

    def get_system_commands(self, screen: Screen):
        """Expose the browser's actions in the Ctrl+P command palette."""
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Filter", "Jump to the filter input", self.action_focus_filter
        )
        yield SystemCommand(
            "Filter by project", "Narrow to one project", self.action_filter_project
        )
        yield SystemCommand(
            "Focus list", "Jump to the observations tree", self.action_focus_list
        )
        yield SystemCommand("Reload", "Re-read the store", self.action_reload)
