"""``~/.claude/settings.json`` merge / unmerge helpers.

The Claude Code settings file is a small JSON document; mait-code's
install needs to merge in its hooks, MCP server registrations, and
embedding-provider environment variable without trampling on anything
the user has set themselves.

The functions here are kept pure (in / out dicts, no IO) so the install
and uninstall command tests can exercise them directly; the on-disk
wrappers handle atomic writes and missing-file cases.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

__all__ = [
    "MAIT_CODE_HOOK_PREFIX",
    "MAIT_CODE_MCP_SERVERS",
    "MOD_NAME",
    "PLUGIN_DIRS_ENV",
    "merge_settings",
    "mod_dir",
    "mod_registered",
    "mods_enabled",
    "read_settings_file",
    "sync_mod_dir",
    "unmerge_settings",
    "write_settings_file",
]


MAIT_CODE_HOOK_PREFIX = "mc-hook-"
"""Hook command prefix used to identify mait-code-owned hooks in
``settings.json``. Anything in the user's ``hooks.*[*].hooks[*].command``
starting with this prefix is considered ours and is stripped on
uninstall."""

MAIT_CODE_MCP_SERVERS = ("mait-reminders",)
"""Historical mait-code MCP server names. Kept for backwards-compatible
uninstall (the project no longer ships MCP servers, but old installs
may still have these entries)."""

MOD_NAME = "mait-companion"
"""The optional Claude Code mod shipped under ``mods/`` in the source tree."""

PLUGIN_DIRS_ENV = "CLAUDE_CODE_PLUGIN_DIRS"
"""The ``settings.json`` ``env`` entry Claude Code reads extra plugin folders
from: absolute paths joined by the platform's path-list separator."""


def merge_settings(
    source: dict[str, Any],
    dest: dict[str, Any],
    *,
    user_settings: dict[str, str],
) -> dict[str, Any]:
    """Merge mait-code's settings into a user's existing settings.

    Returns a new dict; does not mutate either input. The merge replaces
    mait-code-owned hook entries and MCP servers with the source's
    versions, then propagates all user settings as ``MAIT_CODE_*``
    environment variables. Other user keys are preserved verbatim.

    Args:
        source: The ``config/settings.json`` shipped in the source tree.
        dest: The user's existing ``~/.claude/settings.json`` content
            (or ``{}`` if the file didn't exist).
        user_settings: Flat ``{key: value}`` from the settings file.

    Returns:
        The merged settings dict ready to write back.
    """
    from mait_code.config import SETTINGS

    merged: dict[str, Any] = {k: v for k, v in dest.items()}

    src_hooks = source.get("hooks", {}) or {}
    merged_hooks: dict[str, Any] = dict(merged.get("hooks", {}) or {})
    for hook_name, hook_config in src_hooks.items():
        merged_hooks[hook_name] = hook_config
    if merged_hooks:
        merged["hooks"] = merged_hooks

    src_servers = source.get("mcpServers", {}) or {}
    merged_servers: dict[str, Any] = dict(merged.get("mcpServers", {}) or {})
    for server_name, server_config in src_servers.items():
        merged_servers[server_name] = server_config
    if merged_servers:
        merged["mcpServers"] = merged_servers

    env: dict[str, Any] = dict(merged.get("env", {}) or {})
    for setting in SETTINGS:
        if setting.key in user_settings:
            env[setting.env] = user_settings[setting.key]
    merged["env"] = env

    return merged


def unmerge_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Strip mait-code-owned entries from a settings dict.

    Hook entries are identified by any inner ``command`` starting with
    :data:`MAIT_CODE_HOOK_PREFIX`. MCP servers are removed by name from
    :data:`MAIT_CODE_MCP_SERVERS`. The
    ``MAIT_CODE_EMBEDDING_PROVIDER`` env entry is removed. Empty
    top-level sections are dropped.

    Args:
        settings: The current on-disk settings dict.

    Returns:
        A new dict with mait-code's footprint removed.
    """
    cleaned: dict[str, Any] = {k: v for k, v in settings.items()}

    hooks = dict(cleaned.get("hooks", {}) or {})
    for hook_name, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept = [entry for entry in entries if not _entry_is_mait_code(entry)]
        if kept:
            hooks[hook_name] = kept
        else:
            del hooks[hook_name]
    if hooks:
        cleaned["hooks"] = hooks
    else:
        cleaned.pop("hooks", None)

    servers = dict(cleaned.get("mcpServers", {}) or {})
    for name in MAIT_CODE_MCP_SERVERS:
        servers.pop(name, None)
    if servers:
        cleaned["mcpServers"] = servers
    else:
        cleaned.pop("mcpServers", None)

    cleaned = sync_mod_dir(cleaned, None)
    env = dict(cleaned.get("env", {}) or {})
    for key in list(env):
        if isinstance(key, str) and key.startswith("MAIT_CODE_"):
            del env[key]
    if env:
        cleaned["env"] = env
    else:
        cleaned.pop("env", None)

    return cleaned


def mod_dir(source_dir: Path) -> Path:
    """The mait-companion mod folder inside a mait-code source tree."""
    return source_dir / "mods" / MOD_NAME


def _is_mod_entry(entry: str) -> bool:
    """Whether a plugin-dir entry is a mait-companion folder, wherever it lives.

    Matched on the trailing ``mods/mait-companion`` rather than one exact path,
    so a moved or re-cloned source tree can't leave a stale entry behind.
    """
    return Path(entry).expanduser().parts[-2:] == ("mods", MOD_NAME)


def _plugin_dirs(settings: dict[str, Any]) -> list[str]:
    env = settings.get("env") or {}
    raw = env.get(PLUGIN_DIRS_ENV, "") if isinstance(env, dict) else ""
    if not isinstance(raw, str):
        return []
    return [entry for entry in raw.split(os.pathsep) if entry]


def mods_enabled() -> bool:
    """Whether the ``mods`` setting is on, read fresh from the settings file.

    The cache is dropped first: install and update rewrite ``settings.toml``
    just before they sync ``settings.json``, and must see what they wrote.
    """
    from mait_code import config

    config.reset_cache()
    return config.get_bool("mods")


def mod_registered(settings: dict[str, Any]) -> str | None:
    """Return the mait-companion folder ``settings`` loads, or ``None``."""
    return next((e for e in _plugin_dirs(settings) if _is_mod_entry(e)), None)


def sync_mod_dir(settings: dict[str, Any], folder: Path | None) -> dict[str, Any]:
    """Point ``CLAUDE_CODE_PLUGIN_DIRS`` at *folder*, or drop the mod from it.

    Every mait-companion entry is removed first, then *folder* (when given) is
    appended, so the result names the mod at most once. Other plugin folders
    keep their order. An emptied variable, and then an emptied ``env``, are
    dropped. Pure: returns a new dict.

    Args:
        settings: A ``settings.json`` document.
        folder: The mod folder to load, or ``None`` to unload it.

    Returns:
        The updated settings dict.
    """
    updated: dict[str, Any] = {k: v for k, v in settings.items()}
    kept = [e for e in _plugin_dirs(settings) if not _is_mod_entry(e)]
    if folder is not None:
        kept.append(str(folder))
    env = settings.get("env")
    env = dict(env) if isinstance(env, dict) else {}
    if kept:
        env[PLUGIN_DIRS_ENV] = os.pathsep.join(kept)
    else:
        env.pop(PLUGIN_DIRS_ENV, None)
    if env:
        updated["env"] = env
    else:
        updated.pop("env", None)
    return updated


def _entry_is_mait_code(entry: Any) -> bool:
    """Return True if a hook entry contains any mait-code-owned command."""
    if not isinstance(entry, dict):
        return False
    inner = entry.get("hooks", [])
    if not isinstance(inner, list):
        return False
    for hook in inner:
        if not isinstance(hook, dict):
            continue
        cmd = hook.get("command", "")
        if isinstance(cmd, str) and MAIT_CODE_HOOK_PREFIX in cmd:
            return True
    return False


def read_settings_file(path: Path) -> dict[str, Any]:
    """Read a settings.json. Returns ``{}`` if missing or unparseable."""
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def write_settings_file(path: Path, settings: dict[str, Any]) -> None:
    """Write ``settings`` to ``path`` atomically with a trailing newline.

    Uses a tempfile + ``os.replace`` so a crash mid-write can't leave
    half a JSON file on disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(settings, indent=2) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup of the tempfile on failure.
        Path(tmp_path).unlink(missing_ok=True)
        raise
