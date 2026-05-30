"""Interactive ``mait-code settings`` editor — a Textual TUI.

A full-screen master–detail app: a settings list on the left, an inline edit
form on the right that adapts to the highlighted setting (a radio set for
enums, a validated input for free text, read-only for derived values). Every
write delegates to :func:`~mait_code.cli._settings_edit.apply_setting`, so the
TUI owns none of the validation/persist/enforce/follow-up logic — it is pure
presentation over the shared core.

Destructive follow-ups are confirmed in a modal: a ``data-dir`` move runs
inline (a fast rename); a re-embed drops out via :meth:`App.suspend` so
``run_reindex`` prints its normal progress to the terminal, then returns.

Requires a TTY; the bare ``settings`` callback only routes here when attached
to one, falling back to the read-only list otherwise.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.validation import ValidationResult, Validator
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
)
from textual.widgets.data_table import ColumnKey

from mait_code import config
from mait_code.cli._settings_edit import (
    SettingError,
    apply_setting,
    validation_error,
)
from mait_code.tui.app import SHARED_TCSS, MaitApp

__all__ = ["run_interactive_editor"]

_WEIGHTS_KEY = "__weights__"
"""Sentinel list-row key for the grouped scoring-weight editor."""


def run_interactive_editor() -> None:
    """Launch the Textual settings editor (blocks until the user quits)."""
    SettingsApp().run()


def _by_key() -> dict[str, config.Setting]:
    return {s.key: s for s in config.SETTINGS}


class _LiveValidator(Validator):
    """Adapt a Setting's validation rules to Textual's live ``Input`` check."""

    def __init__(self, setting: config.Setting) -> None:
        super().__init__()
        self._setting = setting

    def validate(self, value: str) -> ValidationResult:
        msg = validation_error(self._setting, value)
        return self.success() if msg is None else self.failure(msg)


# Source only ever holds these words, so the column is sized to the longest
# ("settings"). The migration marker rides on the Setting column instead, so it
# costs the wider Value column nothing.
_SETTING_WIDTH = 26
_SOURCE_WIDTH = 8
_VALUE_WIDTH = 26
_MIGRATION_MARK = " ⚠"


def _truncate(text: str, width: int = _VALUE_WIDTH) -> str:
    """Clip *text* to *width*, marking truncation with an ellipsis."""
    return text if len(text) <= width else text[: width - 1] + "…"


def _row_cells(key: str, value_width: int = _VALUE_WIDTH) -> tuple[Text, Text, Text]:
    """Return the (setting, value, source) cells for a settings-table row.

    *value_width* is the current width of the (flexing) Value column, used to
    truncate the value with an ellipsis so it never overflows.
    """
    if key == _WEIGHTS_KEY:
        weights = " / ".join(config.get(k) for k in config._WEIGHT_KEYS)
        return (
            Text("scoring weights…"),
            Text(_truncate(weights, value_width)),
            Text("grouped", style="cyan"),
        )

    setting = _by_key()[key]
    value, source = config.resolve(setting)

    if not setting.settable:
        # Derived rows stay navigable (the detail pane explains them) but read
        # as muted and reject edits.
        return (
            Text(setting.key, style="dim"),
            Text(_truncate(value, value_width), style="dim"),
            Text("derived", style="dim"),
        )

    setting_cell = Text(setting.key)
    if setting.requires_migration:
        setting_cell.append(_MIGRATION_MARK, style="yellow")
    value_style = "dim" if source == "default" else ""
    source_cell = Text(source, style="dim" if source == "default" else "")
    return (
        setting_cell,
        Text(_truncate(value, value_width), style=value_style),
        source_cell,
    )


class ConfirmScreen(ModalScreen[bool]):
    """A yes/no modal; ``push_screen_wait`` resolves to the chosen bool."""

    BINDINGS = [("escape", "dismiss_no", "No")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(self._question, classes="modal-title")
            with Horizontal(classes="modal-buttons"):
                yield Button("Yes", id="yes", variant="primary")
                yield Button("No", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_dismiss_no(self) -> None:
        self.dismiss(False)


class WeightsScreen(ModalScreen[bool]):
    """Retune all three scoring weights at once; Apply gated on a sum of 1.0.

    Resolves to ``True`` when the weights were written, ``False`` on cancel.
    A single combined write avoids the transient invalid sum that ``set``
    refuses piecemeal.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("Scoring weights — must sum to 1.0", classes="modal-title")
            for key in config._WEIGHT_KEYS:
                yield Label(key, classes="weight-label")
                yield Input(
                    value=config.get(key),
                    id=f"w-{key}",
                    validators=[_LiveValidator(_by_key()[key])],
                )
            yield Static("", id="weights-sum")
            with Horizontal(classes="modal-buttons"):
                yield Button("Apply", id="w-apply", variant="primary", disabled=True)
                yield Button("Cancel", id="w-cancel")

    def on_mount(self) -> None:
        self._recompute()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._recompute()

    def _recompute(self) -> None:
        total = 0.0
        parseable = True
        for key in config._WEIGHT_KEYS:
            raw = self.query_one(f"#w-{key}", Input).value
            try:
                total += float(raw)
            except (TypeError, ValueError):
                parseable = False
        valid = parseable and abs(total - 1.0) <= 1e-6
        summary = self.query_one("#weights-sum", Static)
        if not parseable:
            summary.update("sum: (enter three numbers)")
        else:
            summary.update(f"sum: {total:.3f}  {'✓' if valid else '✗ must be 1.0'}")
        self.query_one("#w-apply", Button).disabled = not valid

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "w-apply":
            self._save()
            self.dismiss(True)
        elif event.button.id == "w-cancel":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _save(self) -> None:
        values = config.read_settings_file()
        for key in config._WEIGHT_KEYS:
            values[key] = self.query_one(f"#w-{key}", Input).value
        config.write_settings_file(values)
        config._settings_cache = None


class SettingsApp(MaitApp):
    """Master–detail editor for the mait-code settings registry."""

    TITLE = "mait-code settings"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_settings.tcss"]

    BINDINGS = [
        ("ctrl+s", "apply", "Apply"),
        ("escape", "focus_list", "Back to list"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_key: str | None = None
        self._row_order: list[str] = []
        self._value_width = _VALUE_WIDTH
        self._value_col: ColumnKey | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield DataTable(id="list", cursor_type="row", zebra_stripes=True)
            yield VerticalScroll(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        # The detail pane scrolls but shouldn't be a Tab stop — Tab should land
        # straight on the editor widget, not the container around it.
        self.query_one("#detail", VerticalScroll).can_focus = False
        table = self.query_one("#list", DataTable)
        table.add_column("Setting", width=_SETTING_WIDTH, key="k")
        self._value_col = table.add_column("Value", width=self._value_width, key="v")
        table.add_column("Source", width=_SOURCE_WIDTH, key="s")
        for key in self._ordered_keys():
            table.add_row(*_row_cells(key, self._value_width), key=key)
            self._row_order.append(key)
        table.focus()
        # Size the Value column to fill the half once the layout is known.
        self.call_after_refresh(self._fit_value_column)

    def on_resize(self) -> None:
        self._fit_value_column()

    def _fit_value_column(self) -> None:
        """Flex the Value column to fill the list pane's remaining width."""
        if not self._row_order or self._value_col is None:
            return
        table = self.query_one("#list", DataTable)
        available = table.scrollable_content_region.width
        if available <= 0:
            return
        # Reserve the two fixed columns (and per-column padding) and give the
        # rest to Value. A small floor keeps Source visible rather than letting
        # Value push it off the edge on a narrow pane.
        pad = table.cell_padding * 2
        value_width = max(
            8, available - (_SETTING_WIDTH + pad) - (_SOURCE_WIDTH + pad) - pad
        )
        if value_width == self._value_width:
            return
        self._value_width = value_width
        table.columns[self._value_col].width = value_width
        for key in self._row_order:
            table.update_cell(key, "v", _row_cells(key, value_width)[1])
        table.refresh(layout=True)

    def _ordered_keys(self) -> list[str]:
        """Row keys in display order: the three weights collapse into one row."""
        keys: list[str] = []
        weights_added = False
        for setting in config.SETTINGS:
            if setting.key in config._WEIGHT_KEYS:
                if not weights_added:
                    keys.append(_WEIGHTS_KEY)
                    weights_added = True
                continue
            keys.append(setting.key)
        return keys

    async def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        key = event.row_key.value
        if key is not None:
            await self._show_detail(key)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Enter on a row hands focus to the detail pane's editor.
        self._focus_editor()

    def _focus_editor(self) -> None:
        for selector in ("#editor", "#edit-weights", "#apply"):
            found = self.query(selector)
            if found:
                found.first().focus()
                return

    async def _show_detail(self, key: str) -> None:
        self._current_key = key
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()

        if key == _WEIGHTS_KEY:
            current = ", ".join(
                f"{k.removeprefix('score-weight-')}={config.get(k)}"
                for k in config._WEIGHT_KEYS
            )
            await detail.mount(
                Label("scoring weights", classes="title"),
                Label(
                    "Three weights that must sum to 1.0; edited together.",
                    classes="help",
                ),
                Static(current),
                Button("Edit weights…", id="edit-weights", variant="primary"),
            )
            return

        setting = _by_key()[key]
        widgets: list[Static | Input | RadioSet | Button] = [
            Label(setting.key, classes="title"),
            Label(setting.help, classes="help"),
        ]
        if setting.requires_migration:
            widgets.append(
                Static(
                    "⚠ Changing this re-embeds all stored memories "
                    "(rebuilds the vector table from preserved text — no data "
                    "loss, but it takes a moment).",
                    classes="warn-note",
                )
            )
        current, source = config.resolve(setting)

        if not setting.settable:
            widgets.append(Static(f"{current}", classes="value"))
            widgets.append(Static("derived — computed, not editable", id="source"))
            await detail.mount(*widgets)
            return

        if setting.choices:
            widgets.append(
                RadioSet(
                    *(RadioButton(c, value=(c == current)) for c in setting.choices),
                    id="editor",
                )
            )
        else:
            widgets.append(
                Input(value=current, validators=[_LiveValidator(setting)], id="editor")
            )
        widgets.append(Static(f"source: {source}", id="source"))
        widgets.append(Static("", id="msg"))
        widgets.append(Button("Apply", id="apply", variant="primary"))
        await detail.mount(*widgets)

    # -- editing -----------------------------------------------------------

    def _editor_value(self, setting: config.Setting) -> str | None:
        if setting.choices:
            radio = self.query_one("#editor", RadioSet)
            idx = radio.pressed_index
            return setting.choices[idx] if idx >= 0 else None
        return self.query_one("#editor", Input).value

    def on_input_changed(self, event: Input.Changed) -> None:
        # Ignore stray Changed events from an input being torn down during a
        # panel rebuild (the new row may have no #msg slot, e.g. a derived one),
        # and the weights modal's own inputs (it validates them itself).
        if self._current_key is None or self._current_key == _WEIGHTS_KEY:
            return
        editors = self.query("#editor")
        msg_slots = self.query("#msg")
        if not editors or not msg_slots or event.input is not editors.first():
            return
        setting = _by_key()[self._current_key]
        msg = validation_error(setting, event.value)
        msg_slots.first(Static).update("" if msg is None else f"✗ {msg}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_apply()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            self.action_apply()
        elif event.button.id == "edit-weights":
            self._edit_weights()

    def action_apply(self) -> None:
        if self._current_key == _WEIGHTS_KEY:
            self._edit_weights()
        elif self._current_key is not None:
            self._apply(self._current_key)

    def action_focus_list(self) -> None:
        self.query_one("#list", DataTable).focus()

    @work
    async def _edit_weights(self) -> None:
        changed = await self.push_screen_wait(WeightsScreen())
        if not changed:
            return
        self._refresh_row(_WEIGHTS_KEY)
        await self._show_detail(_WEIGHTS_KEY)

    def _refresh_row(self, key: str) -> None:
        """Re-render a single table row's cells in place after a change."""
        table = self.query_one("#list", DataTable)
        cells = _row_cells(key, self._value_width)
        for column_key, cell in zip(("k", "v", "s"), cells):
            table.update_cell(key, column_key, cell)

    @work
    async def _apply(self, key: str) -> None:
        setting = _by_key()[key]
        if not setting.settable:
            return
        value = self._editor_value(setting)
        if value is None:
            return

        msg = validation_error(setting, value)
        if msg is not None:
            self.query_one("#msg", Static).update(f"✗ {msg}")
            return

        reindex: bool | None = None
        move_data: bool | None = None
        run_reindex_after = False

        if setting.requires_migration:
            confirmed = await self.push_screen_wait(
                ConfirmScreen(
                    "Re-embed all memories now? This rebuilds the vector table."
                )
            )
            reindex = False  # persist now; we run the slow re-embed ourselves
            run_reindex_after = confirmed
        elif key == "data-dir":
            move_data = await self.push_screen_wait(
                ConfirmScreen(f"Move existing data to {value}?")
            )

        try:
            outcome = apply_setting(key, value, reindex=reindex, move_data=move_data)
        except SettingError as exc:
            self.query_one("#msg", Static).update(f"✗ {exc}")
            return

        if run_reindex_after:
            self._run_reindex_suspended()

        self._after_apply(setting, outcome)

    def _run_reindex_suspended(self) -> None:
        """Drop out of the app to re-embed with normal terminal output."""
        from mait_code.tools.memory.cli import ReindexError, run_reindex

        with self.suspend():
            try:
                run_reindex()
            except ReindexError as exc:
                print(f"\nReindex failed: {exc}")
            input("\nPress Enter to return to settings… ")

    def _after_apply(self, setting: config.Setting, outcome: object) -> None:
        self._refresh_row(setting.key)
        _, source = config.resolve(setting)
        self.query_one("#source", Static).update(f"source: {source}")
        warnings = getattr(outcome, "warnings", []) or []
        note = "✓ applied"
        if warnings:
            note += "  ⚠ " + "; ".join(warnings)
        self.query_one("#msg", Static).update(note)
