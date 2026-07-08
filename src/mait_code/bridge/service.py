"""Draining a channel into the inbox — the one orchestration both callers share.

``mc-tool-inbox drain`` and the session-start hook both call :func:`run_drain`.
The gate check is the *first* statement, before any channel is built or touched,
so a disabled Bridge makes exactly zero network calls — the corporate-safety
guarantee, provable with the loopback double.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from mait_code.bridge import config as bridge_config
from mait_code.bridge.base import BridgeChannel

logger = logging.getLogger(__name__)

__all__ = ["DrainOutcome", "run_drain", "drain_channel"]


@dataclass(frozen=True)
class DrainOutcome:
    """Result of a drain attempt.

    Attributes:
        status: ``"disabled"`` (gate off), ``"unconfigured"`` (gate on but the
            channel isn't fully set up), ``"error"`` (the drain raised), or
            ``"ok"``.
        count: Number of captures filed into the inbox.
        detail: Human-readable context for the non-ok statuses.
    """

    status: str
    count: int = 0
    detail: str = ""


def drain_channel(conn, channel: BridgeChannel, type_id: str) -> int:
    """Drain one channel into an open inbox connection; return the count filed.

    Idempotent across runs: the per-machine watermark is read before and
    advanced after, so a re-drain from the same position yields nothing new.
    """
    from mait_code.tools.inbox import service as inbox_service

    since = bridge_config.get_watermark(type_id)
    result = channel.drain(since)
    for capture in result.captures:
        body = capture.body.strip()
        if body:
            inbox_service.add_item(conn, body=body, project=None)
    if result.watermark is not None:
        bridge_config.set_watermark(type_id, result.watermark)
    return len(result.captures)


def run_drain() -> DrainOutcome:
    """Drain the active channel into the inbox, best-effort.

    Never raises: every failure mode comes back as a :class:`DrainOutcome` so a
    session-start hook can swallow it to a log line and carry on.
    """
    if not bridge_config.bridge_enabled():
        return DrainOutcome("disabled")

    type_id = bridge_config.active_type()
    try:
        channel = bridge_config.active_channel()
    except ValueError as exc:
        logger.warning("bridge: not draining — %s", exc)
        return DrainOutcome("unconfigured", detail=str(exc))

    try:
        from mait_code.tools.inbox.db import connection

        with connection() as conn:
            count = drain_channel(conn, channel, type_id)
    except Exception as exc:  # best-effort: never break the caller
        logger.warning("bridge: drain failed: %s", exc)
        return DrainOutcome("error", detail=str(exc))

    if count:
        logger.info("bridge: drained %d item(s) from %s", count, type_id)
    return DrainOutcome("ok", count=count)
