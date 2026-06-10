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
from textual.app import ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.validation import ValidationResult, Validator
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    Tree,
)
from textual.widgets.tree import TreeNode

from mait_code import config
from mait_code.cli._settings_edit import (
    SettingError,
    apply_setting,
    validation_error,
)
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.banner import BrandBanner
from mait_code.tui.confirm import ConfirmScreen

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


# Settings grouped into the tree's top-level categories, in display order.
# Every settable/derived key lands under exactly one group; the three scoring
# weights collapse into the single _WEIGHTS_KEY row under "Scoring & dedup".
# A test pins this taxonomy against config.SETTINGS so a new setting can't slip
# in uncategorised.
_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("General", ("data-dir", "theme")),
    ("Logging", ("log-level", "log-file", "log-backup-count")),
    (
        "Embeddings",
        (
            "embedding-provider",
            "embedding-model",
            "bedrock-model-id",
            "bedrock-region",
        ),
    ),
    (
        "Models",
        (
            "extraction-model",
            "reflection-model",
            "llm-timeout",
            "git-timeout",
            "reflection-batch-size",
            "reflection-novelty-gate",
        ),
    ),
    (
        "Scoring & dedup",
        (
            _WEIGHTS_KEY,
            "half-life-episodic",
            "half-life-semantic",
            "half-life-procedural",
            "dedup-string-threshold",
            "dedup-vector-threshold",
            "dedup-conflict-threshold",
            "scope-boost-global",
            "scope-boost-cross-project",
        ),
    ),
    (
        "Paths (derived)",
        (
            "embedding-dim",
            "memory-db-path",
            "reminders-db-path",
            "model-cache-dir",
            "observations-dir",
            "project-aliases-path",
        ),
    ),
)

# Common groups open on boot; advanced/derived groups start collapsed to keep
# the initial list short.
_EXPANDED_GROUPS = frozenset({"General", "Logging", "Embeddings"})

# Leaf labels render "<key>  <value>" on one line. The key column is padded to
# this width so values line up down the tree; the value is then truncated to
# what's left of a comfortable half-pane.
_KEY_WIDTH = 26
_VALUE_WIDTH = 26
_MIGRATION_MARK = " ⚠"


def _truncate(text: str, width: int = _VALUE_WIDTH) -> str:
    """Clip *text* to *width*, marking truncation with an ellipsis."""
    return text if len(text) <= width else text[: width - 1] + "…"


def _leaf_label(key: str, value_width: int = _VALUE_WIDTH) -> Text:
    """Build a tree leaf's one-line label: padded key + inline current value.

    Defaults (and derived values) render dimmed; the migration ⚠ marker rides
    next to the key, included in the padding so values stay column-aligned.
    """
    label = Text(no_wrap=True)

    if key == _WEIGHTS_KEY:
        weights = " / ".join(config.get(k) for k in config._WEIGHT_KEYS)
        name = "scoring weights…"
        label.append(name)
        label.append(" " * max(2, _KEY_WIDTH - len(name)))
        label.append(_truncate(weights, value_width), style="dim")
        return label

    setting = _by_key()[key]
    value, source = config.resolve(setting)

    if not setting.settable:
        # Derived rows stay navigable (the detail pane explains them) but read
        # as muted and reject edits.
        label.append(setting.key, style="dim")
        label.append(" " * max(2, _KEY_WIDTH - len(setting.key)))
        label.append(_truncate(value, value_width), style="dim")
        return label

    label.append(setting.key)
    visible = len(setting.key)
    if setting.requires_migration:
        label.append(_MIGRATION_MARK, style="yellow")
        visible += len(_MIGRATION_MARK)
    label.append(" " * max(2, _KEY_WIDTH - visible))
    label.append(
        _truncate(value, value_width), style="dim" if source == "default" else ""
    )
    return label


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
        ("escape", "escape", "Back"),
        Binding("1", "focus_list", "List", show=False),
        Binding("2", "focus_editor", "Editor", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_key: str | None = None
        self._row_order: list[str] = []
        self._setting_nodes: dict[str, TreeNode[str]] = {}

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Settings")
        with Horizontal(id="body"):
            yield Tree("settings", id="list")
            yield VerticalScroll(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        # The detail pane scrolls but shouldn't be a Tab stop — Tab should land
        # straight on the editor widget, not the container around it.
        self.query_one("#detail", VerticalScroll).can_focus = False
        tree: Tree[str] = self.query_one("#list", Tree)
        tree.show_root = False
        tree.guide_depth = 2
        for label, keys in _GROUPS:
            group = tree.root.add(label, expand=label in _EXPANDED_GROUPS)
            for key in keys:
                node = group.add_leaf(_leaf_label(key), data=key)
                self._setting_nodes[key] = node
                self._row_order.append(key)
        tree.focus()
        # Land on the first real setting rather than a category header, so the
        # detail pane shows an editor on boot. Deferred until after the first
        # refresh: the tree's visible-line map (which move_cursor indexes into)
        # isn't built until then.
        self.call_after_refresh(tree.move_cursor, self._setting_nodes["data-dir"])

    async def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        # Leaves carry their setting key as node data; category nodes carry
        # None and get a read-only summary instead of an editor.
        key = event.node.data
        if key is None:
            await self._show_group_detail(event.node)
        else:
            await self._show_detail(key)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        # Enter on a setting leaf hands focus to the detail pane's editor;
        # on a category node Tree handles expand/collapse itself.
        if event.node.data is not None:
            self._focus_editor()

    async def _show_group_detail(self, node: TreeNode[str]) -> None:
        """Render a category node's read-only summary in the detail pane."""
        self._current_key = None
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        await detail.mount(
            Label(str(node.label), classes="title"),
            Label(
                f"{len(node.children)} settings — expand and pick one to edit.",
                classes="help",
            ),
        )

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

        if setting.key == "theme":
            # The valid set is every registered theme — known only at runtime,
            # so it can't live in the (Textual-free) config schema as `choices`.
            widgets.append(
                RadioSet(
                    *(
                        RadioButton(name, value=(name == current))
                        for name in self._theme_names()
                    ),
                    id="editor",
                )
            )
        elif setting.choices:
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

    def _theme_names(self) -> list[str]:
        """Every registered theme name, sorted — the theme picker's options."""
        return sorted(self.available_themes)

    def _editor_value(self, setting: config.Setting) -> str | None:
        if setting.key == "theme":
            radio = self.query_one("#editor", RadioSet)
            idx = radio.pressed_index
            names = self._theme_names()
            return names[idx] if 0 <= idx < len(names) else None
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
        self.query_one("#list", Tree).focus()

    def action_escape(self) -> None:
        """Escape steps back to the list; pressed on the list itself, it quits.

        From the editor pane it returns focus to the settings tree; from the
        tree (nothing left to back out of) it exits — so escape always
        eventually leaves, like ``q``.
        """
        if self.query_one("#list", Tree).has_focus:
            self.exit()
        else:
            self.action_focus_list()

    def action_focus_editor(self) -> None:
        self._focus_editor()

    def get_system_commands(self, screen: Screen):
        """Expose the settings editor's actions in the Ctrl+P command palette."""
        yield from super().get_system_commands(screen)
        yield SystemCommand("Apply", "Apply the current edit", self.action_apply)
        yield SystemCommand(
            "Focus list", "Jump to the settings list", self.action_focus_list
        )
        yield SystemCommand(
            "Focus editor", "Jump to the detail editor", self.action_focus_editor
        )

    @work
    async def _edit_weights(self) -> None:
        changed = await self.push_screen_wait(WeightsScreen())
        if not changed:
            return
        self._refresh_row(_WEIGHTS_KEY)
        await self._show_detail(_WEIGHTS_KEY)

    def _refresh_row(self, key: str) -> None:
        """Re-render a single tree leaf's label in place after a change."""
        self._setting_nodes[key].set_label(_leaf_label(key))

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

        # Apply a theme change live too — apply_setting persisted it, so the
        # theme_changed_signal write is a no-op; this just recolours the editor.
        if key == "theme":
            self.theme = value

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
