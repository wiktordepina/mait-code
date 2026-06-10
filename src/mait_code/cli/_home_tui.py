"""Interactive ``mait-code home`` &mdash; the companion's front door.

A navigable hub over everything mait-code, not an at-a-glance readout: a brand
header, a tree sidebar of sections (Board, Memory, Reminders, Inbox, Identity,
System), and a detail pane that renders the highlighted section in full. Tree
nodes carry live status badges; pressing ``Enter`` on a Board, Memory or
Settings node leaves home and opens that dedicated TUI, returning here when it
quits (the relaunch loop lives in :func:`mait_code.cli.home`).

Pure presentation over the same store layers the ``mc-tool-*`` CLIs use &mdash;
nothing here writes, and nothing shells out. The one maintenance action is
``e`` (reindex): after a confirm it drops out via :meth:`App.suspend` so
``run_reindex`` can embed the entries missing a vector with its normal
terminal progress, then home reloads with the fresh embedding counts.

The brand debuts here too: the
wordmark (with a plain-text fallback on narrow terminals), the signature glyph,
and the companion voice in every empty state. The Identity section renders what
Claude is presented with at session start &mdash; the identity stack plus the
live output of the session-start context builder.

Every detail view is best-effort: a broken store renders a snag line in the
pane rather than taking the hub down.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Label, Markdown, Static, Tree
from textual.widgets.tree import TreeNode

from mait_code.config import data_dir
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.confirm import ConfirmScreen
from mait_code.tui.banner import BrandBanner, installed_version
from mait_code.tui.brand import GLYPH, empty_state
from mait_code.tui.markdown import md_parser
from mait_code.tui.palette import rich_colour as _rich_colour

__all__ = ["HomeApp", "HomeTarget", "NodeSpec", "run_home_tui"]


class HomeTarget(enum.Enum):
    """A sibling TUI the hub can hand off to.

    :meth:`HomeApp.action_launch` exits with one of these; the ``home`` command
    reads it from :func:`run_home_tui` and launches the matching app before
    looping back to a fresh home.
    """

    BOARD = "board"
    MEMORY = "memory"
    OBSERVATIONS = "observations"
    SETTINGS = "settings"


def run_home_tui() -> HomeTarget | None:
    """Launch the home hub, returning the sibling TUI to open next, if any.

    ``None`` means the user quit; a :class:`HomeTarget` means they chose to open
    that TUI. Blocks until the user leaves home.
    """
    app = HomeApp()
    app.run()
    return app.target


#: Longest card/reminder/inbox line rendered in a detail pane before clipping.
_LINE_WIDTH = 72


def _clip(text: str, width: int = _LINE_WIDTH) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if len(first_line) > width:
        return first_line[: width - 1] + "…"
    return first_line


# -- tree model ----------------------------------------------------------------


class NodeSpec:
    """What a tree node points at: a detail view, and optionally a launch.

    *detail* keys into :meth:`HomeApp._detail_builders`. *launch* (when set)
    makes ``Enter`` on the node hand off to that sibling TUI instead of just
    rendering detail.
    """

    __slots__ = ("detail", "launch")

    def __init__(self, detail: str, launch: HomeTarget | None = None) -> None:
        self.detail = detail
        self.launch = launch


# -- shared line helpers (pure; no theme needed) -------------------------------


def _card_line(card: dict) -> Label:
    line = Text(f"#{card['id']} {_clip(card['title'])}  ")
    line.append(card["project"], style="dim")
    return Label(line)


def _reminder_line(r: dict) -> Label:
    line = Text(f"#{r['id']} {_clip(r['what'])}  ")
    line.append(r["due"].strftime("%Y-%m-%d %H:%M"), style="dim")
    return Label(line)


def _kv_rows(
    rows: list[tuple[str, str]],
    *,
    key_style: str = "bold",
    value_style: str = "dim",
) -> list[Widget]:
    """Key→value rows with the values aligned into one column.

    Keys are padded to the widest key in the batch, so the value column lines up
    vertically — the monospace equivalent of a borderless two-column table.
    """
    width = max((len(key) for key, _ in rows), default=0)
    out: list[Widget] = []
    for key, value in rows:
        # Padding rides the (styled) key run; a trailing-padded run keeps its
        # spaces, unlike a leading-padded one — the run-whitespace gotcha.
        line = Text(f"{key.ljust(width)}  ", style=key_style)
        line.append(value, style=value_style)
        out.append(Label(line))
    return out


# -- badge snapshot ------------------------------------------------------------


class _Badges:
    """A point-in-time count of each store, for the tree's node badges.

    Read once per tree build. Best-effort: a store that raises leaves its
    counts at zero rather than breaking the sidebar — the detail pane is where
    a broken store surfaces its error.
    """

    def __init__(self) -> None:
        self.board_live = 0
        self.board_in_progress = 0
        self.board_refined = 0
        self.board_projects = 0
        self.mem_total = 0
        self.mem_types = 0
        self.mem_pct = 0
        self.mem_unreflected = 0
        self.rem_overdue = 0
        self.rem_upcoming = 0
        self.inbox = 0
        self._collect()

    def _collect(self) -> None:
        self._collect_board()
        self._collect_memory()
        self._collect_reminders()
        self._collect_inbox()

    def _collect_board(self) -> None:
        try:
            from mait_code.tools.board import service
            from mait_code.tools.board.db import get_connection

            conn = get_connection()
            try:
                cards = service.list_cards(conn)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 — a broken store just zeroes its badge
            return
        live = [c for c in cards if c["status"] != "done"]
        self.board_live = len(live)
        self.board_in_progress = sum(c["status"] == "in_progress" for c in cards)
        self.board_refined = sum(c["status"] == "refined" for c in cards)
        self.board_projects = len({c["project"] for c in live})

    def _collect_memory(self) -> None:
        try:
            from mait_code.tools.memory.db import get_connection
            from mait_code.tools.memory.stats import collect_stats

            conn = get_connection()
            try:
                stats = collect_stats(conn)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            return
        self.mem_total = stats.total
        self.mem_types = len(stats.by_type)
        self.mem_pct = stats.embedded_pct
        self.mem_unreflected = stats.unreflected

    def _collect_reminders(self) -> None:
        try:
            from mait_code.tools.reminders.db import get_connection
            from mait_code.tools.reminders.service import active_reminders

            conn = get_connection()
            try:
                overdue, upcoming = active_reminders(conn)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            return
        self.rem_overdue = len(overdue)
        self.rem_upcoming = len(upcoming)

    def _collect_inbox(self) -> None:
        try:
            from mait_code.tools.inbox import service
            from mait_code.tools.inbox.db import get_connection

            conn = get_connection()
            try:
                self.inbox = service.count_items(conn)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            return


class HomeApp(MaitApp):
    """The companion's front door — a tree-navigable hub over every store."""

    TITLE = "mait-code"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_home.tcss"]

    BINDINGS = [
        ("r", "reload", "Reload"),
        ("e", "reindex", "Reindex"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        # The sibling TUI to open after home exits, read by run_home_tui. None
        # until the user picks a launch node (MaitApp is App[None], so the
        # choice rides on the instance rather than App.run()'s return value).
        self.target: HomeTarget | None = None

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Home Hub")
        with Horizontal(id="body"):
            yield Tree(f"{GLYPH} mait-code", id="tree")
            yield VerticalScroll(id="detail")
        yield Static(id="health")
        yield Footer()

    def on_mount(self) -> None:
        tree: Tree[NodeSpec] = self.query_one("#tree", Tree)
        # Enter posts NodeSelected without auto-expanding (see on_tree_node_selected),
        # so a launch leaf launches and a category toggles — no double action.
        tree.auto_expand = False
        tree.guide_depth = 2
        tree.root.data = NodeSpec("home")
        tree.root.expand()
        self._build_tree()
        self.query_one("#health", Static).update(_health_line(self._level_colours()))
        tree.focus()
        # The root is highlighted on boot but emits no NodeHighlighted, so render
        # its detail explicitly (same reasoning as the memory browser's tree).
        self.call_after_refresh(self._show_detail, "home")

    # -- rendering -------------------------------------------------------------

    def _build_tree(self) -> None:
        """(Re)build the sidebar, folding live counts into the node badges."""
        tree: Tree[NodeSpec] = self.query_one("#tree", Tree)
        tree.root.remove_children()
        b = _Badges()
        warn = self._level_colours()["warn"]
        accent = self._accent_colour()

        def section(
            name: str, spec: NodeSpec, badge: str = "", style: str = "dim"
        ) -> TreeNode[NodeSpec]:
            # The gap rides the end of the name run, not the start of the badge
            # run — the tree renderer trims a styled run's leading whitespace.
            label = Text(f"{name}  ") if badge else Text(name)
            if badge:
                label.append(badge, style=style)
            node = tree.root.add(label, data=spec)
            node.expand()
            return node

        def leaf(parent: TreeNode[NodeSpec], name: str, spec: NodeSpec) -> None:
            parent.add_leaf(name, data=spec)

        def launch_leaf(parent: TreeNode[NodeSpec], name: str, spec: NodeSpec) -> None:
            # A dedicated "open this TUI" leaf: the ↗ glyph and the accent hue
            # mark it as a hand-off, distinct from the plain detail leaves. The
            # category itself stays a normal expand/collapse node.
            parent.add_leaf(Text(f"↗ {name}", style=accent), data=spec)

        board = section(
            "Board",
            NodeSpec("board"),
            f"{b.board_live} active" if b.board_live else "",
        )
        launch_leaf(board, "Open board", NodeSpec("board", HomeTarget.BOARD))
        leaf(board, "In progress", NodeSpec("board:in_progress"))
        leaf(board, "Next up", NodeSpec("board:refined"))
        leaf(board, "By project", NodeSpec("board:by_project"))

        memory = section(
            "Memory",
            NodeSpec("memory"),
            f"{b.mem_total}" if b.mem_total else "",
        )
        launch_leaf(
            memory, "Open memory browser", NodeSpec("memory", HomeTarget.MEMORY)
        )
        leaf(memory, "By type", NodeSpec("memory:by_type"))
        leaf(memory, "Embedding coverage", NodeSpec("memory:embedding"))
        leaf(memory, "Reflection status", NodeSpec("memory:reflection"))
        # Sits under Reflection status on purpose: the observations browser is
        # the drill-down its "awaiting N" count used to lack. Same detail key,
        # so highlighting the launch leaf previews the reflection numbers.
        launch_leaf(
            memory,
            "Open observations",
            NodeSpec("memory:reflection", HomeTarget.OBSERVATIONS),
        )

        if b.rem_overdue:
            reminders = section(
                "Reminders", NodeSpec("reminders"), f"{b.rem_overdue} overdue!", warn
            )
        else:
            reminders = section(
                "Reminders",
                NodeSpec("reminders"),
                f"{b.rem_upcoming} upcoming" if b.rem_upcoming else "",
            )
        leaf(reminders, "Overdue", NodeSpec("reminders:overdue"))
        leaf(reminders, "Upcoming", NodeSpec("reminders:upcoming"))

        section("Inbox", NodeSpec("inbox"), f"{b.inbox}" if b.inbox else "")

        identity = section("Identity", NodeSpec("identity"))
        leaf(identity, "System prompt", NodeSpec("identity:sysprompt"))

        system = section("System", NodeSpec("system"))
        launch_leaf(
            system, "Open settings", NodeSpec("system:settings", HomeTarget.SETTINGS)
        )
        leaf(system, "Doctor", NodeSpec("system:doctor"))
        leaf(system, "Version & paths", NodeSpec("system:version"))

    # -- detail dispatch -------------------------------------------------------

    def _detail_builders(self) -> dict[str, Callable[[], list[Widget]]]:
        return {
            "home": self._detail_home,
            "board": self._detail_board,
            "board:in_progress": self._detail_board_in_progress,
            "board:refined": self._detail_board_refined,
            "board:by_project": self._detail_board_by_project,
            "memory": self._detail_memory,
            "memory:by_type": self._detail_memory_by_type,
            "memory:embedding": self._detail_memory_embedding,
            "memory:reflection": self._detail_memory_reflection,
            "reminders": self._detail_reminders,
            "reminders:overdue": self._detail_reminders_overdue,
            "reminders:upcoming": self._detail_reminders_upcoming,
            "inbox": self._detail_inbox,
            "identity": self._detail_identity,
            "identity:sysprompt": self._detail_sysprompt,
            "system": self._detail_system,
            "system:doctor": self._detail_doctor,
            "system:settings": self._detail_settings,
            "system:version": self._detail_version,
        }

    async def on_tree_node_highlighted(
        self, event: Tree.NodeHighlighted[NodeSpec]
    ) -> None:
        spec = event.node.data
        if spec is not None:
            await self._show_detail(spec.detail)

    def on_tree_node_selected(self, event: Tree.NodeSelected[NodeSpec]) -> None:
        # Enter: launch a sibling TUI if this node has one; otherwise toggle a
        # category open/closed. Leaf detail nodes simply re-show their detail
        # (already rendered on highlight), so nothing extra to do.
        spec = event.node.data
        if spec is not None and spec.launch is not None:
            self.action_launch(spec.launch)
        elif event.node.allow_expand:
            event.node.toggle()

    async def _show_detail(self, key: str) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        builder = self._detail_builders().get(key)
        try:
            widgets = builder() if builder else [Label(empty_state("Nothing here."))]
        except Exception as exc:  # noqa: BLE001 — a broken store mustn't kill home
            widgets = [
                Label(empty_state(f"This view hit a snag: {exc}"), classes="overdue")
            ]
        await detail.mount_all(widgets)

    # -- detail builders: overview ---------------------------------------------

    def _detail_home(self) -> list[Widget]:
        b = _Badges()
        widgets: list[Widget] = [
            Label(
                empty_state("Welcome home — your central place for mait-code."),
                classes="help",
            ),
            Label(
                "Pick a section on the left; open a full tool from its "
                "“↗ Open …” leaf.",
                classes="help",
            ),
        ]

        board = (
            f"{b.board_in_progress} in progress · {b.board_refined} next up"
            if b.board_live
            else "all clear"
        )
        rem = (
            f"{b.rem_overdue} overdue · {b.rem_upcoming} upcoming"
            if (b.rem_overdue or b.rem_upcoming)
            else "nothing pending"
        )
        widgets.append(Label("At a glance", classes="subhead"))
        widgets += _kv_rows(
            [
                ("Board", board),
                ("Memory", f"{b.mem_total} entries · {b.mem_pct}% embedded"),
                ("Reminders", rem),
                ("Inbox", f"{b.inbox} waiting" if b.inbox else "inbox zero"),
            ]
        )
        return widgets

    # -- detail builders: board ------------------------------------------------

    @staticmethod
    def _board_cards() -> list[dict]:
        from mait_code.tools.board import service
        from mait_code.tools.board.db import get_connection

        conn = get_connection()
        try:
            return service.list_cards(conn)
        finally:
            conn.close()

    def _detail_board(self) -> list[Widget]:
        cards = self._board_cards()
        if not cards:
            return [Label(empty_state("The board is clear — nothing tracked yet."))]
        widgets: list[Widget] = [Label("Board", classes="title")]
        live = [c for c in cards if c["status"] != "done"]
        n_proj = len({c["project"] for c in live})
        widgets.append(
            Label(f"{len(live)} live across {n_proj} project(s)", classes="help")
        )
        widgets.append(
            Label(
                "Press Enter on “↗ Open board” to launch the full board.",
                classes="hint",
            )
        )
        for status, head in (("in_progress", "In progress"), ("refined", "Next up")):
            group = [c for c in cards if c["status"] == status]
            if group:
                widgets.append(Label(head, classes="subhead"))
                widgets += [_card_line(c) for c in group]
        return widgets

    def _detail_board_in_progress(self) -> list[Widget]:
        group = [c for c in self._board_cards() if c["status"] == "in_progress"]
        if not group:
            return [Label(empty_state("Nothing in progress right now."))]
        widgets: list[Widget] = [Label("In progress", classes="title")]
        widgets += [_card_line(c) for c in group]
        return widgets

    def _detail_board_refined(self) -> list[Widget]:
        group = [c for c in self._board_cards() if c["status"] == "refined"]
        if not group:
            return [Label(empty_state("Nothing refined and ready yet."))]
        widgets: list[Widget] = [Label("Next up", classes="title")]
        widgets += [_card_line(c) for c in group]
        return widgets

    def _detail_board_by_project(self) -> list[Widget]:
        cards = self._board_cards()
        if not cards:
            return [Label(empty_state("The board is clear — nothing tracked yet."))]
        by_project: dict[str, dict[str, int]] = {}
        for card in cards:
            counts = by_project.setdefault(card["project"], {})
            counts[card["status"]] = counts.get(card["status"], 0) + 1

        def live(counts: dict[str, int]) -> int:
            return sum(n for status, n in counts.items() if status != "done")

        rows: list[tuple[str, str]] = []
        for project in sorted(
            by_project, key=lambda p: live(by_project[p]), reverse=True
        ):
            counts = by_project[project]
            parts = [
                f"{n} {status.replace('_', ' ')}"
                for status, n in counts.items()
                if status != "done" and n
            ]
            rows.append((project, " · ".join(parts) if parts else "all done"))
        widgets: list[Widget] = [Label("By project", classes="title")]
        widgets += _kv_rows(rows)
        return widgets

    # -- detail builders: memory -----------------------------------------------

    @staticmethod
    def _memory_stats():
        from mait_code.tools.memory.db import get_connection
        from mait_code.tools.memory.stats import collect_stats

        conn = get_connection()
        try:
            return collect_stats(conn)
        finally:
            conn.close()

    def _detail_memory(self) -> list[Widget]:
        stats = self._memory_stats()
        if stats.total == 0:
            return [
                Label(
                    empty_state("Nothing remembered yet — we're just getting started.")
                )
            ]
        widgets: list[Widget] = [
            Label("Memory", classes="title"),
            Label(f"{stats.total} entries", classes="help"),
            Label(
                "Press Enter on “↗ Open memory browser” to launch it.",
                classes="hint",
            ),
            Label("By type", classes="subhead"),
        ]
        widgets += _kv_rows([(name, str(count)) for name, count in stats.by_type])
        if stats.superseded:
            widgets.append(
                Label(
                    f"{stats.superseded} superseded (kept for audit, hidden from recall)",
                    classes="help",
                )
            )
        return widgets

    def _detail_memory_by_type(self) -> list[Widget]:
        from mait_code.tools.memory.db import get_connection
        from mait_code.tools.memory.search import list_entries

        conn = get_connection()
        try:
            entries = list_entries(conn, limit=100_000)
        finally:
            conn.close()
        if not entries:
            return [Label(empty_state("Nothing remembered yet."))]
        by_type: dict[str, list[dict]] = {}
        for entry in entries:
            by_type.setdefault(entry["entry_type"], []).append(entry)
        widgets: list[Widget] = [Label("By type", classes="title")]
        for entry_type in sorted(by_type, key=lambda t: -len(by_type[t])):
            group = by_type[entry_type]
            widgets.append(Label(f"{entry_type} ({len(group)})", classes="subhead"))
            for entry in group[:5]:
                line = Text(f"{str(entry['created_at'])[:10]}  ", style="dim")
                line.append(_clip(entry["content"]))
                widgets.append(Label(line))
            if len(group) > 5:
                widgets.append(Label(Text(f"… and {len(group) - 5} more", style="dim")))
        return widgets

    def _detail_memory_embedding(self) -> list[Widget]:
        stats = self._memory_stats()
        if stats.total == 0:
            return [Label(empty_state("Nothing remembered yet."))]
        widgets: list[Widget] = [
            Label("Embedding coverage", classes="title"),
            Label(
                f"{stats.embedded}/{stats.total} embedded ({stats.embedded_pct}%)",
                classes="help",
            ),
        ]
        widgets += _kv_rows(
            [
                ("embedded", f"{stats.embedded} of {stats.total}"),
                ("unembedded", str(stats.unembedded)),
                ("provider", stats.provider),
                ("model", stats.model),
                ("dimensions", str(stats.dim)),
            ]
        )
        widgets.append(
            Label(
                empty_state("Press e to embed the entries missing a vector."),
                classes="hint",
            )
        )
        return widgets

    def _detail_memory_reflection(self) -> list[Widget]:
        stats = self._memory_stats()
        last = (
            stats.last_reflected_at.strftime("%Y-%m-%d %H:%M")
            if stats.last_reflected_at
            else "never"
        )
        widgets: list[Widget] = [Label("Reflection status", classes="title")]
        widgets += _kv_rows(
            [
                ("awaiting", f"{stats.unreflected} observation(s)"),
                ("last run", last),
            ]
        )
        widgets.append(
            Label(
                empty_state(
                    "Press Enter on “↗ Open observations” to see what's waiting; "
                    "run /reflect in a session to synthesise insights."
                ),
                classes="hint",
            )
        )
        return widgets

    # -- detail builders: reminders --------------------------------------------

    @staticmethod
    def _active_reminders():
        from mait_code.tools.reminders.db import get_connection
        from mait_code.tools.reminders.service import active_reminders

        conn = get_connection()
        try:
            return active_reminders(conn)
        finally:
            conn.close()

    def _detail_reminders(self) -> list[Widget]:
        overdue, upcoming = self._active_reminders()
        if not overdue and not upcoming:
            return [
                Label(
                    empty_state(
                        "Nothing pending — I'll nudge you when something's due."
                    )
                )
            ]
        widgets: list[Widget] = [Label("Reminders", classes="title")]
        if overdue:
            widgets.append(
                Label(f"Overdue ({len(overdue)})", classes="subhead overdue")
            )
            widgets += [_reminder_line(r) for r in overdue]
        if upcoming:
            widgets.append(Label("Upcoming", classes="subhead"))
            widgets += [_reminder_line(r) for r in upcoming]
        return widgets

    def _detail_reminders_overdue(self) -> list[Widget]:
        overdue, _ = self._active_reminders()
        if not overdue:
            return [Label(empty_state("Nothing overdue — you're on top of it."))]
        widgets: list[Widget] = [Label("Overdue", classes="title overdue")]
        widgets += [_reminder_line(r) for r in overdue]
        return widgets

    def _detail_reminders_upcoming(self) -> list[Widget]:
        _, upcoming = self._active_reminders()
        if not upcoming:
            return [Label(empty_state("Nothing upcoming on the books."))]
        widgets: list[Widget] = [Label("Upcoming", classes="title")]
        widgets += [_reminder_line(r) for r in upcoming]
        return widgets

    # -- detail builders: inbox ------------------------------------------------

    def _detail_inbox(self) -> list[Widget]:
        from mait_code.tools.inbox import service
        from mait_code.tools.inbox.db import get_connection

        conn = get_connection()
        try:
            items = service.list_items(conn)
        finally:
            conn.close()
        if not items:
            return [Label(empty_state("Inbox zero — nothing waiting to be sorted."))]
        n = len(items)
        widgets: list[Widget] = [
            Label("Inbox", classes="title"),
            Label(
                f"{n} captured item{'s' if n != 1 else ''} waiting for triage.",
                classes="help",
            ),
            Label(
                empty_state("Run /triage in a session to sort these."), classes="hint"
            ),
        ]
        for item in items:
            line = Text(f"{str(item['created_at'])[:10]}  ", style="dim")
            line.append(_clip(item["body"]))
            widgets.append(Label(line))
        return widgets

    # -- detail builders: identity ---------------------------------------------

    def _detail_identity(self) -> list[Widget]:
        return [
            Label("Identity", classes="title"),
            Label(
                empty_state("What I'm made of — open System prompt to see it."),
                classes="help",
            ),
        ]

    def _detail_sysprompt(self) -> list[Widget]:
        from mait_code.hooks.session_start.context import build_session_context

        # Read each identity document once — the text feeds both the token
        # estimate and the rendered body.
        identity = [
            (title, path, _read_identity(path)) for title, path in _identity_files()
        ]
        session = build_session_context()

        total = sum(_estimate_tokens(text) for _, _, text in identity if text)
        total += _estimate_tokens(session) if session else 0

        title_line = Text(f"{GLYPH} What I see when I wake up  ", style="bold")
        title_line.append(f"{_fmt_tokens(total)} tokens total", style="dim")
        widgets: list[Widget] = [
            Label(title_line, classes="title"),
            Label("Rough estimate — ~4 chars/token, no tokenizer.", classes="hint"),
        ]

        for title, path, text in identity:
            widgets.append(_sysprompt_subhead(title, text))
            if text is None:
                widgets.append(
                    Label(
                        empty_state(
                            f"{path.name} isn't written yet — "
                            "this part of me is still blank."
                        )
                    )
                )
            else:
                widgets.append(
                    Markdown(text, parser_factory=md_parser, open_links=False)
                )

        widgets.append(
            _sysprompt_subhead("Session context — built live by the hook", session)
        )
        if session:
            widgets.append(
                Markdown(session, parser_factory=md_parser, open_links=False)
            )
        else:
            widgets.append(
                Label(empty_state("A quiet start — nothing to surface right now."))
            )
        return widgets

    # -- detail builders: system -----------------------------------------------

    def _detail_system(self) -> list[Widget]:
        return [
            Label("System", classes="title"),
            Label(
                empty_state("Health, configuration, and where things live."),
                classes="help",
            ),
        ]

    def _detail_doctor(self) -> list[Widget]:
        from mait_code.console import GLYPH as LEVEL_GLYPH
        from mait_code.cli._doctor import run_doctor

        colours = self._level_colours()
        report = run_doctor()
        widgets: list[Widget] = [Label("Doctor", classes="title")]
        # Pad the name column so the messages line up beneath one another, with
        # the level glyph (its own colour) leading each row.
        width = max((len(c.name) for c in report.checks), default=0)
        for check in report.checks:
            line = Text()
            line.append(f"{LEVEL_GLYPH[check.level]}  ", style=colours[check.level])
            line.append(f"{check.name.ljust(width)}  ", style="bold")
            line.append(check.message, style="dim")
            widgets.append(Label(line))
        return widgets

    def _detail_settings(self) -> list[Widget]:
        from mait_code.config import collect_settings

        widgets: list[Widget] = [
            Label("Settings", classes="title"),
            Label(
                "Press Enter on “↗ Open settings” to launch the editor.",
                classes="hint",
            ),
        ]
        try:
            snapshot = collect_settings()
        except Exception as exc:  # noqa: BLE001
            return widgets + [Label(empty_state(f"Couldn't read settings: {exc}"))]
        widgets += _kv_rows([(s.key, str(s.value)) for s in snapshot.settings])
        return widgets

    def _detail_version(self) -> list[Widget]:
        from mait_code.cli._paths import settings_path

        home = str(Path.home())
        widgets: list[Widget] = [Label("Version & paths", classes="title")]
        widgets += _kv_rows(
            [
                ("version", installed_version()),
                ("data dir", str(data_dir()).replace(home, "~")),
                ("settings", str(settings_path()).replace(home, "~")),
            ]
        )
        return widgets

    # -- theme helpers ---------------------------------------------------------

    def _level_colours(self) -> dict[str, str]:
        """Doctor levels → Rich-parseable colours from the active theme.

        Normalised through :func:`_rich_colour`, so the ``ansi`` themes (whose
        ``ansi_yellow``-style names Rich can't parse) render instead of crashing,
        and falls back to the house palette when a slot is unset.
        """
        from mait_code.tui import palette

        theme = self.get_theme(self.theme)
        return {
            "ok": _rich_colour(theme.success if theme else None, palette.SUCCESS),
            "warn": _rich_colour(theme.warning if theme else None, palette.WARNING),
            "fail": _rich_colour(theme.error if theme else None, palette.ERROR),
        }

    def _accent_colour(self) -> str:
        """The active theme's accent hue (Rich-safe), for the tree's launch leaves.

        Normalised through :func:`_rich_colour`; falls back to the house accent
        when the active theme leaves it unset.
        """
        from mait_code.tui import palette

        theme = self.get_theme(self.theme)
        return _rich_colour(theme.accent if theme else None, palette.ACCENT)

    # -- actions ---------------------------------------------------------------

    def _refresh(self) -> None:
        """Re-read every store — rebuilds the badges, health line, and detail."""
        tree: Tree[NodeSpec] = self.query_one("#tree", Tree)
        current = tree.cursor_node
        key = current.data.detail if current and current.data else "home"
        self._build_tree()
        self.query_one("#health", Static).update(_health_line(self._level_colours()))
        self.call_after_refresh(self._show_detail, key)

    def action_reload(self) -> None:
        """Re-read every store — refreshes the badges and the current detail."""
        self._refresh()
        self.notify("Home reloaded", title="Home")

    @work
    async def action_reindex(self) -> None:
        """Confirm, embed the entries missing a vector, then refresh the hub."""
        try:
            missing = self._memory_stats().unembedded
        except Exception as exc:  # noqa: BLE001 — a broken store mustn't kill home
            self.notify(
                f"Couldn't read the memory store: {exc}",
                title="Reindex",
                severity="error",
            )
            return
        if missing == 0:
            self.notify("Every memory entry already has a vector.", title="Reindex")
            return
        noun = "entry" if missing == 1 else "entries"
        confirmed = await self.push_screen_wait(
            ConfirmScreen(f"Embed the {missing} memory {noun} missing a vector?")
        )
        if not confirmed:
            return
        note, failed = self._run_reindex_suspended()
        self._refresh()
        self.notify(
            note, title="Reindex", severity="error" if failed else "information"
        )

    def _run_reindex_suspended(self) -> tuple[str, bool]:
        """Drop out of the app to embed with normal terminal output.

        Returns:
            The outcome line for the toast, and whether the reindex failed.
        """
        from mait_code.tools.memory.cli import ReindexError, run_reindex

        with self.suspend():
            try:
                note, failed = (
                    f"Embedded {run_reindex(missing_only=True)} entries",
                    False,
                )
            except ReindexError as exc:
                note, failed = f"Reindex failed: {exc}", True
                print(f"\n{note}")
            input("\nPress Enter to return home… ")
        return note, failed

    def action_launch(self, target: HomeTarget) -> None:
        """Leave home and open a sibling TUI; the home command relaunches us."""
        self.target = target
        self.exit()

    def action_cursor_down(self) -> None:
        self.query_one("#tree", Tree).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#tree", Tree).action_cursor_up()

    def get_system_commands(self, screen: Screen):
        """Expose the hub's actions in the Ctrl+P command palette."""
        yield from super().get_system_commands(screen)
        yield SystemCommand("Reload", "Re-read every store", self.action_reload)
        yield SystemCommand(
            "Reindex memory",
            "Embed the memory entries that lack a vector",
            self.action_reindex,
        )
        yield SystemCommand(
            "Open board",
            "Jump to the board TUI",
            lambda: self.action_launch(HomeTarget.BOARD),
        )
        yield SystemCommand(
            "Open memory",
            "Jump to the memory browser",
            lambda: self.action_launch(HomeTarget.MEMORY),
        )
        yield SystemCommand(
            "Open observations",
            "Jump to the observations browser",
            lambda: self.action_launch(HomeTarget.OBSERVATIONS),
        )
        yield SystemCommand(
            "Open settings",
            "Jump to the settings editor",
            lambda: self.action_launch(HomeTarget.SETTINGS),
        )


# -- module helpers: identity & health -----------------------------------------


def _identity_files() -> tuple[tuple[str, Path], ...]:
    ddir = data_dir()
    return (
        ("Soul document", ddir / "soul_document.md"),
        ("User context", ddir / "user_context.md"),
        ("Curated memory (MEMORY.md)", ddir / "memory" / "MEMORY.md"),
    )


def _read_identity(path: Path) -> str | None:
    """An identity document's text, or ``None`` when it isn't written yet."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token for English prose.

    A deliberate heuristic, not a tokenizer — mait-code ships no model SDK and
    works offline. Close enough to gauge the budget the identity stack spends at
    session start; the true count is whatever Claude's tokenizer lands on.
    """
    return round(len(text) / 4)


def _fmt_tokens(n: int) -> str:
    """A compact ``~1.2k`` / ``~840`` token count for a section header badge."""
    return f"~{n / 1000:.1f}k" if n >= 1000 else f"~{n}"


def _sysprompt_subhead(title: str, text: str | None) -> Label:
    """A system-prompt section header carrying its token-estimate badge."""
    head = Text(f"{title}  ")
    head.append(
        f"{_fmt_tokens(_estimate_tokens(text))} tokens" if text else "blank",
        style="dim",
    )
    return Label(head, classes="subhead")


def _health_line(colours: dict[str, str]) -> Text:
    """The doctor verdict as one line: a level glyph and the check counts.

    A sibling of ``_doctor._verdict``, rebuilt here because the console's
    semantic ``ok``/``warn``/``fail`` styles don't resolve inside Textual —
    *colours* maps those levels to concrete theme colours instead.
    """
    from mait_code.console import GLYPH as LEVEL_GLYPH
    from mait_code.cli._doctor import run_doctor

    report = run_doctor()
    n_fail = sum(c.level == "fail" for c in report.checks)
    n_warn = sum(c.level == "warn" for c in report.checks)
    n_ok = sum(c.level == "ok" for c in report.checks)
    overall = "fail" if n_fail else "warn" if n_warn else "ok"

    line = Text()
    line.append(f"{LEVEL_GLYPH[overall]} ", style=colours[overall])
    segments: list[tuple[str, str]] = []
    if n_fail:
        segments.append((f"{n_fail} failed", colours["fail"]))
    if n_warn:
        segments.append(
            (f"{n_warn} warning{'s' if n_warn != 1 else ''}", colours["warn"])
        )
    segments.append((f"{n_ok} passed", colours["ok"]))
    # Separators trail the run before them — see the run-whitespace note in
    # _detail_board_by_project.
    for i, (text, style) in enumerate(segments):
        line.append(f"{text}{' · ' if i < len(segments) - 1 else '  '}", style=style)
    line.append("— doctor", style="dim")
    return line
