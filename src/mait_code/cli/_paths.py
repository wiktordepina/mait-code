"""XDG-aware path helpers for the CLI.

Single source of truth for where mait-code stores its install record,
how to locate the user's Claude Code directory, and how to resolve the
data directory under XDG conventions.

The helpers honour environment overrides — useful for tests (which
override ``HOME``, ``XDG_DATA_HOME``, and ``MAIT_CODE_DATA_DIR`` via
the ``fake_home`` fixture) and for users who want to relocate any of
these paths.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "claude_dir",
    "data_dir",
    "install_record_path",
    "mait_code_state_dir",
    "xdg_data_home",
]


def xdg_data_home() -> Path:
    """Return the XDG data home directory.

    Honours ``$XDG_DATA_HOME`` when set to a non-empty value; otherwise
    falls back to ``~/.local/share`` per the XDG Base Directory Spec.
    """
    override = os.environ.get("XDG_DATA_HOME", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".local" / "share"


def mait_code_state_dir() -> Path:
    """Return the directory holding mait-code's CLI state.

    Currently houses the install record. ``$XDG_DATA_HOME/mait-code``
    by default; honours ``$XDG_DATA_HOME`` overrides via
    :func:`xdg_data_home`.
    """
    return xdg_data_home() / "mait-code"


def install_record_path() -> Path:
    """Return the path to the install record JSON."""
    return mait_code_state_dir() / "install.json"


def claude_dir() -> Path:
    """Return the user's Claude Code config directory (``~/.claude``)."""
    return Path.home() / ".claude"


def data_dir() -> Path:
    """Return the mait-code data directory.

    Honours ``$MAIT_CODE_DATA_DIR`` when set; otherwise defaults to
    ``~/.claude/mait-code-data`` to match the existing install layout.
    """
    override = os.environ.get("MAIT_CODE_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return claude_dir() / "mait-code-data"
