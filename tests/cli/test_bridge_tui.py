"""Tests for the Textual Bridge editor.

Drives the real app via ``run_test()`` → pilot: render the form, toggle the
gate, fill fields, test the connection, and save — asserting the config files
change. The channel library is covered under ``tests/bridge``; here we check the
TUI wiring on top of it.
"""

from __future__ import annotations

import asyncio

from textual.widgets import Input, RadioButton, RadioSet, Select, Static

from mait_code import config
from mait_code.bridge import config as bridge_config
from mait_code.bridge.base import TestResult as _TestResult
from mait_code.bridge.loopback import LoopbackChannel
from mait_code.bridge.ntfy import NtfyChannel
from mait_code.cli._bridge_tui import BridgeApp


def _run(coro_factory):
    return asyncio.run(coro_factory())


def _set_gate(app: BridgeApp, label: str) -> None:
    rs = app.query_one("#gate", RadioSet)
    for rb in rs.query(RadioButton):
        if str(rb.label) == label:
            rb.value = True


def test_initial_render_disabled_with_ntfy_fields():
    async def scenario():
        app = BridgeApp()
        async with app.run_test():
            assert app.query_one("#channel-type", Select).value == "ntfy"
            # ntfy's three fields are present…
            assert app.query_one("#field-server", Input) is not None
            assert app.query_one("#field-capture_topic", Input) is not None
            assert app.query_one("#field-token", Input).password is True
            # …and the gate defaults to disabled.
            assert app._gate_value() == "disabled"

    _run(scenario)


def test_save_disabled_persists_without_required_fields():
    async def scenario():
        app = BridgeApp()
        async with app.run_test() as pilot:
            _set_gate(app, "disabled")
            app.action_save()
            await pilot.pause()
        assert config.get("bridge") == "disabled"

    _run(scenario)


def test_save_enabled_blank_required_is_refused():
    async def scenario():
        app = BridgeApp()
        async with app.run_test() as pilot:
            _set_gate(app, "enabled")
            await pilot.pause()
            app.action_save()
            await pilot.pause()
            msg = str(app.query_one("#msg", Static).render())
            assert "required" in msg
        # Nothing was written — the gate is still its default.
        assert config.get("bridge") == "disabled"

    _run(scenario)


def test_save_enabled_persists_gate_type_and_config():
    async def scenario():
        app = BridgeApp()
        async with app.run_test() as pilot:
            app.query_one("#field-server", Input).value = "https://ntfy.example.org"
            app.query_one("#field-capture_topic", Input).value = "cap"
            app.query_one("#field-token", Input).value = "tk_123"
            _set_gate(app, "enabled")
            await pilot.pause()
            app.action_save()
            await pilot.pause()

        assert config.get("bridge") == "enabled"
        assert config.get("bridge-type") == "ntfy"
        assert bridge_config.load_channel_config("ntfy") == {
            "server": "https://ntfy.example.org",
            "capture_topic": "cap",
            "token": "tk_123",
        }

    _run(scenario)


def test_test_connection_reports_blank_config_error():
    async def scenario():
        app = BridgeApp()
        async with app.run_test() as pilot:
            app.action_test()
            await app.workers.wait_for_complete()
            await pilot.pause()
            msg = str(app.query_one("#msg", Static).render())
            assert msg.startswith("✗")

    _run(scenario)


def test_test_connection_success(monkeypatch):
    monkeypatch.setattr(
        NtfyChannel, "test_connection", lambda self: _TestResult(True, "connected")
    )

    async def scenario():
        app = BridgeApp()
        async with app.run_test() as pilot:
            app.query_one("#field-server", Input).value = "https://x"
            app.query_one("#field-capture_topic", Input).value = "cap"
            app.action_test()
            await app.workers.wait_for_complete()
            await pilot.pause()
            msg = str(app.query_one("#msg", Static).render())
            assert msg.startswith("✓") and "connected" in msg

    _run(scenario)


def test_switching_channel_rerenders_fields(monkeypatch):
    # Make the loopback double selectable so the Select offers a second option.
    monkeypatch.setattr(LoopbackChannel, "hidden", False)

    async def scenario():
        app = BridgeApp()
        async with app.run_test() as pilot:
            app.query_one("#channel-type", Select).value = "loopback"
            await pilot.pause()
            # ntfy fields gone, loopback's own field rendered.
            assert not app.query("#field-server")
            assert app.query_one("#field-name", Input) is not None

    _run(scenario)
