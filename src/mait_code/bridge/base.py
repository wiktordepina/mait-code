"""The channel-agnostic core of the Bridge.

The Bridge moves captures *in* (a phone, another machine) and notifications
*out* (due reminders) over a pluggable transport. Everything transport-specific
lives behind :class:`BridgeChannel`; the gate, the settings form, the inbox
drain and the reminders publish are all written against this interface, so a new
transport (MQTT, a Telegram bot, …) is *only* a new subclass plus a line in the
registry — no change to the callers.

This module is deliberately dependency-light: the dataclasses and the abstract
base only. Concrete channels (:mod:`~mait_code.bridge.ntfy`,
:mod:`~mait_code.bridge.loopback`) import from here, never the reverse.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar

__all__ = [
    # Value types
    "ConfigField",
    "TestResult",
    "Capture",
    "DrainResult",
    "OutboundMessage",
    # Interface
    "BridgeChannel",
]


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigField:
    """One user-facing config input a channel needs, declared by the channel.

    The Bridge settings form renders one labelled input per field returned by
    :meth:`BridgeChannel.config_schema`, so the form is generic over channels
    rather than hard-coded to any one transport.

    Attributes:
        key: Stable identifier; the storage key within the channel's config.
        label: Human label shown beside the input.
        help: One-line hint rendered under the input.
        kind: ``"str"`` | ``"int"`` | ``"bool"`` — drives input styling/coercion.
        secret: ``True`` masks the value in displays (tokens, passwords).
        required: ``True`` means the channel cannot operate without it; a blank
            required field is what ``doctor`` warns about when the gate is on.
        placeholder: Example value shown in the empty input.
    """

    key: str
    label: str
    help: str = ""
    kind: str = "str"
    secret: bool = False
    required: bool = True
    placeholder: str = ""


@dataclass(frozen=True)
class TestResult:
    """Outcome of :meth:`BridgeChannel.test_connection` — shown inline in the form.

    Attributes:
        ok: Whether the probe round-trip succeeded.
        message: Human-readable detail (the error, or a success note).
    """

    ok: bool
    message: str


@dataclass(frozen=True)
class Capture:
    """One inbound item drained from a channel, bound for the inbox.

    Attributes:
        body: The captured text, filed verbatim into ``inbox.db``.
        external_id: The channel's own id for the source message, for tracing
            and de-duplication (empty when the transport has none).
    """

    body: str
    external_id: str = ""


@dataclass(frozen=True)
class DrainResult:
    """What a single :meth:`BridgeChannel.drain` returned.

    The watermark is *opaque to the caller*: each channel defines what it means
    (ntfy: the last message id; loopback: a running count). The drain service
    persists it verbatim per-machine and hands it back on the next drain, so
    re-drains are idempotent without the service knowing the transport.

    Attributes:
        captures: Inbound items, oldest first.
        watermark: Channel-defined resume token, or ``None`` to leave the stored
            watermark unchanged (e.g. nothing new).
    """

    captures: list[Capture] = field(default_factory=list)
    watermark: str | None = None


@dataclass(frozen=True)
class OutboundMessage:
    """A notification to publish outward (exercised by the reminders half, #78).

    Defined here so the interface is complete and both channels implement it now;
    the reminders publish path that fills in ``actions`` lands in a follow-up.

    Attributes:
        body: The notification text.
        title: Optional title/heading.
        actions: Transport-specific action descriptors (e.g. an ntfy "Done"
            button); empty for a plain notification.
    """

    body: str
    title: str | None = None
    actions: tuple[Mapping[str, str], ...] = ()


# ---------------------------------------------------------------------------
# The channel interface
# ---------------------------------------------------------------------------


class BridgeChannel(ABC):
    """A swappable Bridge transport.

    Subclasses declare their identity and config, know how to test themselves,
    and implement the two transport verbs (:meth:`drain` inbound,
    :meth:`publish` outbound). Register a subclass in
    :mod:`~mait_code.bridge.registry` and it becomes selectable everywhere the
    gate, form and hooks already handle — with no change to those callers.

    Class attributes:
        type_id: Stable, lowercase identifier (the ``bridge-type`` value).
        display_name: Human label for the channel selector.
        hidden: ``True`` keeps the channel out of the user-facing picker while
            still usable by id (the loopback test double sets this).
    """

    type_id: ClassVar[str]
    display_name: ClassVar[str]
    hidden: ClassVar[bool] = False

    @classmethod
    @abstractmethod
    def config_schema(cls) -> Sequence[ConfigField]:
        """Return the config inputs this channel needs, in display order."""

    @classmethod
    @abstractmethod
    def from_config(cls, config: Mapping[str, str]) -> BridgeChannel:
        """Build a channel from resolved config values.

        Raises:
            ValueError: If a required value is missing or malformed. Callers
                turn this into a form error or a ``doctor`` warning, never a
                crashed session.
        """

    @abstractmethod
    def test_connection(self) -> TestResult:
        """Attempt a lightweight round-trip and report the outcome.

        Must never raise: connection/credential failures come back as a
        ``TestResult(ok=False, …)`` so the form can show them inline.
        """

    @abstractmethod
    def drain(self, since: str | None) -> DrainResult:
        """Fetch inbound captures after the *since* watermark.

        Args:
            since: The opaque watermark from the previous drain, or ``None`` on
                the first drain.
        """

    @abstractmethod
    def publish(self, message: OutboundMessage) -> None:
        """Publish an outbound notification. (Reminders half — #78.)"""
