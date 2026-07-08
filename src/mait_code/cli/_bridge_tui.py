"""Interactive Bridge configuration — a Textual TUI.

A single-screen form: the enable toggle (the corporate-safety gate, off by
default), a channel-type selector, and the selected channel's own config inputs
— rendered from :meth:`BridgeChannel.config_schema` so the form is generic over
channels, never hard-coded to ntfy. A "Test connection" button probes the
*in-form* values before saving; "Save" persists the gate + type to the settings
file and the channel config to ``bridge.json``.

Reached from the home hub (``HomeTarget.BRIDGE``) or launched directly. Requires
a TTY.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Select,
    Static,
)

from mait_code import config
from mait_code.bridge import config as bridge_config
from mait_code.bridge.base import BridgeChannel, ConfigField
from mait_code.bridge.registry import get_channel_class, selectable_channels
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.banner import BrandBanner

__all__ = ["run_bridge_editor"]

_GATE_OPTIONS = ("enabled", "disabled")


def run_bridge_editor() -> None:
    """Launch the Textual Bridge editor (blocks until the user quits)."""
    BridgeApp().run()


class BridgeApp(MaitApp):
    """Form for enabling and configuring the Bridge channel."""

    TITLE = "mait-code bridge"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_bridge.tcss"]

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("ctrl+t", "test", "Test connection"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._type = bridge_config.active_type()
        if get_channel_class(self._type) is None or _is_hidden(self._type):
            # Fall back to the first offered channel if the stored type is
            # unknown or not user-selectable (e.g. the loopback test double).
            offered = selectable_channels()
            self._type = offered[0].type_id if offered else self._type
        self._form_ready = False

    # -- Layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Bridge")
        with VerticalScroll(id="body"):
            yield Label("Bridge", classes="title")
            yield Label(
                "Capture in / notify out over a self-hosted channel. Off by "
                "default — enabling it allows network access, so keep it off "
                "where that isn't permitted.",
                classes="help",
            )

            yield Label("Status", classes="field-label")
            enabled = bridge_config.bridge_enabled()
            yield RadioSet(
                RadioButton("enabled", value=enabled),
                RadioButton("disabled", value=not enabled),
                id="gate",
            )

            yield Label("Channel", classes="field-label")
            yield Select(
                [(cls.display_name, cls.type_id) for cls in selectable_channels()],
                value=self._type,
                allow_blank=False,
                id="channel-type",
            )

            yield Vertical(id="fields")
            yield Static("", id="msg")
            with Horizontal(classes="button-row"):
                yield Button("Test connection", id="test")
                yield Button("Save", id="save", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._render_fields(self._type)
        self._form_ready = True

    # -- Dynamic field rendering ------------------------------------------

    def _render_fields(self, type_id: str) -> None:
        """(Re)build the channel-specific inputs from its config schema."""
        container = self.query_one("#fields", Vertical)
        container.remove_children()
        cls = get_channel_class(type_id)
        if cls is None:
            return
        stored = bridge_config.load_channel_config(type_id)
        widgets: list[Label | Input] = []
        for field in cls.config_schema():
            widgets.append(Label(_field_label(field), classes="field-label"))
            widgets.append(
                Input(
                    value=stored.get(field.key, ""),
                    placeholder=field.placeholder,
                    password=field.secret,
                    id=f"field-{field.key}",
                )
            )
        container.mount(*widgets)

    def on_select_changed(self, event: Select.Changed) -> None:
        # Select posts a Changed for its initial value on mount — ignore that
        # and any no-op re-selection of the current type.
        if not self._form_ready or event.value == self._type:
            return
        self._type = str(event.value)
        self._render_fields(self._type)
        self.query_one("#msg", Static).update("")

    # -- Reading the form --------------------------------------------------

    def _field_values(self) -> dict[str, str]:
        cls = get_channel_class(self._type)
        if cls is None:
            return {}
        values: dict[str, str] = {}
        for field in cls.config_schema():
            values[field.key] = self.query_one(f"#field-{field.key}", Input).value
        return values

    def _gate_value(self) -> str:
        idx = self.query_one("#gate", RadioSet).pressed_index
        return _GATE_OPTIONS[idx] if 0 <= idx < len(_GATE_OPTIONS) else "disabled"

    def _build_channel(self) -> BridgeChannel:
        """Build a channel from the current in-form values (may raise ValueError)."""
        return bridge_config.build_channel(self._type, self._field_values())

    # -- Actions -----------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        elif event.button.id == "test":
            self.action_test()

    def action_test(self) -> None:
        self._run_test()

    @work(exclusive=True)
    async def _run_test(self) -> None:
        msg = self.query_one("#msg", Static)
        try:
            channel = self._build_channel()
        except ValueError as exc:
            msg.update(f"✗ {exc}")
            return
        msg.update("… testing")
        result = await asyncio.to_thread(channel.test_connection)
        msg.update(("✓ " if result.ok else "✗ ") + result.message)

    def action_save(self) -> None:
        gate = self._gate_value()
        values = self._field_values()
        msg = self.query_one("#msg", Static)

        # Refuse to save an enabled Bridge with required fields blank — the
        # drain would only no-op and warn. A disabled Bridge saves freely.
        if gate == "enabled":
            missing = bridge_config.missing_required(self._type, values)
            if missing:
                msg.update(f"✗ fill required field(s): {', '.join(missing)}")
                return

        bridge_config.save_channel_config(self._type, values)
        file_values = config.read_settings_file()
        file_values["bridge"] = gate
        file_values["bridge-type"] = self._type
        config.write_settings_file(file_values)
        config.reset_cache()

        msg.update(f"✓ saved — Bridge {gate}")
        self.notify(f"Bridge {gate}", title="Saved")


def _is_hidden(type_id: str) -> bool:
    cls = get_channel_class(type_id)
    return bool(cls and cls.hidden)


def _field_label(field: ConfigField) -> str:
    label = field.label if field.required else f"{field.label} (optional)"
    return f"{label}\n{field.help}" if field.help else label
