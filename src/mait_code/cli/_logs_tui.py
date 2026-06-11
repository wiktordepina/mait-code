"""Interactive ``mait-code logs`` &mdash; explore the structured JSONL logs.

A full-screen master&ndash;detail viewer over the logs the tools and hooks
write (:mod:`mait_code.logging`): a tree of log lines grouped by day on the
left (newest day expanded, older days collapsed behind their counts), a detail
pane rendering the selected line's full record &mdash; message, schema fields,
invocation args, and the stack trace when one was captured &mdash; on the
right. Highlighting a day shows its shape instead: lines per level and per
tool.

Four filters compose: free-text search over the message (``/``), a minimum
severity that cycles on ``l``, and tool / day pickers on ``t`` / ``d`` (the
shared :class:`~mait_code.tui.filters.ChoiceFilterScreen`). The masthead
subtitle carries the active narrowing so the view is never silently filtered.

Pure presentation over :mod:`mait_code.cli._logs`; nothing here writes &mdash;
though the surrounding process may append to today's log as it runs, which is
what ``r`` (reload) is for. Requires a TTY; the bare ``logs`` command only
routes here when attached to one, falling back to a day-grouped summary
otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Input, Label, Static, Tree
from textual.widgets.tree import TreeNode

from mait_code.cli._logs import (
    CORE_FIELDS,
    LEVELS,
    default_log_path,
    entry_day,
    entry_time,
    group_by_day,
    level_at_least,
    level_counts,
    log_files,
    read_log_entries,
)
from mait_code.tui import palette
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.banner import BrandBanner
from mait_code.tui.brand import empty_state
from mait_code.tui.filters import ChoiceFilterScreen

__all__ = ["LogsApp", "run_logs_tui"]


def run_logs_tui(log_path: Path | None = None) -> None:
    """Launch the Textual log viewer (blocks until the user quits)."""
    LogsApp(log_path=log_path).run()


#: A leaf renders "time  level  tool  message"; the message is clipped to this
#: width so the tree never forces a horizontal scroll on a sane split.
_MSG_WIDTH = 48

#: One-character level markers for the tree rows.
_LEVEL_CHAR = {"debug": "D", "info": "I", "warning": "W", "error": "E"}

#: Day groups render at most this many rows; the filters are the way to reach
#: older lines in a noisy day, and a note row says when rows were folded.
_MAX_DAY_ROWS = 500

#: An extra field whose rendered value fits this many characters rides an
#: aligned key→value row; anything longer gets its own wrapped block.
_INLINE_FIELD_MAX = 64


def _clip(text: str, width: int = _MSG_WIDTH) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if len(first_line) > width:
        return first_line[: width - 1] + "…"
    return first_line


def _kv_rows(rows: list[tuple[str, str]]) -> list[Widget]:
    """Key→value rows with the values aligned into one column (the home hub's
    convention; padding rides the end of the key run — the run-whitespace
    gotcha)."""
    width = max((len(key) for key, _ in rows), default=0)
    out: list[Widget] = []
    for key, value in rows:
        line = Text(no_wrap=True)
        line.append(f"{key.ljust(width)}  ", style="bold")
        line.append(value, style="dim")
        out.append(Label(line))
    return out


def _field_text(value: object) -> str:
    """An extra field's display text: strings as-is, the rest as JSON."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=repr)


class LogsApp(MaitApp):
    """Master–detail, read-only viewer over the structured JSONL logs."""

    TITLE = "mait-code logs"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_logs.tcss"]

    BINDINGS = [
        ("slash", "focus_filter", "Filter"),
        ("l", "cycle_level", "Level"),
        ("t", "filter_tool", "Tool"),
        ("d", "filter_day", "Day"),
        ("escape", "escape", "Back"),
        ("r", "reload", "Reload"),
        Binding("1", "focus_list", "List", show=False),
        Binding("2", "focus_detail", "Detail", show=False),
    ]

    def __init__(self, log_path: Path | None = None) -> None:
        super().__init__()
        # None resolves to the configured path at load time, so a settings
        # change between reloads is honoured; tests pass an explicit path.
        self._log_path = log_path
        self._entries: list[dict] = []
        self._clipped = False
        self._query = ""
        self._min_level: str | None = None
        self._tool: str | None = None
        self._day: str | None = None

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Logs")
        with Horizontal(id="body"):
            with Vertical(id="nav"):
                yield Input(placeholder="filter messages…", id="filter")
                yield Tree("logs", id="list")
            yield VerticalScroll(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        # As in the observations browser: the detail pane holds no focusable
        # editor widget — the container keeps focus so a long stack trace can
        # be scrolled from the keyboard (Tab or `2` to reach it).
        tree: Tree[dict | str | None] = self.query_one("#list", Tree)
        tree.show_root = False
        tree.guide_depth = 2
        self._load_entries()
        self._rebuild_tree()
        tree.focus()

    # -- data ----------------------------------------------------------------

    def _load_entries(self) -> None:
        """(Re)read the active log file and its rotated siblings."""
        path = self._log_path or default_log_path()
        self._entries, self._clipped = read_log_entries(log_files(path))

    def _filtered(self) -> list[dict]:
        """The entries the active filters leave visible."""
        entries = self._entries
        if self._day:
            entries = [e for e in entries if entry_day(e) == self._day]
        if self._tool:
            entries = [e for e in entries if e["tool"] == self._tool]
        if self._min_level:
            entries = [
                e for e in entries if level_at_least(e["level"], self._min_level)
            ]
        if self._query:
            needle = self._query.casefold()
            entries = [e for e in entries if needle in self._haystack(e)]
        return entries

    @staticmethod
    def _haystack(entry: dict) -> str:
        """What free-text search matches against: the message, plus the args
        and error message when present — the fields a "what happened?" query
        actually means."""
        parts = [entry["msg"]]
        for key in ("args", "error_message"):
            value = entry.get(key)
            if isinstance(value, str):
                parts.append(value)
        return " ".join(parts).casefold()

    # -- theme helpers ---------------------------------------------------------

    def _level_colours(self) -> dict[str, str]:
        """Level → a Rich-safe span style from the active theme.

        Debug recedes, info stays neutral, warnings and errors take the
        theme's semantic colours.
        """
        theme = self.get_theme(self.theme)
        return {
            "debug": "dim",
            "info": "",
            "warning": palette.rich_colour(
                theme.warning if theme else None, palette.WARNING
            ),
            "error": palette.rich_colour(theme.error if theme else None, palette.ERROR),
        }

    # -- tree ----------------------------------------------------------------

    def _leaf_label(self, entry: dict, colours: dict[str, str]) -> Text:
        """One tree row: dim time, coloured level marker, dim tool, message."""
        level = entry["level"] if entry["level"] in LEVELS else "info"
        label = Text(no_wrap=True)
        # Gaps ride inside the styled runs (not as separate unstyled
        # segments), so renderers that trim leading run whitespace can't
        # swallow them.
        label.append(f"{entry_time(entry)}  ", style="dim")
        label.append(f"{_LEVEL_CHAR[level]}  ", style=colours[level] or "")
        if entry["tool"]:
            label.append(f"{entry['tool']}  ", style="dim")
        label.append(_clip(entry["msg"]), style="dim" if level == "debug" else "")
        return label

    def _day_label(
        self, day: str, entries: list[dict], colours: dict[str, str]
    ) -> Text:
        """A day row: the date, its line count, and its warning/error tallies."""
        counts = level_counts(entries)
        n = len(entries)
        label = Text(no_wrap=True)
        label.append(f"{day}  ")
        segments: list[tuple[str, str]] = [(f"{n} line{'s' if n != 1 else ''}", "dim")]
        if counts["error"]:
            plural = "s" if counts["error"] != 1 else ""
            segments.append((f"{counts['error']} error{plural}", colours["error"]))
        if counts["warning"]:
            plural = "s" if counts["warning"] != 1 else ""
            segments.append(
                (f"{counts['warning']} warning{plural}", colours["warning"])
            )
        # Separators trail the run before them — the run-whitespace gotcha.
        for i, (text, style) in enumerate(segments):
            suffix = " · " if i < len(segments) - 1 else ""
            label.append(text + suffix, style=style)
        return label

    def _rebuild_tree(self) -> None:
        """Re-populate the tree from the filtered entries.

        The newest day opens expanded — it's why you're here; older days stay
        collapsed behind their counts. With any filter narrowing the view,
        every day expands, since the matches are the point. Boot lands the
        cursor on the newest line so the detail pane shows content
        immediately.
        """
        tree: Tree[dict | str | None] = self.query_one("#list", Tree)
        tree.root.remove_children()

        visible = self._filtered()
        days = group_by_day(visible)
        colours = self._level_colours()
        filtering = bool(self._query or self._min_level or self._tool)
        first_leaf: TreeNode[dict | str | None] | None = None
        for index, (day, entries) in enumerate(days.items()):
            # Day nodes carry their date string as data; leaves carry their
            # entry dict — the highlight handler tells them apart by type.
            group = tree.root.add(
                self._day_label(day, entries, colours),
                data=day,
                expand=filtering or index == 0,
            )
            for entry in entries[:_MAX_DAY_ROWS]:
                leaf = group.add_leaf(self._leaf_label(entry, colours), data=entry)
                if first_leaf is None:
                    first_leaf = leaf
            if len(entries) > _MAX_DAY_ROWS:
                folded = len(entries) - _MAX_DAY_ROWS
                group.add_leaf(
                    Text(f"… {folded} older lines — filter to narrow", style="dim"),
                    data=None,
                )

        self._update_subtitle(len(visible))
        if first_leaf is not None:
            # Deferred until after the first refresh: the tree's visible-line
            # map isn't built until then, and an explicit detail render covers
            # the rebuild-lands-on-the-same-line case where Tree emits no
            # NodeHighlighted (the observations browser's reasoning, verbatim).
            self.call_after_refresh(tree.move_cursor, first_leaf)
            self.call_after_refresh(self._show_detail, first_leaf.data)
        else:
            self.call_after_refresh(self._show_empty)

    def _update_subtitle(self, shown: int) -> None:
        # The masthead carries the view name and every active narrowing, so
        # the list is never silently filtered: error tally first, then the
        # severity floor, tool, day, and the text-match count.
        total = len(self._entries)
        errors = level_counts(self._entries)["error"]
        text = f"Logs — {total} lines"
        if errors:
            text += f" · {errors} error{'s' if errors != 1 else ''}"
        if self._min_level:
            text += f" · ≥ {self._min_level}"
        if self._tool:
            text += f" · {self._tool}"
        if self._day:
            text += f" · {self._day}"
        if self._query:
            text += f" · {shown}/{total} match"
        if self._clipped:
            text += " · oldest lines clipped"
        self.query_one(BrandBanner).set_subtitle(text)

    # -- detail --------------------------------------------------------------

    async def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        # Leaves carry their entry dict as node data; day nodes carry their
        # date string; the folded-rows note carries None and keeps the pane.
        data = event.node.data
        if isinstance(data, dict):
            await self._show_detail(data)
        elif isinstance(data, str):
            await self._show_day_detail(data)

    async def _show_detail(self, entry: dict) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        colours = self._level_colours()
        level = entry["level"] if entry["level"] in LEVELS else "info"

        title = Text(no_wrap=True)
        title.append(entry["level"].upper(), style=colours[level] or "bold")
        if entry["logger"]:
            title.append("  ")
            title.append(entry["logger"], style="dim")
        meta_parts = [f"{entry_day(entry)} {entry_time(entry)}"]
        if entry["tool"]:
            meta_parts.append(entry["tool"])
        if entry["pid"] is not None:
            meta_parts.append(f"pid {entry['pid']}")
        widgets: list[Widget] = [
            Label(title, classes="title"),
            Label(" · ".join(meta_parts), classes="help"),
            Static(Text(entry["msg"]), classes="message"),
        ]
        widgets += self._field_widgets(entry)
        stack = entry.get("stack")
        if isinstance(stack, str) and stack:
            widgets.append(Label("Stack trace", classes="subhead"))
            widgets.append(Static(Text(stack), classes="block"))
        await detail.mount_all(widgets)

    def _field_widgets(self, entry: dict) -> list[Widget]:
        """The line's extra fields: short values as aligned key→value rows,
        long ones (invocation args, error messages) as wrapped blocks."""
        extras = {
            key: value
            for key, value in entry.items()
            if key not in CORE_FIELDS and key != "stack"
        }
        if not extras:
            return []
        short: list[tuple[str, str]] = []
        long: list[tuple[str, str]] = []
        for key, value in extras.items():
            text = _field_text(value)
            target = long if len(text) > _INLINE_FIELD_MAX or "\n" in text else short
            target.append((key, text))
        widgets: list[Widget] = [Label("Fields", classes="subhead")]
        widgets += _kv_rows(short)
        for key, text in long:
            widgets.append(Label(key, classes="fieldname"))
            widgets.append(Static(Text(text), classes="block"))
        return widgets

    async def _show_day_detail(self, day: str) -> None:
        """The day's shape: its lines per level and per tool."""
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        entries = [e for e in self._filtered() if entry_day(e) == day]
        n = len(entries)
        counts = level_counts(entries)
        widgets: list[Widget] = [
            Label(day, classes="title"),
            Label(
                f"{n} line{'s' if n != 1 else ''} — expand and pick one to read.",
                classes="help",
            ),
            Label("By level", classes="subhead"),
        ]
        widgets += _kv_rows(
            [(level, str(counts[level])) for level in reversed(LEVELS) if counts[level]]
        )
        by_tool: dict[str, int] = {}
        for entry in entries:
            tool = entry["tool"] or "(unknown)"
            by_tool[tool] = by_tool.get(tool, 0) + 1
        if by_tool:
            widgets.append(Label("By tool", classes="subhead"))
            widgets += _kv_rows(
                [
                    (tool, str(count))
                    for tool, count in sorted(by_tool.items(), key=lambda kv: -kv[1])
                ]
            )
        await detail.mount_all(widgets)

    async def _show_empty(self) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        if self._query or self._min_level or self._tool or self._day:
            message = "Nothing logged matches the active filters."
        else:
            message = "Nothing logged yet — lines accrue as the tools run."
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

        The hierarchical escape, as in the sibling browsers: from the filter
        or the detail pane it returns focus to the tree, and from the tree
        (nothing left to back out of) it exits — so escape always eventually
        leaves, like ``q``.
        """
        if self.query_one("#list", Tree).has_focus:
            self.exit()
        else:
            self.action_focus_list()

    def action_cycle_level(self) -> None:
        """Cycle the severity floor: all → debug → info → warning → error."""
        order: list[str | None] = [None, *LEVELS]
        self._min_level = order[(order.index(self._min_level) + 1) % len(order)]
        self._rebuild_tree()

    @work
    async def action_filter_tool(self) -> None:
        tools = sorted({e["tool"] for e in self._entries if e["tool"]})
        result = await self.push_screen_wait(
            ChoiceFilterScreen(
                "Filter by tool", tools, self._tool, all_label="All tools"
            )
        )
        if result is None:
            return  # escape/cancel — leave the active filter as-is
        # A tool name filters to it; the ALL_CHOICES sentinel clears it.
        self._tool = result if isinstance(result, str) else None
        self._rebuild_tree()
        self.action_focus_list()

    @work
    async def action_filter_day(self) -> None:
        days = sorted({entry_day(e) for e in self._entries}, reverse=True)
        result = await self.push_screen_wait(
            ChoiceFilterScreen("Narrow to a day", days, self._day, all_label="All days")
        )
        if result is None:
            return
        self._day = result if isinstance(result, str) else None
        self._rebuild_tree()
        self.action_focus_list()

    def action_reload(self) -> None:
        """Re-read the files — picks up lines written since launch."""
        self._load_entries()
        self._rebuild_tree()
        self.notify("Logs reloaded", title="Logs")

    def get_system_commands(self, screen: Screen):
        """Expose the viewer's actions in the Ctrl+P command palette."""
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Filter", "Jump to the message filter", self.action_focus_filter
        )
        yield SystemCommand(
            "Cycle level", "Raise or clear the severity floor", self.action_cycle_level
        )
        yield SystemCommand(
            "Filter by tool", "Narrow to one tool", self.action_filter_tool
        )
        yield SystemCommand(
            "Narrow to a day", "Show a single day", self.action_filter_day
        )
        yield SystemCommand("Reload", "Re-read the log files", self.action_reload)
