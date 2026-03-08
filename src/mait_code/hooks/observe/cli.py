"""Observation hook — extracts knowledge from conversation events.

Triggered by PreCompact and SessionEnd hooks. Reads the session transcript
incrementally, calls Claude Haiku for structured extraction, and stores
results in memory.db and daily observation logs.
"""

import argparse
import json
import sys

from mait_code.hooks.observe.cursor import get_cursor, set_cursor
from mait_code.hooks.observe.extractor import extract_observations
from mait_code.hooks.observe.storage import (
    store_entities_and_relationships,
    store_extraction,
    write_raw_extraction,
)
from mait_code.hooks.observe.transcript import format_for_extraction, read_new_lines


def main():
    """Entry point for mc-hook-observe."""
    try:
        _run()
    except Exception as e:
        print(f"observe: {e}", file=sys.stderr)
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
        print("observe: no transcript_path in event", file=sys.stderr)
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

    extraction = extract_observations(conversation_text)
    if not extraction:
        set_cursor(transcript_path, new_offset)
        return

    write_raw_extraction(extraction, args.trigger)
    store_extraction(extraction)
    store_entities_and_relationships(extraction)
    set_cursor(transcript_path, new_offset)
