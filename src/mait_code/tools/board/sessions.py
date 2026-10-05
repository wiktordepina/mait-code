"""Which Claude Code session is running, and whether a recorded one still is.

Claude Code exports ``CLAUDE_CODE_SESSION_ID`` and ``CLAUDE_PID`` to every Bash
call and every hook it runs. The board records both when a card is bound to a
session (see :func:`~mait_code.tools.board.service.bind_session`): the id names
the conversation, and the pid is the Claude Code process serving it, which is
how a binding is known to be *active* and how it follows a ``/clear`` (new id,
same process).

This module is the only place that reads those variables, so the service layer
stays environment-free and takes a :class:`SessionRef` from its caller.
"""

from __future__ import annotations

import os
from typing import NamedTuple

__all__ = [
    "PID_ENV",
    "SESSION_ENV",
    "SessionRef",
    "current_pid",
    "current_session",
    "pid_alive",
]

#: The variable Claude Code sets to the running session's id.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

#: The variable Claude Code sets to its own process id.
PID_ENV = "CLAUDE_PID"


class SessionRef(NamedTuple):
    """A Claude Code session: its id and the pid of the process serving it."""

    session_id: str
    pid: int


def current_pid() -> int | None:
    """Return the Claude Code process id from the environment, if valid.

    Hooks use this alone: they receive the session id on stdin, which is the
    authoritative one for the event they handle.
    """
    try:
        pid = int(os.environ.get(PID_ENV, "").strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


def current_session() -> SessionRef | None:
    """Return the session this process runs under, or ``None`` outside one.

    Both variables must be present and the pid a positive integer; anything
    less is treated as "not in a Claude Code session" rather than guessed at.
    """
    session_id = os.environ.get(SESSION_ENV, "").strip()
    pid = current_pid()
    if not session_id or pid is None:
        return None
    return SessionRef(session_id, pid)


def pid_alive(pid: int) -> bool:
    """Return whether a process with *pid* currently exists.

    Signal 0 checks existence without delivering anything. A process owned by
    another user answers ``PermissionError``, which still means it exists. A
    recycled pid reads as alive; that is accepted, as bindings are also
    released whenever their card leaves In Progress.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
