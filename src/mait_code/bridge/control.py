"""The Bridge control-message protocol.

Some messages on the capture topic aren't captures — they're *control*
messages the companion sent to itself: a "Done" button on a reminder
notification publishes ``mait-ctl:dismiss:<id>`` back to the capture topic, and
the next drain acts on it instead of filing it into the inbox.

The wire format lives here so the outbound side (which builds the button) and
the inbound side (which parses the drain) can never drift. The prefix is
distinctive enough that a human typing a real capture won't collide with it.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ControlCommand", "dismiss_command", "parse"]

_PREFIX = "mait-ctl:"


@dataclass(frozen=True)
class ControlCommand:
    """A parsed control message.

    Attributes:
        action: The verb, e.g. ``"dismiss"``.
        reminder_id: The reminder the action targets.
    """

    action: str
    reminder_id: int


def dismiss_command(reminder_id: int) -> str:
    """Return the control-message body that dismisses *reminder_id*."""
    return f"{_PREFIX}dismiss:{reminder_id}"


def parse(body: str) -> ControlCommand | None:
    """Parse a message body into a :class:`ControlCommand`, or ``None``.

    ``None`` means "this is an ordinary capture, file it" — so anything that
    isn't a well-formed control message flows to the inbox untouched.
    """
    if not body.startswith(_PREFIX):
        return None
    parts = body[len(_PREFIX) :].split(":")
    if len(parts) == 2 and parts[0] == "dismiss" and parts[1].isdigit():
        return ControlCommand("dismiss", int(parts[1]))
    return None
