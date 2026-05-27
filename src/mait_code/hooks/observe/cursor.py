"""Cursor-based incremental transcript reading.

Tracks byte offsets per transcript file so the observation hook only
processes new lines since the last invocation.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mait_code.tools.memory.db import get_data_dir

CURSORS_FILENAME = "cursors.json"
PRUNE_AGE_DAYS = 30


def _cursors_path() -> Path:
    return get_data_dir() / "memory" / "observations" / CURSORS_FILENAME


def load_cursors() -> dict:
    """Load the cursor file, returning ``{}`` on missing or corrupt input."""
    path = _cursors_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_cursors(cursors: dict) -> None:
    """Atomically write the cursors dict, pruning stale entries."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PRUNE_AGE_DAYS)).isoformat()
    pruned = {k: v for k, v in cursors.items() if v.get("updated", "") >= cutoff}

    path = _cursors_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(pruned, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_cursor(transcript_path: str) -> int:
    """Return the byte offset for a transcript path, or ``0`` if unseen."""
    cursors = load_cursors()
    entry = cursors.get(transcript_path)
    if entry is None:
        return 0
    return entry.get("offset", 0)


def set_cursor(transcript_path: str, offset: int) -> None:
    """Advance the byte offset for a transcript path and persist the cursors file.

    Writing a fresh record also clears any extraction-failure state recorded by
    :func:`record_failure`, since advancing means moving past the window that
    was failing.
    """
    cursors = load_cursors()
    cursors[transcript_path] = {
        "offset": offset,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    save_cursors(cursors)


def record_failure(transcript_path: str, offset: int) -> int:
    """Record an extraction failure at ``offset`` and return the running count.

    The cursor offset is deliberately left unadvanced so the next invocation
    re-reads the same window. Consecutive failures at the same offset
    accumulate; a failure at a different offset resets the count to 1. The
    count is cleared when :func:`set_cursor` advances past the window.

    Args:
        transcript_path: The transcript whose extraction failed.
        offset: The byte offset the failed read started from.

    Returns:
        The number of consecutive failures now recorded at this offset.
    """
    cursors = load_cursors()
    entry = cursors.get(transcript_path, {})
    if entry.get("fail_offset") == offset:
        count = entry.get("fail_count", 0) + 1
    else:
        count = 1
    entry["fail_offset"] = offset
    entry["fail_count"] = count
    entry.setdefault("offset", offset)
    entry["updated"] = datetime.now(timezone.utc).isoformat()
    cursors[transcript_path] = entry
    save_cursors(cursors)
    return count
