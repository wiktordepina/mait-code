"""The channel registry — the one place that knows every transport.

Adding a channel is: write a :class:`~mait_code.bridge.base.BridgeChannel`
subclass, then register it here. The gate, settings form, drain service and
hooks all resolve channels through this module, so nothing else changes.
"""

from __future__ import annotations

from mait_code.bridge.base import BridgeChannel
from mait_code.bridge.loopback import LoopbackChannel
from mait_code.bridge.ntfy import NtfyChannel

__all__ = [
    "CHANNELS",
    "get_channel_class",
    "selectable_channels",
]

# type_id -> channel class. New transports append here.
CHANNELS: dict[str, type[BridgeChannel]] = {
    cls.type_id: cls for cls in (NtfyChannel, LoopbackChannel)
}


def get_channel_class(type_id: str) -> type[BridgeChannel] | None:
    """Return the channel class for *type_id*, or ``None`` if unregistered."""
    return CHANNELS.get(type_id)


def selectable_channels() -> list[type[BridgeChannel]]:
    """Return the channels offered in the user-facing picker (hidden ones out)."""
    return [cls for cls in CHANNELS.values() if not cls.hidden]
