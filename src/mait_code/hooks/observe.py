"""Observation hook — extracts knowledge from conversation events."""

import json
import sys


def main():
    """Read conversation event from stdin and extract observations."""
    _event = json.loads(sys.stdin.read())
    # Placeholder: will extract facts, decisions, and patterns from conversation
    print("observe: not yet implemented", file=sys.stderr)
