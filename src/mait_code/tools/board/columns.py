"""Fixed kanban column definitions for the board tool.

The board's columns are hardcoded (not user-configurable): a single, fixed
workflow shared by every project. The constants here are the single source of
truth for status validation, board ordering, and display labels.
"""

BACKLOG = "backlog"
REFINED = "refined"
IN_PROGRESS = "in_progress"
BLOCKED = "blocked"
DONE = "done"
ARCHIVED = "archived"

#: Columns in left-to-right board order. ``archived`` is a hidden state and is
#: deliberately excluded.
BOARD_ORDER: tuple[str, ...] = (BACKLOG, REFINED, IN_PROGRESS, BLOCKED, DONE)

#: Every valid ``cards.status`` value, including the hidden ``archived``.
ALL_STATUSES: tuple[str, ...] = (*BOARD_ORDER, ARCHIVED)

#: Human-facing labels for each status.
LABELS: dict[str, str] = {
    BACKLOG: "Backlog",
    REFINED: "Refined",
    IN_PROGRESS: "In Progress",
    BLOCKED: "Blocked",
    DONE: "Done",
    ARCHIVED: "Archived",
}


def is_valid_status(status: str) -> bool:
    """Return True if ``status`` is one of the fixed columns."""
    return status in ALL_STATUSES


def label(status: str) -> str:
    """Return the display label for a status (falls back to the raw value)."""
    return LABELS.get(status, status)


__all__ = [
    "ALL_STATUSES",
    "ARCHIVED",
    "BACKLOG",
    "BLOCKED",
    "BOARD_ORDER",
    "DONE",
    "IN_PROGRESS",
    "LABELS",
    "REFINED",
    "is_valid_status",
    "label",
]
