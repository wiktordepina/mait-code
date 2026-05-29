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

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.validation import ValidationResult, Validator
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RadioButton,
    RadioSet,
    Static,
)

from mait_code import config
from mait_code.cli._settings_edit import (
    SettingError,
    apply_setting,
    validation_error,
)

__all__ = ["run_interactive_editor"]


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


class SettingRow(ListItem):
    """A single list row, carrying the setting key it represents."""

    def __init__(self, key: str) -> None:
        self.setting_key = key
        setting = _by_key()[key]
        # Derived rows stay navigable (so the detail pane can explain them) but
        # are visually dimmed and reject edits.
        super().__init__(
            Label(self._row_text()),
            classes="" if setting.settable else "derived",
        )

    def _row_text(self) -> str:
        setting = _by_key()[self.setting_key]
        value, source = config.resolve(setting)
        marker = " ⚠" if setting.requires_migration else ""
        if not setting.settable:
            return f"{setting.key:<26} {value}  ·  read-only"
        return f"{setting.key:<26} {value:<22} {source}{marker}"

    def refresh_row(self) -> None:
        self.query_one(Label).update(self._row_text())


class ConfirmScreen(ModalScreen[bool]):
    """A yes/no modal; ``push_screen_wait`` resolves to the chosen bool."""

    BINDINGS = [("escape", "dismiss_no", "No")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._question, id="question")
            with Horizontal(id="buttons"):
                yield Button("Yes", id="yes", variant="primary")
                yield Button("No", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_dismiss_no(self) -> None:
        self.dismiss(False)


class SettingsApp(App[None]):
    """Master–detail editor for the mait-code settings registry."""

    TITLE = "mait-code settings"

    CSS = """
    #body { height: 1fr; }
    #list { width: 42%; border-right: solid $panel; }
    #list .derived { color: $text-muted; }
    #detail { width: 1fr; padding: 1 2; }
    #detail .title { text-style: bold; color: $accent; }
    #detail .help { color: $text-muted; margin-bottom: 1; }
    #detail #source { color: $text-muted; margin-top: 1; }
    #detail #msg { margin-top: 1; }
    #detail #apply { margin-top: 1; }
    ConfirmScreen { align: center middle; }
    ConfirmScreen #dialog {
        width: 60; height: auto; padding: 1 2;
        border: thick $accent; background: $surface;
    }
    ConfirmScreen #buttons { height: auto; margin-top: 1; align-horizontal: right; }
    ConfirmScreen Button { margin-left: 2; }
    """

    BINDINGS = [
        ("ctrl+s", "apply", "Apply"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_key: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield ListView(*self._build_rows(), id="list")
            yield VerticalScroll(id="detail")
        yield Footer()

    def _build_rows(self) -> list[SettingRow]:
        rows: list[SettingRow] = []
        for setting in config.SETTINGS:
            if setting.key in config._WEIGHT_KEYS:
                continue  # grouped weight editor lands in a later commit
            rows.append(SettingRow(setting.key))
        return rows

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if isinstance(item, SettingRow):
            await self._show_detail(item.setting_key)

    async def _show_detail(self, key: str) -> None:
        self._current_key = key
        setting = _by_key()[key]
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()

        widgets: list[Static | Input | RadioSet | Button] = [
            Label(setting.key, classes="title"),
            Label(setting.help, classes="help"),
        ]
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
        # panel rebuild (the new row may have no #msg slot, e.g. a derived one).
        if self._current_key is None:
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

    def action_apply(self) -> None:
        if self._current_key is not None:
            self._apply(self._current_key)

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
        row = self.query_one("#list", ListView).highlighted_child
        if isinstance(row, SettingRow):
            row.refresh_row()
        _, source = config.resolve(setting)
        self.query_one("#source", Static).update(f"source: {source}")
        warnings = getattr(outcome, "warnings", []) or []
        note = "✓ applied"
        if warnings:
            note += "  ⚠ " + "; ".join(warnings)
        self.query_one("#msg", Static).update(note)
