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

from mait_code.hooks.observe.cursor import get_cursor, set_cursor
from mait_code.hooks.observe.extractor import extract_observations
from mait_code.hooks.observe.storage import (
    store_entities_and_relationships,
    store_extraction,
    write_raw_extraction,
)
from mait_code.hooks.observe.transcript import format_for_extraction, read_new_lines
from mait_code.logging import log_invocation, setup_logging

logger = logging.getLogger(__name__)


@log_invocation(name="mc-hook-observe")
def main():
    """Entry point for mc-hook-observe."""
    setup_logging()
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

    event = json.loads(sys.stdin.read())
    transcript_path = event.get("transcript_path")
    if not transcript_path:
        logger.warning("no transcript_path in event")
        return

    byte_offset = get_cursor(transcript_path)
    messages, new_offset = read_new_lines(transcript_path, byte_offset)

    if not messages:
        set_cursor(transcript_path, new_offset)
        return

    conversation_text = format_for_extraction(messages)
    if not conversation_text.strip():
        set_cursor(transcript_path, new_offset)
        return

    from mait_code.context import get_context

    ctx = get_context()
    project = ctx["project"]
    branch = ctx["branch"]

    extraction = extract_observations(conversation_text, project=project, branch=branch)
    if not extraction:
        set_cursor(transcript_path, new_offset)
        return

    write_raw_extraction(extraction, args.trigger, project=project, branch=branch)
    store_extraction(extraction, project=project, branch=branch)
    store_entities_and_relationships(extraction)
    set_cursor(transcript_path, new_offset)
