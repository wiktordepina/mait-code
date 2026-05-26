"""Observe hook — extract observations from Claude Code transcripts.

Triggered by PreCompact and SessionEnd, the hook reads the session transcript
incrementally (tracking a per-transcript byte cursor), formats new turns for
extraction, calls Claude Haiku to pull structured facts, and stores the
result in the memory database plus daily raw extraction logs.

This is the largest hook package; the modules below break the pipeline into
discrete stages — transcript IO, cursor management, extraction, scope
resolution, and storage — each surfaced here for reuse and testing.
"""

from mait_code.hooks.observe.cli import main
from mait_code.hooks.observe.cursor import (
    get_cursor,
    load_cursors,
    save_cursors,
    set_cursor,
)
from mait_code.hooks.observe.extractor import (
    build_extraction_prompt,
    call_haiku,
    extract_observations,
    parse_extraction,
)
from mait_code.hooks.observe.scope import resolve_scope
from mait_code.hooks.observe.storage import (
    store_entities_and_relationships,
    store_extraction,
    write_raw_extraction,
)
from mait_code.hooks.observe.transcript import (
    format_for_extraction,
    read_new_lines,
)

__all__ = [
    # CLI
    "main",
    # Transcript
    "format_for_extraction",
    "read_new_lines",
    # Cursor
    "get_cursor",
    "load_cursors",
    "save_cursors",
    "set_cursor",
    # Extraction
    "build_extraction_prompt",
    "call_haiku",
    "extract_observations",
    "parse_extraction",
    # Scope
    "resolve_scope",
    # Storage
    "store_entities_and_relationships",
    "store_extraction",
    "write_raw_extraction",
]
