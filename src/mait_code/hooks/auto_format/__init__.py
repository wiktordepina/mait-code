"""Auto-format hook — placeholder, not currently registered.

Entry point exists (``mc-hook-format`` in pyproject.toml) but is not wired
into ``~/.claude/settings.json``. Reserved for a future PostToolUse hook
that auto-runs formatters after file edits.
"""

from mait_code.hooks.auto_format.cli import main

__all__ = ["main"]
