"""Fixtures for the Bridge tests.

The loopback channel keeps class-level queue state, so it is reset between
tests. ``setup_ssl`` is stubbed to a no-op so channel HTTP paths don't touch the
OS trust store under test.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from mait_code.bridge.loopback import LoopbackChannel


@pytest.fixture(autouse=True)
def _reset_loopback() -> Iterator[None]:
    LoopbackChannel.reset()
    yield
    LoopbackChannel.reset()


@pytest.fixture(autouse=True)
def _no_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mait_code.ssl.setup_ssl", lambda: None)


@pytest.fixture
def bridge_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the Bridge with the loopback channel selected."""
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "enabled")
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "loopback")
