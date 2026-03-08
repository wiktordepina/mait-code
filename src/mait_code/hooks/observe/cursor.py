"""Cursor-based incremental transcript reading.

Tracks byte offsets per transcript file so the observation hook
only processes new lines since the last invocation.
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
    """Load cursor file. Returns {} on missing or corrupt file."""
    path = _cursors_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError, OSError:
        return {}


def save_cursors(cursors: dict) -> None:
    """Atomically write cursors dict, pruning stale entries."""
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
    """Get byte offset for a transcript path. Returns 0 if unseen."""
    cursors = load_cursors()
    entry = cursors.get(transcript_path)
    if entry is None:
        return 0
    return entry.get("offset", 0)


def set_cursor(transcript_path: str, offset: int) -> None:
    """Update byte offset for a transcript path and save."""
    cursors = load_cursors()
    cursors[transcript_path] = {
        "offset": offset,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    save_cursors(cursors)
