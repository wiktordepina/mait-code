"""Memory store statistics — shared by the ``stats`` CLI command and the home TUI.

Pure SQL counts plus cheap config reads. Deliberately does **not** probe
embedding-provider availability (:func:`~mait_code.tools.memory.embeddings.is_available`
can load a local model); callers that want the probe layer it on top.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from mait_code.tools.memory.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL
from mait_code.tools.memory.embeddings import (
    _get_provider_name as _embedding_provider_name,
)

__all__ = ["MemoryStats", "collect_stats"]


@dataclass(frozen=True)
class MemoryStats:
    """A snapshot of the memory store's shape and embedding coverage."""

    total: int
    by_type: list[tuple[str, int]]
    by_class: list[tuple[str, int]]
    by_scope: list[tuple[str, int]]
    by_project: list[tuple[str, int]]
    embedded: int
    provider: str
    model: str
    dim: int
    unreflected: int
    last_reflected_at: datetime | None

    @property
    def unembedded(self) -> int:
        """Entries with no vector in ``memory_vec``."""
        return self.total - self.embedded

    @property
    def embedded_pct(self) -> int:
        """Embedding coverage as a whole-number percentage (0 when empty)."""
        return round(100 * self.embedded / self.total) if self.total else 0


def collect_stats(conn: sqlite3.Connection) -> MemoryStats:
    """Collect store statistics from an open memory connection.

    All counts come from SQL; provider/model/dimension come from
    configuration. ``unreflected`` and ``last_reflected_at`` describe the
    global reflection watermark (observation backlog and freshness).
    """
    # Imported here, not at module top: reflect.py pulls in the LLM layer.
    from mait_code.tools.memory.reflect import (
        count_unreflected,
        get_last_reflected_at,
    )

    total = conn.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
    by_type = conn.execute(
        "SELECT entry_type, COUNT(*) FROM memory_entries "
        "GROUP BY entry_type ORDER BY COUNT(*) DESC"
    ).fetchall()
    by_class = conn.execute(
        "SELECT memory_class, COUNT(*) FROM memory_entries GROUP BY memory_class"
    ).fetchall()
    by_scope = conn.execute(
        "SELECT scope, COUNT(*) FROM memory_entries GROUP BY scope ORDER BY COUNT(*) DESC"
    ).fetchall()
    by_project = conn.execute(
        "SELECT COALESCE(project, '(global)'), COUNT(*) FROM memory_entries "
        "GROUP BY project ORDER BY COUNT(*) DESC"
    ).fetchall()

    try:
        embedded = conn.execute("SELECT COUNT(*) FROM memory_vec").fetchone()[0]
    except sqlite3.Error:
        embedded = 0

    return MemoryStats(
        total=total,
        by_type=[(t, n) for t, n in by_type],
        by_class=[(c, n) for c, n in by_class],
        by_scope=[(s, n) for s, n in by_scope],
        by_project=[(p, n) for p, n in by_project],
        embedded=embedded,
        provider=_embedding_provider_name(),
        model=EMBEDDING_MODEL,
        dim=EMBEDDING_DIM,
        unreflected=count_unreflected(conn),
        last_reflected_at=get_last_reflected_at(conn),
    )
