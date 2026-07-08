"""The Bridge — pluggable capture-in / notify-out transport.

Revives the terminal-bound inbox (and, in a follow-up, reminders) by fixing the
*transport* rather than the tools: a self-hosted channel drained daemon-free by
the session-start hook and routed by ``/triage``. The transport is abstracted
behind :class:`~mait_code.bridge.base.BridgeChannel`, so a new channel (ntfy
today; MQTT, Telegram, … later) is a subclass plus a registry line — the gate,
settings form and hooks are written against the interface, not any one channel.

Off by default: :func:`~mait_code.bridge.config.bridge_enabled` gates every
network path, enabled only via the hub or ``mait-code settings``.
"""

from mait_code.bridge.base import (
    BridgeChannel,
    Capture,
    ConfigField,
    DrainResult,
    OutboundMessage,
    TestResult,
)
from mait_code.bridge.config import (
    active_channel,
    active_type,
    bridge_enabled,
    build_channel,
    config_problems,
    get_watermark,
    load_channel_config,
    missing_required,
    save_channel_config,
    set_watermark,
)
from mait_code.bridge.loopback import LoopbackChannel
from mait_code.bridge.ntfy import NtfyChannel
from mait_code.bridge.registry import (
    CHANNELS,
    get_channel_class,
    selectable_channels,
)
from mait_code.bridge.service import (
    DrainOutcome,
    PublishOutcome,
    drain_channel,
    publish_due_reminders,
    run_drain,
)

__all__ = [
    # Interface
    "BridgeChannel",
    "ConfigField",
    "TestResult",
    "Capture",
    "DrainResult",
    "OutboundMessage",
    # Channels
    "NtfyChannel",
    "LoopbackChannel",
    # Registry
    "CHANNELS",
    "get_channel_class",
    "selectable_channels",
    # Config & state
    "bridge_enabled",
    "active_type",
    "active_channel",
    "build_channel",
    "load_channel_config",
    "save_channel_config",
    "get_watermark",
    "set_watermark",
    "missing_required",
    "config_problems",
    # Drain & publish service
    "run_drain",
    "drain_channel",
    "DrainOutcome",
    "publish_due_reminders",
    "PublishOutcome",
]
