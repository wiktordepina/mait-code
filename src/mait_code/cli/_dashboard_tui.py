"""Interactive start-page setup — edit ``dashboard.toml`` as a form.

A two-pane editor over :class:`~mait_code.cli._dashboard.EditableDashboard`:
the tile list and the grid's column count on the left; the selected tile's
form — widget picker or command input, title, span — with a live preview on
the right. Add, remove and reorder tiles; ``Ctrl+S`` writes the file back
through tomlkit, so hand-authored comments and formatting survive.

Two deliberate safety choices. **Command text is never executed while being
typed** — a command tile's preview runs only on ``Ctrl+R``, so a half-typed
``rm``-anything can't fire; built-in widgets preview live because they only
read the stores. And quitting with unsaved changes asks first.

``Ctrl+E`` is the escape hatch for anything the form doesn't cover: it saves,
suspends the app, opens the file in ``$EDITOR``, and reloads the working copy
on return.

Reached from the home hub (``HomeTarget.DASHBOARD``). Requires a TTY.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Footer,
    Input,
    Label,
    OptionList,
    RadioButton,
    RadioSet,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from mait_code.cli import _dashboard as dashboard
from mait_code.config import get_int
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.banner import BrandBanner
from mait_code.tui.confirm import ConfirmScreen
from mait_code.tui.palette import rich_colour as _rich_colour

__all__ = ["DashboardSetupApp", "run_dashboard_setup"]


def run_dashboard_setup() -> None:
    """Launch the start-page setup editor (blocks until the user quits)."""
    DashboardSetupApp().run()


#: RadioSet order for the tile-type toggle.
_TYPES = ("widget", "command")

#: Placeholder shown for a command tile until the user runs its preview.
_COMMAND_PREVIEW_HINT = "Ctrl+R runs the command and previews its output."


class DashboardSetupApp(MaitApp):
    """Form editor for the home hub's start page (``dashboard.toml``)."""

    TITLE = "mait-code start page"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_dashboard_setup.tcss"]

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("a", "add_tile", "Add tile"),
        ("d", "remove_tile", "Remove"),
        ("shift+up", "move_up", "Move ↑"),
        ("shift+down", "move_down", "Move ↓"),
        ("ctrl+r", "preview_command", "Run preview"),
        ("ctrl+e", "open_editor", "Edit raw"),
        # Take over the base quit keys so leaving asks about unsaved changes.
        Binding("q", "request_quit", "Quit"),
        Binding("escape", "request_quit", "Quit", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._model = dashboard.EditableDashboard.load()
        self._selected = 0
        self._dirty = False
        # Guards the form's Changed handlers while _fill_form writes values —
        # the same trick as the Bridge editor's _form_ready.
        self._form_ready = False

    # -- Layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Start Page Setup")
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Label("Tiles", classes="title")
                yield OptionList(id="tile-list")
                yield Label("Grid columns", classes="field-label")
                yield Select(
                    [(str(n), n) for n in range(1, dashboard.MAX_COLUMNS + 1)],
                    value=self._model.columns,
                    allow_blank=False,
                    id="columns",
                )
                yield Label(
                    "a add · d remove · shift+↑/↓ reorder",
                    classes="hint",
                )
            with VerticalScroll(id="form"):
                yield Label("Tile", id="form-title", classes="title")
                yield Label("Type", classes="field-label")
                yield RadioSet(
                    RadioButton("built-in widget"),
                    RadioButton("shell command"),
                    id="type",
                )
                yield Label("Widget", classes="field-label", id="widget-label")
                # Seeded with the first tile's widget: with allow_blank=False
                # an unseeded Select snaps to its first option and posts that
                # as a Changed after mount — which would read as a user edit.
                first = self._model.tiles[0]
                yield Select(
                    [
                        (dashboard.builtin_title(key), key)
                        for key in dashboard.BUILTIN_WIDGETS
                    ],
                    value=first.widget or next(iter(dashboard.BUILTIN_WIDGETS)),
                    allow_blank=False,
                    id="widget",
                )
                yield Label("Command", classes="field-label", id="command-label")
                yield Input(
                    placeholder="df -h / | tail -1",
                    id="command",
                )
                yield Label("Title (optional)", classes="field-label")
                yield Input(placeholder="defaults to the widget's name", id="title")
                yield Label("Span (grid columns to occupy)", classes="field-label")
                yield Select(
                    [(str(n), n) for n in range(1, self._model.columns + 1)],
                    # Seeded like the widget picker: an off-model initial value
                    # would post a Changed after mount that reads as an edit.
                    value=min(first.span, self._model.columns),
                    allow_blank=False,
                    id="span",
                )
                yield Label("Preview", classes="field-label")
                yield Static(id="preview", classes="tile")
                yield Static("", id="msg")
        yield Footer()

    def on_mount(self) -> None:
        for warning in self._model.warnings:
            self.notify(warning, title="Start page", severity="warning")
        self._refresh_list()
        self._select(0)
        self.query_one("#tile-list", OptionList).focus()

    # -- Model ↔ UI sync -----------------------------------------------------

    def _tile(self) -> dashboard.EditableTile:
        return self._model.tiles[self._selected]

    def _refresh_list(self) -> None:
        """Rebuild the tile list, keeping the highlight on the selection."""
        options = self.query_one("#tile-list", OptionList)
        options.clear_options()
        for i, tile in enumerate(self._model.tiles):
            label = Text(f"{i + 1}  ")
            if tile.widget is not None:
                name = tile.title or dashboard.builtin_title(tile.widget)
                kind = "widget"
            else:
                name = tile.title or tile.command or "(empty command)"
                kind = "command"
            # The gap rides the name run — the renderer trims a styled run's
            # leading whitespace (the tree's run-whitespace gotcha).
            label.append(f"{name}  ")
            label.append(kind, style="dim")
            options.add_option(Option(label, id=str(i)))
        if self._model.tiles:
            self._selected = min(self._selected, len(self._model.tiles) - 1)
            options.highlighted = self._selected

    def _fill_form(self) -> None:
        """Write the selected tile into the form without echoing back.

        Every programmatic assignment is wrapped in ``prevent`` so no Changed
        message is posted at all — a queued fill event arriving later would
        otherwise read as a user edit and could clobber a real one (the
        ``_form_ready`` flag alone can't help, because it is back on by the
        time queued messages are delivered).
        """
        self._form_ready = False
        tile = self._tile()
        is_widget = tile.widget is not None
        self.query_one("#form-title", Label).update(
            f"Tile {self._selected + 1} of {len(self._model.tiles)}"
        )
        radio = self.query_one("#type", RadioSet)
        wanted = _TYPES.index("widget" if is_widget else "command")
        if radio.pressed_index != wanted:
            # RadioSet exposes no setter; press the matching button directly.
            buttons = list(radio.query(RadioButton))
            with radio.prevent(RadioSet.Changed):
                buttons[wanted].value = True
        if is_widget:
            widget_select = self.query_one("#widget", Select)
            with widget_select.prevent(Select.Changed):
                widget_select.value = tile.widget
        command = self.query_one("#command", Input)
        with command.prevent(Input.Changed):
            command.value = tile.command or ""
        title = self.query_one("#title", Input)
        with title.prevent(Input.Changed):
            title.value = tile.title
        self._rebuild_span_options()
        self._set_type_visibility(is_widget)
        self._form_ready = True
        self._refresh_preview()

    def _rebuild_span_options(self) -> None:
        """Span options follow the column count; the value clamps with it."""
        tile = self._tile()
        tile.span = min(tile.span, self._model.columns)
        span = self.query_one("#span", Select)
        with span.prevent(Select.Changed):
            span.set_options((str(n), n) for n in range(1, self._model.columns + 1))
            span.value = tile.span

    def _set_type_visibility(self, is_widget: bool) -> None:
        for selector, shown in (
            ("#widget-label", is_widget),
            ("#widget", is_widget),
            ("#command-label", not is_widget),
            ("#command", not is_widget),
        ):
            self.query_one(selector).display = shown

    def _select(self, index: int) -> None:
        self._selected = max(0, min(index, len(self._model.tiles) - 1))
        options = self.query_one("#tile-list", OptionList)
        if options.highlighted != self._selected:
            options.highlighted = self._selected
        self._fill_form()

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.query_one("#msg", Static).update(
            Text("unsaved changes — Ctrl+S to save", style="dim")
        )

    # -- Preview -------------------------------------------------------------

    def _warn_colour(self) -> str:
        from mait_code.tui import palette

        theme = self.get_theme(self.theme)
        return _rich_colour(theme.warning if theme else None, palette.WARNING)

    def _refresh_preview(self) -> None:
        """Render the selected tile's preview — live only for widget tiles."""
        preview = self.query_one("#preview", Static)
        tile = self._tile()
        preview.border_title = tile.title or (
            dashboard.builtin_title(tile.widget)
            if tile.widget is not None
            else _clip_command(tile.command)
        )
        preview.remove_class("tile-error")
        if tile.widget is None:
            preview.update(Text(_COMMAND_PREVIEW_HINT, style="dim"))
            return
        try:
            lines = dashboard.builtin_tile_lines(tile.widget)
        except Exception as exc:  # noqa: BLE001 — a broken store is preview content
            preview.update(Text(f"couldn't read: {exc}", style=self._warn_colour()))
            preview.add_class("tile-error")
            return
        body = Text()
        styles = {"": "", "dim": "dim", "warn": self._warn_colour()}
        for i, line in enumerate(lines):
            if i:
                body.append("\n")
            body.append(line.text, style=styles.get(line.style, ""))
        preview.update(body)

    def action_preview_command(self) -> None:
        tile = self._tile()
        if tile.widget is not None:
            return  # widget previews are already live
        if not (tile.command or "").strip():
            self.notify("Type a command first.", title="Preview")
            return
        preview = self.query_one("#preview", Static)
        preview.update(Text("⧗ running…", style="dim"))
        self._run_preview(tile.command or "", self._selected)

    @work(thread=True, group="setup-preview", exclusive=True)
    def _run_preview(self, command: str, index: int) -> None:
        result = dashboard.run_command_tile(command, get_int("dashboard-tile-timeout"))
        try:
            self.call_from_thread(self._apply_preview, result, index)
        except RuntimeError:
            pass  # the app closed while the command ran

    def _apply_preview(self, result: dashboard.CommandResult, index: int) -> None:
        if index != self._selected:  # selection moved on while it ran
            return
        preview = self.query_one("#preview", Static)
        if result.ok:
            preview.remove_class("tile-error")
            preview.update(Text(result.output))
        else:
            preview.add_class("tile-error")
            preview.update(Text(result.output, style=self._warn_colour()))

    # -- Form events -----------------------------------------------------------

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_id is not None and int(event.option_id) != self._selected:
            self._selected = int(event.option_id)
            self._fill_form()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if not self._form_ready or event.radio_set.id != "type":
            return
        tile = self._tile()
        want_widget = _TYPES[event.index] == "widget"
        if want_widget == (tile.widget is not None):
            return
        if want_widget:
            tile.command = None
            tile.widget = str(self.query_one("#widget", Select).value)
        else:
            tile.widget = None
            tile.command = self.query_one("#command", Input).value.strip()
        self._set_type_visibility(want_widget)
        self._mark_dirty()
        self._refresh_list()
        self._refresh_preview()

    def on_select_changed(self, event: Select.Changed) -> None:
        if not self._form_ready:
            return
        if event.select.id == "widget":
            tile = self._tile()
            if tile.widget is not None and tile.widget != event.value:
                tile.widget = str(event.value)
                self._mark_dirty()
                self._refresh_list()
                self._refresh_preview()
        elif event.select.id == "span":
            tile = self._tile()
            if tile.span != event.value:
                tile.span = int(str(event.value))
                self._mark_dirty()
        elif event.select.id == "columns":
            if self._model.columns != event.value:
                self._model.columns = int(str(event.value))
                self._rebuild_span_options()
                self._mark_dirty()

    def on_input_changed(self, event: Input.Changed) -> None:
        # _fill_form's value assignments deliver their Changed events after
        # _form_ready is back on, so a no-op guard against the model is what
        # actually keeps programmatic fills from reading as user edits.
        if not self._form_ready:
            return
        tile = self._tile()
        if event.input.id == "command" and tile.widget is None:
            if event.value.strip() == (tile.command or ""):
                return
            tile.command = event.value.strip()
            self._mark_dirty()
            self._refresh_list()
            # Deliberately no execution here — the preview stays a hint until
            # the user presses Ctrl+R on the finished command.
            self.query_one("#preview", Static).border_title = tile.title or (
                _clip_command(tile.command)
            )
        elif event.input.id == "title":
            if event.value.strip() == tile.title:
                return
            tile.title = event.value.strip()
            self._mark_dirty()
            self._refresh_list()
            if tile.widget is not None:
                self._refresh_preview()
            else:
                self.query_one("#preview", Static).border_title = tile.title or (
                    _clip_command(tile.command)
                )

    # -- Tile actions ------------------------------------------------------------

    def action_add_tile(self) -> None:
        self._model.tiles.insert(
            self._selected + 1 if self._model.tiles else 0,
            dashboard.EditableTile(widget="reminders"),
        )
        self._mark_dirty()
        self._refresh_list()
        self._select(self._selected + 1 if len(self._model.tiles) > 1 else 0)

    def action_remove_tile(self) -> None:
        if len(self._model.tiles) <= 1:
            self.notify("The grid needs at least one tile.", title="Start page")
            return
        del self._model.tiles[self._selected]
        self._mark_dirty()
        self._refresh_list()
        self._select(self._selected)

    def action_move_up(self) -> None:
        self._move(-1)

    def action_move_down(self) -> None:
        self._move(1)

    def _move(self, delta: int) -> None:
        i, j = self._selected, self._selected + delta
        if not 0 <= j < len(self._model.tiles):
            return
        tiles = self._model.tiles
        tiles[i], tiles[j] = tiles[j], tiles[i]
        self._selected = j
        self._mark_dirty()
        self._refresh_list()

    # -- Save / quit / raw edit ---------------------------------------------------

    def action_save(self) -> None:
        try:
            self._model.save()
        except OSError as exc:
            self.notify(f"Couldn't save: {exc}", title="Start page", severity="error")
            return
        self._dirty = False
        self.query_one("#msg", Static).update("")
        self.notify(f"Saved {self._model.path.name}", title="Start page")

    @work
    async def action_request_quit(self) -> None:
        if self._dirty:
            confirmed = await self.push_screen_wait(
                ConfirmScreen("Discard unsaved changes?")
            )
            if not confirmed:
                return
        self.exit()

    def action_open_editor(self) -> None:
        """Save, drop to ``$EDITOR`` on the file, and reload on return."""
        self.action_save()
        if self._dirty:  # the save failed and said so; stay put
            return
        editor = os.environ.get("EDITOR") or "vi"
        with self.suspend():
            subprocess.run([editor, str(self._model.path)], check=False)
        self._model = dashboard.EditableDashboard.load(self._model.path)
        self._selected = 0
        self._refresh_list()
        self._select(0)
        self.notify("Reloaded from file", title="Start page")


def _clip_command(command: str | None, width: int = 40) -> str:
    text = (command or "").strip() or "(empty command)"
    return text if len(text) <= width else text[: width - 1] + "…"
