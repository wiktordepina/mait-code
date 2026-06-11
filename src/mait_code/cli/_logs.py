"""Read-side helpers for the structured JSON Lines logs.

The writing side lives in :mod:`mait_code.logging`; this module is the
consumer the ``mait-code logs`` surfaces sit on. It discovers the active log
file plus its daily-rotated siblings (``mait-code.jsonl.YYYY-MM-DD``), parses
each line back into a dict, and offers the small grouping/counting helpers the
log viewer and the home hub share.

Parsing is deliberately forgiving: the logs are append-only files written by
short-lived processes, so a truncated final line or a stray non-JSON line is
expected weather, not an error — malformed lines are skipped, never raised.
Every parsed entry is normalised to carry the core schema fields (``ts``,
``level``, ``logger``, ``msg``, ``tool``, ``pid``) with sane defaults, so
consumers can index without guarding; extra fields (``event``, ``args``,
``stack``, …) ride along as-is.

Day grouping and display times use *local* time, matching how the rotation
suffix is stamped by ``TimedRotatingFileHandler``.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from pathlib import Path

__all__ = [
    # Schema
    "LEVELS",
    "CORE_FIELDS",
    # Discovery & parsing
    "default_log_path",
    "log_files",
    "read_log_entries",
    # Grouping & filtering helpers
    "entry_day",
    "entry_time",
    "group_by_day",
    "level_at_least",
    "level_counts",
]

#: The schema's levels, least to most severe. Severity filtering compares
#: positions in this tuple; an unknown level reads as ``info``.
LEVELS = ("debug", "info", "warning", "error")

#: Fields present on every normalised entry; anything else on a parsed line is
#: an extra that consumers render generically.
CORE_FIELDS = ("ts", "level", "logger", "msg", "tool", "pid")

#: Rotated files are the active file's name plus a ``.YYYY-MM-DD`` suffix
#: (``TimedRotatingFileHandler``'s midnight-rotation stamp).
_ROTATED_SUFFIX = re.compile(r"\.\d{4}-\d{2}-\d{2}$")

#: Newest lines kept per file. A runaway day (a tool stuck in a retry loop at
#: DEBUG) shouldn't make the viewer unbootable; fourteen capped files stay
#: comfortably parseable. The viewer notes when a file was clipped.
MAX_LINES_PER_FILE = 5000


def default_log_path() -> Path:
    """The active log file path, as the writing side resolves it.

    Delegates to :func:`mait_code.logging.log_file_path` — one resolution
    (the ``log-file`` setting, else ``<state-dir>/mait-code.jsonl``) shared by
    writer and reader.
    """
    from mait_code.logging import log_file_path

    return log_file_path()


def log_files(active: Path) -> list[Path]:
    """The log files on disk for *active*: itself plus its rotated siblings.

    Rotated files sort newest first after the active file. Files that don't
    exist are excluded — an empty list means nothing has ever been logged.
    """
    files: list[Path] = []
    if active.is_file():
        files.append(active)
    if active.parent.is_dir():
        rotated = [
            p
            for p in active.parent.glob(f"{active.name}.*")
            if _ROTATED_SUFFIX.search(p.name) and p.is_file()
        ]
        files.extend(sorted(rotated, key=lambda p: p.name, reverse=True))
    return files


def _parse_line(line: str) -> dict | None:
    """One JSONL line → a normalised entry dict, or ``None`` if malformed."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    try:
        ts = float(obj.get("ts", 0.0))
    except (TypeError, ValueError):
        ts = 0.0
    entry: dict = {
        "ts": ts,
        "level": str(obj.get("level", "info")).lower(),
        "logger": str(obj.get("logger", "")),
        "msg": str(obj.get("msg", "")),
        "tool": str(obj.get("tool", "")),
        "pid": obj.get("pid"),
    }
    for key, value in obj.items():
        if key not in entry:
            entry[key] = value
    return entry


def read_log_entries(
    files: list[Path], *, max_lines_per_file: int = MAX_LINES_PER_FILE
) -> tuple[list[dict], bool]:
    """Parse *files* into entries, newest first.

    Each file contributes at most its *max_lines_per_file* newest lines (a
    bounded tail, so one pathological file can't stall the viewer). Lines that
    aren't a JSON object are skipped.

    Returns:
        The entries sorted newest-first by timestamp, and whether any file was
        clipped to its tail.
    """
    entries: list[dict] = []
    clipped = False
    for path in files:
        tail: deque[str] = deque(maxlen=max_lines_per_file)
        total = 0
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    total += 1
                    tail.append(line)
        except OSError:
            continue  # vanished or unreadable mid-listing — skip, don't crash
        clipped = clipped or total > max_lines_per_file
        entries.extend(e for e in (_parse_line(line) for line in tail) if e)
    entries.sort(key=lambda e: e["ts"], reverse=True)
    return entries, clipped


def entry_day(entry: dict) -> str:
    """An entry's local calendar day, ``YYYY-MM-DD``."""
    return time.strftime("%Y-%m-%d", time.localtime(entry["ts"]))


def entry_time(entry: dict) -> str:
    """An entry's local wall-clock time, ``HH:MM:SS``."""
    return time.strftime("%H:%M:%S", time.localtime(entry["ts"]))


def group_by_day(entries: list[dict]) -> dict[str, list[dict]]:
    """Bucket entries by local day, newest day first.

    Entry order within a day is preserved (the read already sorts
    newest-first); day keys are sorted descending rather than trusting
    insertion order, so a skewed timestamp can't misplace a group.
    """
    by_day: dict[str, list[dict]] = {}
    for entry in entries:
        by_day.setdefault(entry_day(entry), []).append(entry)
    return {day: by_day[day] for day in sorted(by_day, reverse=True)}


def level_at_least(level: str, minimum: str) -> bool:
    """Whether *level* is at or above *minimum* severity.

    Unknown levels read as ``info`` — a line with a mangled level shouldn't
    vanish from every severity view.
    """
    info = LEVELS.index("info")
    have = LEVELS.index(level) if level in LEVELS else info
    want = LEVELS.index(minimum) if minimum in LEVELS else info
    return have >= want


def level_counts(entries: list[dict]) -> dict[str, int]:
    """Entries per level, keyed by every known level (zeros included)."""
    counts: dict[str, int] = {level: 0 for level in LEVELS}
    for entry in entries:
        level = entry["level"] if entry["level"] in LEVELS else "info"
        counts[level] += 1
    return counts
