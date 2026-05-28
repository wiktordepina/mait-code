"""XDG-aware path helpers for the CLI.

Single source of truth for where mait-code stores its install record,
settings file, log files, and how to locate the user's Claude Code
directory and data directory under XDG conventions.

The helpers honour environment overrides — useful for tests (which
override ``HOME``, ``XDG_DATA_HOME``, ``XDG_CONFIG_HOME``,
``XDG_STATE_HOME``, and ``MAIT_CODE_DATA_DIR`` via the ``fake_home``
fixture) and for users who want to relocate any of these paths.
"""

from __future__ import annotations

import os
from pathlib import Path

from mait_code.config import data_dir as _config_data_dir

__all__ = [
    "claude_dir",
    "data_dir",
    "install_record_path",
    "mait_code_config_dir",
    "mait_code_log_dir",
    "mait_code_state_dir",
    "settings_path",
    "xdg_config_home",
    "xdg_data_home",
    "xdg_state_home",
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


def xdg_config_home() -> Path:
    """Return the XDG config home directory.

    Honours ``$XDG_CONFIG_HOME`` when set to a non-empty value; otherwise
    falls back to ``~/.config`` per the XDG Base Directory Spec.
    """
    override = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".config"


def xdg_state_home() -> Path:
    """Return the XDG state home directory.

    Honours ``$XDG_STATE_HOME`` when set to a non-empty value; otherwise
    falls back to ``~/.local/state`` per the XDG Base Directory Spec.
    """
    override = os.environ.get("XDG_STATE_HOME", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".local" / "state"


def mait_code_state_dir() -> Path:
    """Return the directory holding mait-code's persistent data.

    Houses the install record. ``$XDG_DATA_HOME/mait-code`` by default;
    honours ``$XDG_DATA_HOME`` overrides via :func:`xdg_data_home`.
    """
    return xdg_data_home() / "mait-code"


def mait_code_config_dir() -> Path:
    """Return the directory holding mait-code's configuration.

    Houses the settings file. ``$XDG_CONFIG_HOME/mait-code`` by default;
    honours ``$XDG_CONFIG_HOME`` overrides via :func:`xdg_config_home`.
    """
    return xdg_config_home() / "mait-code"


def mait_code_log_dir() -> Path:
    """Return the directory holding mait-code's log files.

    ``$XDG_STATE_HOME/mait-code`` by default; honours ``$XDG_STATE_HOME``
    overrides via :func:`xdg_state_home`.
    """
    return xdg_state_home() / "mait-code"


def settings_path() -> Path:
    """Return the path to the mait-code settings file (TOML)."""
    return mait_code_config_dir() / "settings.toml"


def install_record_path() -> Path:
    """Return the path to the install record JSON."""
    return mait_code_state_dir() / "install.json"


def claude_dir() -> Path:
    """Return the user's Claude Code config directory (``~/.claude``)."""
    return Path.home() / ".claude"


def data_dir() -> Path:
    """Return the mait-code data directory.

    Delegates to :func:`mait_code.config.data_dir`, the single source of
    truth for this resolution (honours ``$MAIT_CODE_DATA_DIR``; otherwise
    ``~/.claude/mait-code-data``).
    """
    return _config_data_dir()
