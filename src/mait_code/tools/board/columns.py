"""Fixed kanban column definitions for the board tool.

The board's columns are hardcoded (not user-configurable): a single, fixed
workflow shared by every project. The constants here are the single source of
truth for status validation, board ordering, and display labels.
"""

BACKLOG = "backlog"
REFINED = "refined"
IN_PROGRESS = "in_progress"
IN_REVIEW = "in_review"
DONE = "done"
ARCHIVED = "archived"

#: The tag value that marks a card blocked. ``blocked`` is no longer a status -
#: it is carried as a tag alongside a card's real flow position, so a blocked
#: card keeps its column. The ``block``/``unblock`` verbs are thin aliases over
#: this tag.
BLOCKED_TAG = "blocked"

#: ``cards.kind`` values. A card is a unit of work on the kanban; an epic is an
#: umbrella over member cards (via ``cards.parent_id``) that lives off the
#: kanban, in the initiatives view.
CARD = "card"
EPIC = "epic"
KINDS: tuple[str, ...] = (CARD, EPIC)

#: The reserved project every epic carries - an initiative can span several
#: repos, so it belongs to none of them. Never a real project: the service
#: refuses it for a card, and ``list_projects`` leaves it out. No leading dash,
#: so ``--project @epic`` isn't mistaken for a flag.
EPIC_PROJECT = "@epic"

#: ``card_links.type`` values. ``blocks`` (``from`` must be done before ``to``
#: can start) is the only one, and the only one that affects ordering.
BLOCKS = "blocks"
LINK_TYPES: tuple[str, ...] = (BLOCKS,)

#: Reference label recording the card a new one was split from or raised as a
#: follow-up of (``add --from N``), valued ``#N``. A reference, not a link: it
#: carries provenance and never affects ordering.
ORIGIN_LABEL = "from"

#: Columns in left-to-right board order. ``archived`` is a hidden state and is
#: deliberately excluded.
BOARD_ORDER: tuple[str, ...] = (BACKLOG, REFINED, IN_PROGRESS, IN_REVIEW, DONE)

#: Every valid ``cards.status`` value, including the hidden ``archived``.
ALL_STATUSES: tuple[str, ...] = (*BOARD_ORDER, ARCHIVED)

#: Human-facing labels for each status.
LABELS: dict[str, str] = {
    BACKLOG: "Backlog",
    REFINED: "Refined",
    IN_PROGRESS: "In Progress",
    IN_REVIEW: "In Review",
    DONE: "Done",
    ARCHIVED: "Archived",
}


#: A playbook run's step statuses (``card_run_steps.status``). Step names come
#: from the playbook; the board only records where each one stands.
STEP_PENDING = "pending"
STEP_IN_PROGRESS = "in_progress"
STEP_DONE = "done"
STEP_SKIPPED = "skipped"
STEP_PAUSED = "paused"
STEP_STATUSES: tuple[str, ...] = (
    STEP_PENDING,
    STEP_IN_PROGRESS,
    STEP_DONE,
    STEP_SKIPPED,
    STEP_PAUSED,
)


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
    "BLOCKED_TAG",
    "BLOCKS",
    "BOARD_ORDER",
    "CARD",
    "DONE",
    "EPIC",
    "EPIC_PROJECT",
    "IN_PROGRESS",
    "IN_REVIEW",
    "KINDS",
    "LABELS",
    "LINK_TYPES",
    "ORIGIN_LABEL",
    "REFINED",
    "STEP_DONE",
    "STEP_IN_PROGRESS",
    "STEP_PAUSED",
    "STEP_PENDING",
    "STEP_SKIPPED",
    "STEP_STATUSES",
    "is_valid_status",
    "label",
]
