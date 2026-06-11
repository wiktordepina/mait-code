"""Tests for the ``mait-code`` console-script entry point."""

from __future__ import annotations

import pytest

import mait_code.cli as cli


def test_main_applies_env_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() injects the settings [env] table — the CLI doesn't route
    through setup_logging(), so it carries its own apply_env() call."""
    order: list[str] = []
    monkeypatch.setattr(cli, "_apply_env", lambda: order.append("env"))
    monkeypatch.setattr(cli, "app", lambda: order.append("app"))
    cli.main()
    assert order == ["env", "app"]
