"""Tests for the drain orchestration — the gate-off safety guarantee included."""

from __future__ import annotations

import argparse

import pytest

from mait_code.bridge import config as bc
from mait_code.bridge import service
from mait_code.bridge.loopback import LoopbackChannel
from mait_code.tools.inbox import service as inbox_service
from mait_code.tools.inbox.db import connection


def _inbox_count() -> int:
    with connection() as conn:
        return inbox_service.count_items(conn)


def test_run_drain_disabled_makes_no_channel_call():
    """The corporate-safety spine: gate off ⇒ the channel is never touched."""
    LoopbackChannel.seed("a", "b")
    outcome = service.run_drain()
    assert outcome.status == "disabled"
    assert LoopbackChannel.loop().drain_calls == 0
    assert _inbox_count() == 0


def test_run_drain_files_captures_when_enabled(bridge_on):
    LoopbackChannel.seed("first", "second")
    outcome = service.run_drain()
    assert outcome.status == "ok"
    assert outcome.count == 2
    assert _inbox_count() == 2
    assert LoopbackChannel.loop().drain_calls == 1


def test_run_drain_is_idempotent(bridge_on):
    LoopbackChannel.seed("one")
    assert service.run_drain().count == 1
    assert service.run_drain().count == 0  # nothing new
    assert _inbox_count() == 1
    LoopbackChannel.seed("two")
    assert service.run_drain().count == 1
    assert _inbox_count() == 2


def test_run_drain_unconfigured_channel(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "enabled")
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "ntfy")  # no config saved
    outcome = service.run_drain()
    assert outcome.status == "unconfigured"
    assert "required" in outcome.detail


def test_run_drain_swallows_channel_error(monkeypatch, bridge_on):
    class _Boom(LoopbackChannel):
        def drain(self, since):
            raise RuntimeError("network fell over")

    monkeypatch.setattr(bc, "active_channel", lambda: _Boom())
    outcome = service.run_drain()
    assert outcome.status == "error"
    assert "network fell over" in outcome.detail


def test_run_drain_skips_blank_bodies(bridge_on):
    LoopbackChannel.seed("real", "   ", "")
    outcome = service.run_drain()
    # count reports what was filed, not what the channel returned.
    assert outcome.count == 1
    assert _inbox_count() == 1


# --- CLI: mc-tool-inbox drain ----------------------------------------------


def test_cli_drain_disabled_message(capsys):
    from mait_code.tools.inbox import cli

    cli.cmd_drain(argparse.Namespace())
    assert "disabled" in capsys.readouterr().out


def test_cli_drain_reports_count(capsys, bridge_on):
    from mait_code.tools.inbox import cli

    LoopbackChannel.seed("a", "b", "c")
    cli.cmd_drain(argparse.Namespace())
    assert "Drained 3" in capsys.readouterr().out


def test_cli_drain_nothing_new(capsys, bridge_on):
    from mait_code.tools.inbox import cli

    cli.cmd_drain(argparse.Namespace())
    assert "Nothing new" in capsys.readouterr().out


def test_cli_drain_error_exits(capsys, monkeypatch, bridge_on):
    from mait_code.tools.inbox import cli

    monkeypatch.setattr(
        service, "run_drain", lambda: service.DrainOutcome("error", detail="boom")
    )
    with pytest.raises(SystemExit):
        cli.cmd_drain(argparse.Namespace())
    assert "boom" in capsys.readouterr().err
