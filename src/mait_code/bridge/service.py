"""Bridge orchestration — inbound drain and outbound reminder publish.

``mc-tool-inbox drain`` and the session-start hook drain a channel into the
inbox (:func:`run_drain`); ``mc-tool-reminders check`` and the hook publish due
reminders outward (:func:`publish_due_reminders`). Both check the gate *first*,
before any channel is built or touched, so a disabled Bridge makes exactly zero
network calls — the corporate-safety guarantee, provable with the loopback
double.

The drain also handles the round-trip: a ``dismiss`` control message (from a
notification's "Done" button) dismisses the reminder instead of being filed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from mait_code.bridge import config as bridge_config
from mait_code.bridge import control
from mait_code.bridge.base import BridgeChannel, OutboundMessage

logger = logging.getLogger(__name__)

__all__ = [
    "DrainOutcome",
    "PublishOutcome",
    "run_drain",
    "drain_channel",
    "publish_due_reminders",
]


@dataclass(frozen=True)
class DrainOutcome:
    """Result of a drain attempt.

    Attributes:
        status: ``"disabled"`` (gate off), ``"unconfigured"`` (gate on but the
            channel isn't fully set up), ``"error"`` (the drain raised), or
            ``"ok"``.
        count: Number of captures filed into the inbox.
        dismissed: Number of reminders dismissed by control messages.
        detail: Human-readable context for the non-ok statuses.
    """

    status: str
    count: int = 0
    dismissed: int = 0
    detail: str = ""


@dataclass(frozen=True)
class PublishOutcome:
    """Result of an outbound reminder-publish attempt.

    Attributes:
        status: ``"disabled"``, ``"unconfigured"``, ``"error"``, or ``"ok"``.
        count: Number of reminders published outward.
        detail: Human-readable context for the non-ok statuses.
    """

    status: str
    count: int = 0
    detail: str = ""


def drain_channel(channel: BridgeChannel, type_id: str) -> tuple[int, int]:
    """Drain one channel; file captures, act on control messages.

    Returns ``(filed, dismissed)``. Idempotent across runs: the per-machine
    watermark is read before and advanced after, so a re-drain from the same
    position yields nothing new.
    """
    since = bridge_config.get_watermark(type_id)
    result = channel.drain(since)

    bodies: list[str] = []
    dismiss_ids: list[int] = []
    for capture in result.captures:
        command = control.parse(capture.body)
        if command is not None and command.action == "dismiss":
            dismiss_ids.append(command.reminder_id)
            continue
        body = capture.body.strip()
        if body:
            bodies.append(body)

    if bodies:
        from mait_code.tools.inbox import service as inbox_service
        from mait_code.tools.inbox.db import connection as inbox_connection

        with inbox_connection() as conn:
            for body in bodies:
                inbox_service.add_item(conn, body=body, project=None)

    if dismiss_ids:
        from mait_code.tools.reminders import service as reminders_service
        from mait_code.tools.reminders.db import connection as reminders_connection

        with reminders_connection() as conn:
            for reminder_id in dismiss_ids:
                reminders_service.dismiss_reminder(conn, reminder_id)

    if result.watermark is not None:
        bridge_config.set_watermark(type_id, result.watermark)
    return len(bodies), len(dismiss_ids)


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
        filed, dismissed = drain_channel(channel, type_id)
    except Exception as exc:  # best-effort: never break the caller
        logger.warning("bridge: drain failed: %s", exc)
        return DrainOutcome("error", detail=str(exc))

    if filed or dismissed:
        logger.info(
            "bridge: drained %d item(s), dismissed %d reminder(s) from %s",
            filed,
            dismissed,
            type_id,
        )
    return DrainOutcome("ok", count=filed, dismissed=dismissed)


def publish_due_reminders() -> PublishOutcome:
    """Publish due, not-yet-notified reminders outward, best-effort.

    Each carries a "Done" action that round-trips a dismissal back through the
    capture topic. Publishes each reminder once (stamping ``notified_at``), so a
    still-overdue reminder isn't re-sent every session. Never raises.
    """
    if not bridge_config.bridge_enabled():
        return PublishOutcome("disabled")

    try:
        channel = bridge_config.active_channel()
    except ValueError as exc:
        logger.warning("bridge: not publishing — %s", exc)
        return PublishOutcome("unconfigured", detail=str(exc))

    from mait_code.tools.reminders import service as reminders_service
    from mait_code.tools.reminders.db import connection as reminders_connection

    with reminders_connection() as conn:
        due = reminders_service.due_unnotified(conn)
        if not due:
            return PublishOutcome("ok", count=0)

        published: list[int] = []
        try:
            for reminder in due:
                channel.publish(
                    OutboundMessage(
                        body=reminder["what"],
                        title="Reminder",
                        actions=(
                            {
                                "label": "Done",
                                "control": control.dismiss_command(reminder["id"]),
                            },
                        ),
                    )
                )
                published.append(reminder["id"])
        except ValueError as exc:
            # Config-shaped problem (e.g. no notify topic) — not an error state.
            logger.warning("bridge: not publishing — %s", exc)
            return PublishOutcome("unconfigured", detail=str(exc))
        except Exception as exc:  # best-effort
            reminders_service.mark_notified(conn, published)
            logger.warning("bridge: publish failed after %d: %s", len(published), exc)
            return PublishOutcome("error", count=len(published), detail=str(exc))

        reminders_service.mark_notified(conn, published)
        logger.info("bridge: published %d reminder(s)", len(published))
        return PublishOutcome("ok", count=len(published))
