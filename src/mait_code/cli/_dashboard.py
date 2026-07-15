"""Dashboard config and tile data for the home hub's start page.

The hub's landing view is a user-authored widget grid — the sampler/wtfutil
pattern. A ``dashboard.toml`` in the data dir declares the grid: a column
count and an ordered list of tiles, each either a **built-in widget** (a
glanceable readout over one of the stores) or an **arbitrary shell command**
whose stdout becomes the tile body. No config means the default layout — the
page is never blank.

This module is the pure half: parsing, validation, the default layout, the
built-in collectors, and the subprocess runner for command tiles. Everything
Textual — the grid container, the worker plumbing, the styling — lives in
:mod:`mait_code.cli._home_tui`, which renders the :class:`TileLine` batches
this module produces.

Loading is tolerant by design (modelled on
:func:`mait_code.config.read_settings_file`): a malformed file or a bad tile
falls back or is skipped, with the problem carried in
:attr:`DashboardConfig.warnings` for the hub to surface — never an exception.
The built-in collectors, by contrast, *do* raise on a broken store; the hub
catches per tile and renders an error state, so one broken store costs one
tile, not the page.
"""

from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple

from mait_code.config import data_dir

__all__ = [
    # Config model
    "TileSpec",
    "DashboardConfig",
    "TileLine",
    "CommandResult",
    # Loading
    "dashboard_path",
    "load_dashboard",
    "default_tiles",
    # Editing
    "EditableTile",
    "EditableDashboard",
    # Tiles
    "BUILTIN_WIDGETS",
    "builtin_tile_lines",
    "builtin_title",
    "run_command_tile",
    # Limits
    "MAX_COLUMNS",
    "MAX_OUTPUT_LINES",
]


#: Widest grid the hub will lay out; larger ``columns`` values are clamped.
MAX_COLUMNS = 4

#: Longest command-tile body kept; longer stdout is clipped with a footer line.
MAX_OUTPUT_LINES = 20

#: Lines listed per built-in widget (top reminders, cards, inbox items).
_LIST_LIMIT = 3


@dataclass(frozen=True)
class TileSpec:
    """One tile in the grid: a built-in widget or a shell command.

    Exactly one of :attr:`widget` and :attr:`command` is set — the loader
    skips (with a warning) any ``[[tile]]`` entry that declares both or
    neither.

    Attributes:
        widget: Key into :data:`BUILTIN_WIDGETS`, or ``None`` for a command
            tile.
        command: Shell command whose stdout fills the tile, or ``None`` for a
            built-in.
        title: Tile header. Defaults to the built-in's display name, or the
            command string for command tiles.
        span: Grid columns the tile occupies (clamped to the column count).
    """

    widget: str | None = None
    command: str | None = None
    title: str = ""
    span: int = 1


@dataclass(frozen=True)
class DashboardConfig:
    """The parsed dashboard: grid shape, tiles, and any loader warnings.

    Attributes:
        columns: Grid width, ``1``–:data:`MAX_COLUMNS`.
        tiles: The tiles, in authored order.
        warnings: Human-readable problems the loader worked around (malformed
            file, unknown widget, …) — surfaced by the hub, never raised.
        authored: ``True`` when a readable ``dashboard.toml`` supplied the
            layout; ``False`` means the built-in default is showing (the hub
            uses this to hint where the file lives).
    """

    columns: int = 2
    tiles: tuple[TileSpec, ...] = ()
    warnings: tuple[str, ...] = ()
    authored: bool = False


class TileLine(NamedTuple):
    """One rendered line of a tile body.

    *style* is semantic, not visual — ``""`` (body), ``"dim"`` or ``"warn"``
    — so this module stays free of Textual and the hub maps styles onto the
    active theme.
    """

    text: str
    style: str = ""


@dataclass(frozen=True)
class CommandResult:
    """A command tile's outcome: the body to show and whether it succeeded.

    Attributes:
        ok: ``True`` when the command exited zero within its timeout.
        output: Stdout (clipped to :data:`MAX_OUTPUT_LINES`) on success; a
            one-line diagnosis (exit code + stderr tail, or the timeout) on
            failure.
    """

    ok: bool
    output: str


def dashboard_path() -> Path:
    """Where ``dashboard.toml`` lives — under the data dir, beside settings."""
    return data_dir() / "dashboard.toml"


def default_tiles() -> tuple[TileSpec, ...]:
    """The layout shown when no ``dashboard.toml`` is authored."""
    return (
        TileSpec(widget="reminders"),
        TileSpec(widget="board"),
        TileSpec(widget="inbox"),
        TileSpec(widget="memory"),
    )


def load_dashboard(path: Path | None = None) -> DashboardConfig:
    """Read and validate ``dashboard.toml``, falling back rather than raising.

    Args:
        path: Override the config location (defaults to
            :func:`dashboard_path`).

    Returns:
        The authored layout when the file parses; the default layout (with a
        warning) when it is malformed or declares no usable tile; the default
        layout (silently) when the file simply doesn't exist.
    """
    if path is None:
        path = dashboard_path()
    if not path.exists():
        return DashboardConfig(tiles=default_tiles())
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        return DashboardConfig(
            tiles=default_tiles(),
            warnings=(f"{path.name} could not be read ({exc}) — showing defaults",),
        )

    warnings: list[str] = []
    columns = _parse_columns(raw.get("columns", 2), warnings)
    tiles = _parse_tiles(raw.get("tile", []), columns, warnings)
    if not tiles:
        warnings.append(f"{path.name} declares no usable tiles — showing defaults")
        return DashboardConfig(
            columns=columns, tiles=default_tiles(), warnings=tuple(warnings)
        )
    return DashboardConfig(
        columns=columns, tiles=tiles, warnings=tuple(warnings), authored=True
    )


def _parse_columns(value: object, warnings: list[str]) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        warnings.append(f"columns must be an integer, got {value!r} — using 2")
        return 2
    if not 1 <= value <= MAX_COLUMNS:
        clamped = min(max(value, 1), MAX_COLUMNS)
        warnings.append(
            f"columns must be 1–{MAX_COLUMNS}, got {value} — using {clamped}"
        )
        return clamped
    return value


def _parse_tiles(
    raw: object, columns: int, warnings: list[str]
) -> tuple[TileSpec, ...]:
    return tuple(spec for _, spec in _parse_tiles_indexed(raw, columns, warnings))


def _parse_tiles_indexed(
    raw: object, columns: int, warnings: list[str]
) -> list[tuple[int, TileSpec]]:
    """Validate tile entries, keeping each survivor's index in the raw list.

    The index lets :meth:`EditableDashboard.load` pair a validated tile back
    to its tomlkit table, so edits preserve that table's comments.
    """
    if not isinstance(raw, list):
        warnings.append("tile entries must be [[tile]] tables")
        return []
    tiles: list[tuple[int, TileSpec]] = []
    for i, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            warnings.append(f"tile {i}: not a table — skipped")
            continue
        widget = entry.get("widget")
        command = entry.get("command")
        if isinstance(widget, str) and widget and not command:
            if widget not in BUILTIN_WIDGETS:
                known = ", ".join(sorted(BUILTIN_WIDGETS))
                warnings.append(
                    f"tile {i}: unknown widget {widget!r} "
                    f"(built-ins: {known}) — skipped"
                )
                continue
            command = None
        elif isinstance(command, str) and command.strip() and not widget:
            widget, command = None, command.strip()
        else:
            warnings.append(
                f"tile {i}: needs exactly one of widget or command — skipped"
            )
            continue
        title = entry.get("title")
        title = title.strip() if isinstance(title, str) else ""
        span = entry.get("span", 1)
        if not isinstance(span, int) or isinstance(span, bool) or span < 1:
            warnings.append(f"tile {i}: span must be a positive integer — using 1")
            span = 1
        tiles.append(
            (
                i - 1,
                TileSpec(
                    widget=widget,
                    command=command,
                    title=title,
                    span=min(span, columns),
                ),
            )
        )
    return tiles


# ---------------------------------------------------------------------------
# Built-in widgets. Each collector reads its store fresh and raises on a
# broken one — the hub catches per tile.
# ---------------------------------------------------------------------------


def _tile_reminders() -> list[TileLine]:
    from mait_code.tools.reminders.db import get_connection
    from mait_code.tools.reminders.service import active_reminders

    conn = get_connection()
    try:
        overdue, upcoming = active_reminders(conn)
    finally:
        conn.close()
    if not overdue and not upcoming:
        return [TileLine("nothing pending", "dim")]
    lines: list[TileLine] = []
    if overdue:
        lines.append(TileLine(f"{len(overdue)} overdue", "warn"))
        lines += [
            TileLine(f"  {r['what']} · {r['due']:%Y-%m-%d %H:%M}", "warn")
            for r in overdue[:_LIST_LIMIT]
        ]
    if upcoming:
        lines.append(TileLine(f"{len(upcoming)} upcoming", ""))
        lines += [
            TileLine(f"  {r['what']} · {r['due']:%Y-%m-%d %H:%M}", "dim")
            for r in upcoming[:_LIST_LIMIT]
        ]
    return lines


def _tile_board() -> list[TileLine]:
    from mait_code.tools.board import service
    from mait_code.tools.board.db import get_connection

    conn = get_connection()
    try:
        cards = service.list_cards(conn)
    finally:
        conn.close()
    live = [c for c in cards if c["status"] != "done"]
    if not live:
        return [TileLine("all clear", "dim")]
    in_progress = [c for c in live if c["status"] == "in_progress"]
    refined = [c for c in live if c["status"] == "refined"]
    projects = len({c["project"] for c in live})
    lines = [
        TileLine(
            f"{len(live)} live · {len(in_progress)} in progress · "
            f"{len(refined)} next up · {projects} project(s)",
            "",
        )
    ]
    lines += [
        TileLine(f"  #{c['id']} {c['title']}", "dim") for c in in_progress[:_LIST_LIMIT]
    ]
    return lines


def _tile_inbox() -> list[TileLine]:
    from mait_code.tools.inbox import service
    from mait_code.tools.inbox.db import get_connection

    conn = get_connection()
    try:
        items = service.list_items(conn)
    finally:
        conn.close()
    if not items:
        return [TileLine("inbox zero", "dim")]
    lines = [TileLine(f"{len(items)} waiting for triage", "")]
    lines += [
        TileLine(f"  {item['body'].strip().splitlines()[0]}", "dim")
        for item in items[:_LIST_LIMIT]
    ]
    return lines


def _tile_memory() -> list[TileLine]:
    from mait_code.tools.memory.db import get_connection
    from mait_code.tools.memory.review import due_for_review
    from mait_code.tools.memory.stats import collect_stats

    conn = get_connection()
    try:
        stats = collect_stats(conn)
        due = len(due_for_review(conn))
    finally:
        conn.close()
    if stats.total == 0:
        return [TileLine("nothing remembered yet", "dim")]
    lines = [
        TileLine(f"{stats.total} entries · {stats.embedded_pct}% embedded", ""),
        TileLine(f"{stats.unreflected} awaiting reflection", "dim"),
    ]
    if due:
        lines.append(TileLine(f"{due} due for review", "warn"))
    return lines


def _tile_health() -> list[TileLine]:
    from mait_code.cli._doctor import run_doctor
    from mait_code.console import GLYPH

    report = run_doctor()
    lines: list[TileLine] = []
    for check in report.checks:
        if check.level != "ok":
            style = "warn" if check.level in ("warn", "fail") else ""
            lines.append(
                TileLine(f"{GLYPH[check.level]} {check.name}: {check.message}", style)
            )
    n_ok = sum(c.level == "ok" for c in report.checks)
    lines.append(
        TileLine(
            f"{GLYPH['ok']} {n_ok}/{len(report.checks)} checks passing",
            "dim" if lines else "",
        )
    )
    return lines


def _tile_velocity() -> list[TileLine]:
    """Creation velocity: memories and cards, this week vs the one before."""
    from mait_code.tools.board.db import get_connection as board_connection
    from mait_code.tools.memory.db import get_connection as memory_connection

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    fortnight_ago = now - timedelta(days=14)

    def bucket(stamps: list[object]) -> tuple[int, int]:
        this_week = last_week = 0
        for raw in stamps:
            moment = _parse_stamp(raw)
            if moment is None:
                continue
            if moment >= week_ago:
                this_week += 1
            elif moment >= fortnight_ago:
                last_week += 1
        return this_week, last_week

    conn = memory_connection()
    try:
        mem_stamps = [
            row[0] for row in conn.execute("SELECT created_at FROM memory_entries")
        ]
    finally:
        conn.close()
    conn = board_connection()
    try:
        card_stamps = [row[0] for row in conn.execute("SELECT created_at FROM cards")]
    finally:
        conn.close()

    lines: list[TileLine] = []
    for noun, stamps in (("memories", mem_stamps), ("cards", card_stamps)):
        this_week, last_week = bucket(stamps)
        arrow = "↑" if this_week > last_week else "↓" if this_week < last_week else "→"
        lines.append(
            TileLine(f"{noun}  {this_week} this week · {last_week} last · {arrow}", "")
        )
    return lines


def _parse_stamp(raw: object) -> datetime | None:
    """A stored timestamp as an aware UTC datetime, or ``None`` if unreadable.

    Stores disagree on format — the board writes tz-aware ISO strings, memory
    writes naive ``YYYY-MM-DD HH:MM:SS`` — so parse tolerantly and treat naive
    stamps as UTC.
    """
    if not isinstance(raw, str):
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


#: Built-in widget key → (display title, collector). The collector raises on a
#: broken store; the hub catches per tile and renders an error state.
BUILTIN_WIDGETS: dict[str, tuple[str, Callable[[], list[TileLine]]]] = {
    "reminders": ("Reminders", _tile_reminders),
    "board": ("Board", _tile_board),
    "inbox": ("Inbox", _tile_inbox),
    "memory": ("Memory", _tile_memory),
    "health": ("Health", _tile_health),
    "velocity": ("Velocity", _tile_velocity),
}


def builtin_title(widget: str) -> str:
    """The display title for a built-in widget key."""
    return BUILTIN_WIDGETS[widget][0]


def builtin_tile_lines(widget: str) -> list[TileLine]:
    """Collect a built-in widget's body lines (raises on a broken store)."""
    return BUILTIN_WIDGETS[widget][1]()


# ---------------------------------------------------------------------------
# Command tiles
# ---------------------------------------------------------------------------


def run_command_tile(command: str, timeout: int) -> CommandResult:
    """Run a shell-command tile and shape its output for display.

    The command string comes verbatim from the user's own ``dashboard.toml``
    (the same trust level as a shell rc file) and runs through the shell so
    pipes and globs behave as authored.

    Args:
        command: The authored shell command.
        timeout: Seconds before the tile gives up (the
            ``dashboard-tile-timeout`` setting).

    Returns:
        Success with clipped stdout, or failure with a one-line diagnosis —
        never raises.
    """
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(False, f"timed out after {timeout}s")
    except OSError as exc:
        return CommandResult(False, f"could not run: {exc}")
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()
        tail = f": {detail[-1]}" if detail else ""
        return CommandResult(False, f"exited {proc.returncode}{tail}")
    lines = proc.stdout.rstrip().splitlines()
    if len(lines) > MAX_OUTPUT_LINES:
        clipped = len(lines) - MAX_OUTPUT_LINES
        lines = lines[:MAX_OUTPUT_LINES] + [f"… {clipped} more line(s)"]
    return CommandResult(True, "\n".join(lines) if lines else "(no output)")


# ---------------------------------------------------------------------------
# Editable model — the setup TUI's working copy, round-tripped via tomlkit
# so hand-authored comments and formatting survive an edit.
# ---------------------------------------------------------------------------


@dataclass
class EditableTile:
    """A mutable tile row in the setup editor.

    The private ``table`` field holds the tomlkit table this tile was loaded
    from (``None`` for tiles added in the editor); reusing it on save keeps
    the comments and formatting attached to that entry.
    """

    widget: str | None = None
    command: str | None = None
    title: str = ""
    span: int = 1
    table: Any = None

    def spec(self) -> TileSpec:
        """The tile as an immutable spec, for previews."""
        return TileSpec(
            widget=self.widget, command=self.command, title=self.title, span=self.span
        )


class EditableDashboard:
    """A mutable working copy of ``dashboard.toml`` for the setup editor.

    Loads with the same tolerance as :func:`load_dashboard` (a missing file
    scaffolds from the default layout; a malformed one falls back with a
    warning and regenerates on save). :meth:`save` writes back through
    tomlkit, reusing each surviving tile's original table so comments and
    formatting ride along; only entries the editor actually changed differ.
    """

    def __init__(
        self,
        columns: int,
        tiles: list[EditableTile],
        doc: Any,
        path: Path,
        warnings: tuple[str, ...] = (),
    ) -> None:
        self.columns = columns
        self.tiles = tiles
        self.warnings = warnings
        self._doc = doc
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def load(cls, path: Path | None = None) -> EditableDashboard:
        """Read ``dashboard.toml`` into a working copy, falling back like the loader."""
        import tomlkit

        if path is None:
            path = dashboard_path()
        defaults = [EditableTile(widget=spec.widget) for spec in default_tiles()]
        if not path.exists():
            return cls(2, defaults, None, path)
        try:
            text = path.read_text(encoding="utf-8")
            raw = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            return cls(
                2,
                defaults,
                None,
                path,
                warnings=(
                    f"{path.name} could not be read ({exc}) — "
                    "saving will rewrite it from scratch",
                ),
            )

        warnings: list[str] = []
        columns = _parse_columns(raw.get("columns", 2), warnings)
        indexed = _parse_tiles_indexed(raw.get("tile", []), columns, warnings)
        # tomllib accepted the text, so tomlkit will too; both see the same
        # tile order, which is what makes index pairing sound.
        doc = tomlkit.parse(text)
        tables = list(doc.get("tile", []))
        tiles = [
            EditableTile(
                widget=spec.widget,
                command=spec.command,
                title=spec.title,
                span=spec.span,
                table=tables[i] if i < len(tables) else None,
            )
            for i, spec in indexed
        ]
        if warnings:
            warnings.append("saving keeps only the tiles listed in the editor")
        if not tiles:
            tiles = defaults
        return cls(columns, tiles, doc, path, warnings=tuple(warnings))

    def save(self) -> None:
        """Write the working copy back to ``dashboard.toml`` atomically."""
        import tomlkit

        doc = self._doc if self._doc is not None else _fresh_doc()
        # Only pin `columns` in the file when it matters — an authored value
        # stays put, and a non-default one gets written; a default on a fresh
        # file stays implicit so the scaffold reads minimal.
        if self.columns != 2 or "columns" in doc:
            doc["columns"] = self.columns
        aot = tomlkit.aot()
        for tile in self.tiles:
            table = tile.table if tile.table is not None else tomlkit.table()
            if tile.widget is not None:
                table["widget"] = tile.widget
                table.pop("command", None)
            else:
                table["command"] = tile.command or ""
                table.pop("widget", None)
            if tile.title:
                table["title"] = tile.title
            else:
                table.pop("title", None)
            if tile.span > 1:
                table["span"] = tile.span
            else:
                table.pop("span", None)
            tile.table = table
            aot.append(table)
        doc["tile"] = aot
        self._doc = doc
        _atomic_write(self._path, tomlkit.dumps(doc))


def _fresh_doc() -> Any:
    """A new ``dashboard.toml`` document with an orienting header."""
    import tomlkit

    doc = tomlkit.document()
    doc.add(tomlkit.comment("mait-code start page — the home hub's landing grid."))
    doc.add(
        tomlkit.comment(
            "Tiles are built-in widgets (reminders, board, inbox, memory, "
            "health, velocity)"
        )
    )
    doc.add(tomlkit.comment('or shell commands (command = "…") whose stdout shows.'))
    doc.add(tomlkit.nl())
    return doc


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* via a same-directory temp file and rename."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
