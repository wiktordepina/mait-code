"""Loopback channel — an in-memory Bridge transport for tests.

It exists to *prove the interface is real*: the gate, drain service, inbox
wiring and (later) the reminders publish are all exercised end-to-end without a
live server. It also backs the "gate off ⇒ no network" test — a
:class:`LoopbackChannel` records every ``drain``/``publish`` call, so a test can
assert the channel was never touched while the gate was disabled.

Hidden from the user-facing channel picker (:attr:`hidden`), but selectable by
id (``bridge-type = loopback``) so tests can route through it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from mait_code.bridge.base import (
    BridgeChannel,
    Capture,
    ConfigField,
    DrainResult,
    OutboundMessage,
    TestResult,
)

__all__ = ["LoopbackChannel"]


@dataclass
class _Loop:
    """Shared in-memory state for one named loopback channel."""

    messages: list[str] = field(default_factory=list)
    published: list[OutboundMessage] = field(default_factory=list)
    drain_calls: int = 0
    healthy: bool = True


class LoopbackChannel(BridgeChannel):
    """An in-memory transport whose queue is seeded and inspected by tests."""

    type_id = "loopback"
    display_name = "Loopback (in-memory)"
    hidden = True

    # Keyed by `name` so a test and the code under test share one queue.
    _loops: ClassVar[dict[str, _Loop]] = {}

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._loop = self._loops.setdefault(name, _Loop())

    # -- Identity & config -------------------------------------------------

    @classmethod
    def config_schema(cls) -> Sequence[ConfigField]:
        return (
            ConfigField(
                "name",
                "Queue name",
                help="Which in-memory queue to attach to.",
                required=False,
                placeholder="default",
            ),
        )

    @classmethod
    def from_config(cls, config: Mapping[str, str]) -> LoopbackChannel:
        return cls(name=(config.get("name") or "default"))

    # -- Verbs -------------------------------------------------------------

    def test_connection(self) -> TestResult:
        if self._loop.healthy:
            return TestResult(True, "loopback ready")
        return TestResult(False, "loopback marked unhealthy")

    def drain(self, since: str | None) -> DrainResult:
        self._loop.drain_calls += 1
        start = int(since) if since else 0
        new = self._loop.messages[start:]
        captures = [
            Capture(body=body, external_id=str(start + i)) for i, body in enumerate(new)
        ]
        return DrainResult(captures=captures, watermark=str(len(self._loop.messages)))

    def publish(self, message: OutboundMessage) -> None:
        self._loop.published.append(message)

    # -- Test helpers ------------------------------------------------------

    @classmethod
    def reset(cls) -> None:
        """Forget all queues — call between tests."""
        cls._loops.clear()

    @classmethod
    def seed(cls, *bodies: str, name: str = "default") -> None:
        """Append inbound messages to a queue, as if published to it."""
        cls._loops.setdefault(name, _Loop()).messages.extend(bodies)

    @classmethod
    def loop(cls, name: str = "default") -> _Loop:
        """Return a queue's state for assertions (drain_calls, published, …)."""
        return cls._loops.setdefault(name, _Loop())
