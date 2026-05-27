"""Observation hook — extracts knowledge from conversation events.

Triggered by PreCompact and SessionEnd hooks. Reads the session transcript
incrementally, calls Claude Haiku for structured extraction, and stores
results in memory.db and daily observation logs.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from mait_code.hooks.observe.cursor import get_cursor, record_failure, set_cursor
from mait_code.hooks.observe.extractor import extract_observations
from mait_code.hooks.observe.storage import (
    store_entities_and_relationships,
    store_extraction,
    write_raw_extraction,
)
from mait_code.hooks.observe.transcript import format_for_extraction, read_new_lines
from mait_code.logging import log_invocation, setup_logging

logger = logging.getLogger(__name__)

# Consecutive extraction failures at one offset before we advance past the
# window anyway, so a single un-extractable transcript can't stall extraction
# forever.
MAX_EXTRACTION_FAILURES = 3


def _read_event() -> dict:
    """Read the hook event JSON from stdin.

    Returns:
        The decoded event dict, or an empty dict if stdin is empty or
        contains invalid JSON. This handles the macOS bug where async hooks
        receive no stdin data
        (https://github.com/anthropics/claude-code/issues/38162).
    """
    raw = sys.stdin.read()
    if not raw.strip():
        logger.debug("stdin empty, async hook likely did not receive input")
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("failed to parse stdin as JSON: %s", e)
        return {}


def _find_transcript(cwd: str | None = None) -> str | None:
    """Find the most recently modified transcript for the current project.

    Used as a fallback when stdin is empty (macOS async hook bug). First
    tries to derive the Claude Code project slug from ``cwd``; if that fails
    (e.g. async hooks may not inherit the project's working directory),
    scans all project directories for the most recently modified transcript.

    Args:
        cwd: Working directory to derive the project slug from. Defaults to
            the current process cwd.

    Returns:
        Path to the newest transcript file, or ``None`` if none can be found.
    """
    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.is_dir():
        logger.debug("projects root not found: %s", projects_root)
        return None

    # Try cwd-based slug first (fast path)
    cwd = cwd or os.getcwd()
    slug = cwd.replace("/", "-").replace(".", "-")
    project_dir = projects_root / slug
    if project_dir.is_dir():
        transcripts = list(project_dir.glob("*.jsonl"))
        if transcripts:
            newest = max(transcripts, key=lambda p: p.stat().st_mtime)
            logger.debug("transcript fallback (slug): %s", newest)
            return str(newest)

    # Broad scan: find the most recently modified transcript across all projects
    newest_path = None
    newest_mtime = 0.0
    for candidate_dir in projects_root.iterdir():
        if not candidate_dir.is_dir():
            continue
        for t in candidate_dir.glob("*.jsonl"):
            mtime = t.stat().st_mtime
            if mtime > newest_mtime:
                newest_mtime = mtime
                newest_path = t

    if newest_path:
        logger.debug("transcript fallback (scan): %s", newest_path)
        return str(newest_path)

    logger.debug("no transcripts found under %s", projects_root)
    return None


@log_invocation(name="mc-hook-observe")
def main():
    """Entry point for mc-hook-observe."""
    setup_logging()

    from mait_code.ssl import setup_ssl

    setup_ssl()
    if os.environ.get("MAIT_CODE_NESTED"):
        logger.debug("skipping observe hook in nested claude invocation")
        return
    try:
        _run()
    except BrokenPipeError:
        sys.exit(0)
    except Exception as e:
        logger.error("observe: %s", e)
        sys.exit(0)  # Never fail the hook


def _run():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trigger",
        required=True,
        choices=["precompact", "session-end"],
    )
    args = parser.parse_args()

    event = _read_event()
    transcript_path = event.get("transcript_path")
    if not transcript_path:
        transcript_path = _find_transcript(cwd=event.get("cwd"))
    if not transcript_path:
        logger.warning("no transcript_path available (stdin and fallback both failed)")
        return

    byte_offset = get_cursor(transcript_path)
    messages, new_offset, metadata = read_new_lines(transcript_path, byte_offset)

    if not messages:
        set_cursor(transcript_path, new_offset)
        return

    conversation_text = format_for_extraction(messages)
    if not conversation_text.strip():
        set_cursor(transcript_path, new_offset)
        return

    project = metadata.get("project")
    branch = metadata.get("branch")

    extraction = extract_observations(conversation_text, project=project, branch=branch)
    if extraction is None:
        # Transport failure (LLM timed out or errored). Leave the cursor where
        # it is so the next session re-attempts this window — unless we've
        # failed here repeatedly, in which case advance past the poison window.
        failures = record_failure(transcript_path, byte_offset)
        if failures >= MAX_EXTRACTION_FAILURES:
            logger.error(
                "observe: giving up on window at offset %d after %d consecutive failures",
                byte_offset,
                failures,
            )
            set_cursor(transcript_path, new_offset)
        return

    # The model responded. The dict may be empty (routine conversation, or an
    # unparseable response) — either way the window is handled, so advance.
    # set_cursor also clears any recorded failure state for this transcript.
    if extraction:
        write_raw_extraction(extraction, args.trigger, project=project, branch=branch)
        store_extraction(extraction, project=project, branch=branch)
        store_entities_and_relationships(extraction)
    set_cursor(transcript_path, new_offset)
