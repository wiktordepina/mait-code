"""Shared write path for ``mait-code settings set`` and the interactive editor.

Both the non-interactive ``set`` command and the questionary-driven editor
funnel every change through :func:`apply_setting`, so the two can never
diverge on validation, env shadowing, or destructive follow-ups. The function
is deliberately TTY-free and side-effects are confined to well-known helpers,
so it can be unit-tested in full against a temp ``$HOME``.

The pipeline is: resolve the key → validate → persist the TOML →
*enforce* (sync an already-mirrored ``settings.json`` env entry and warn on a
shell export that still shadows the change) → run the required follow-up
(re-embed on a migration key, relocate the data directory for ``data-dir``).
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mait_code import config

__all__ = [
    # Registry settings
    "ApplyOutcome",
    "SettingError",
    "apply_setting",
    "move_data_dir",
    "validation_error",
    # Custom [env] variables
    "EnvOutcome",
    "env_name_error",
    "set_env_var",
    "unset_env_var",
]


class SettingError(ValueError):
    """A setting could not be applied — unknown/derived key or invalid value."""


@dataclass
class ApplyOutcome:
    """The result of a successful :func:`apply_setting` call.

    Attributes:
        key: The setting that was changed.
        old_value: Its resolved value before the change.
        new_value: The value written to the settings file.
        followup: The required follow-up — ``"reindex"``, ``"move-data"`` or
            ``None`` when the change applies on the next invocation.
        followup_done: ``True`` when the follow-up was actually carried out.
        warnings: Human-readable warnings (e.g. a shell export still shadows
            the change).
    """

    key: str
    old_value: str
    new_value: str
    followup: str | None
    followup_done: bool
    warnings: list[str] = field(default_factory=list)


def apply_setting(
    key: str,
    value: str,
    *,
    reindex: bool | None = None,
    move_data: bool | None = None,
    confirm: Callable[[str], bool] | None = None,
) -> ApplyOutcome:
    """Validate, persist and enforce a single setting change.

    Args:
        key: Kebab-case setting key (e.g. ``log-level``).
        value: The new value, as a string.
        reindex: For a migration key, whether to re-embed now. ``None`` (and
            no *confirm*) means undecided — an error, since the caller must
            choose explicitly.
        move_data: For ``data-dir``, whether to relocate the data directory.
        confirm: A yes/no prompt used by the interactive editor to decide a
            follow-up when the corresponding flag is ``None``.

    Returns:
        An :class:`ApplyOutcome` describing what changed and what ran.

    Raises:
        SettingError: The key is unknown, derived (read-only), a single
            scoring weight, or the value fails validation; or a required
            follow-up decision was not supplied.
    """
    setting = _resolve_settable(key)
    msg = validation_error(setting, value)
    if msg is not None:
        raise SettingError(f"{setting.key}: {msg}")

    old_value, _ = config.resolve(setting)

    values = config.read_settings_file()
    values[key] = value
    config.write_settings_file(values)
    # The module-level cache is now stale; force a re-read so the enforce
    # step and any follow-up observe the value we just wrote.
    config._settings_cache = None

    warnings = _enforce(setting, value)

    followup, followup_done = _run_followup(
        setting,
        old_value=old_value,
        new_value=value,
        reindex=reindex,
        move_data=move_data,
        confirm=confirm,
    )

    return ApplyOutcome(
        key=key,
        old_value=old_value,
        new_value=value,
        followup=followup,
        followup_done=followup_done,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Resolution + validation
# ---------------------------------------------------------------------------


def _resolve_settable(key: str) -> config.Setting:
    """Return the Setting for *key*, rejecting unknown/derived/weight keys."""
    by_key = {s.key: s for s in config.SETTINGS}
    setting = by_key.get(key)
    if setting is None:
        raise SettingError(
            f"unknown setting {key!r}. Run `mait-code settings list` to see the keys."
        )
    if not setting.settable:
        raise SettingError(
            f"{key!r} is a derived, read-only value — it is computed from other "
            "settings and cannot be set directly."
        )
    if key in config._WEIGHT_KEYS:
        raise SettingError(
            f"{key!r} is one of three scoring weights that must sum to 1.0; "
            "setting it alone would leave an invalid sum. Use the interactive "
            "editor (`mait-code settings`) to retune all three at once, or edit "
            "settings.toml directly (`mait-code doctor` validates the result)."
        )
    return setting


def validation_error(setting: config.Setting, value: str) -> str | None:
    """Return a validation error for *value*, or ``None`` when it is valid.

    Combines kind coercion (int/float) with the Setting's own validator.
    The single source of truth shared by :func:`apply_setting` and the
    interactive editor's live validator, so both reject identically.
    """
    if setting.kind == "int":
        try:
            int(value)
        except (TypeError, ValueError):
            return f"must be an integer, got {value!r}"
    elif setting.kind == "float":
        try:
            float(value)
        except (TypeError, ValueError):
            return f"must be a number, got {value!r}"
    if setting.validate is not None:
        return setting.validate(value)
    return None


# ---------------------------------------------------------------------------
# Enforcement — keep settings.json in step; warn on shell shadowing
# ---------------------------------------------------------------------------


def _enforce(setting: config.Setting, written: str) -> list[str]:
    """Sync an already-mirrored settings.json env entry; warn on shell shadow.

    Updates ``~/.claude/settings.json`` only when *setting.env* is **already**
    present in its ``env`` block (so a stale mirror, e.g. the one ``install``
    writes for ``embedding-provider``, can't silently shadow the new value).
    Never adds a key. Anything still overriding after that can only be a shell
    export, which we report precisely.
    """
    from mait_code.cli._paths import claude_dir
    from mait_code.cli._settings import (
        read_settings_file as read_claude_settings,
        write_settings_file as write_claude_settings,
    )

    warnings: list[str] = []
    cj_path = claude_dir() / "settings.json"
    cj = read_claude_settings(cj_path)
    env = dict(cj.get("env") or {})
    if setting.env and setting.env in env and env[setting.env] != written:
        env[setting.env] = written
        cj["env"] = env
        write_claude_settings(cj_path, cj)

    value, source = config.resolve(setting)
    if source == "env" and value != written:
        warnings.append(
            f"{setting.key} is exported as ${setting.env} in your shell "
            f"({value!r}); it overrides the settings file until you unset it."
        )
    return warnings


# ---------------------------------------------------------------------------
# Follow-ups — reindex on migration, move on data-dir
# ---------------------------------------------------------------------------


def _decide(
    flag: bool | None, confirm: Callable[[str], bool] | None, prompt: str
) -> bool | None:
    """Resolve a follow-up decision from an explicit flag or a confirm prompt."""
    if flag is not None:
        return flag
    if confirm is not None:
        return confirm(prompt)
    return None


def _run_followup(
    setting: config.Setting,
    *,
    old_value: str,
    new_value: str,
    reindex: bool | None,
    move_data: bool | None,
    confirm: Callable[[str], bool] | None,
) -> tuple[str | None, bool]:
    """Carry out the follow-up implied by *setting*; return (kind, done)."""
    if setting.requires_migration:
        decision = _decide(
            reindex,
            confirm,
            "Re-embed all memories now? This rebuilds the vector table.",
        )
        if decision is None:
            raise SettingError(
                f"changing {setting.key} invalidates stored embeddings; pass "
                "--reindex to re-embed now or --no-reindex to defer "
                "(then run `mc-tool-memory reindex` yourself)."
            )
        if decision:
            from mait_code.tools.memory.cli import run_reindex

            run_reindex()
        return "reindex", decision

    if setting.key == "data-dir":
        decision = _decide(
            move_data,
            confirm,
            f"Move existing data from {old_value} to {new_value}?",
        )
        if decision is None:
            raise SettingError(
                "changing data-dir leaves your existing memories at the old "
                "path; pass --move-data to relocate them or --no-move-data to "
                "leave them in place."
            )
        if decision:
            move_data_dir(Path(old_value).expanduser(), Path(new_value).expanduser())
        return "move-data", decision

    return None, False


# ---------------------------------------------------------------------------
# Custom [env] variables — the shared write path for `settings set/unset
# env.<NAME>` and the interactive editor's Custom env group.
# ---------------------------------------------------------------------------


@dataclass
class EnvOutcome:
    """The result of a successful [env] table change.

    Attributes:
        name: The environment variable that was changed.
        old_value: Its previous table value, or ``None`` when newly added.
        new_value: The value written, or ``None`` when removed.
        warnings: Human-readable warnings (e.g. a shell export shadows the
            table value).
    """

    name: str
    old_value: str | None
    new_value: str | None
    warnings: list[str] = field(default_factory=list)


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def env_name_error(name: str) -> str | None:
    """Return a validation error for an [env] variable name, or ``None``.

    The single source of truth shared by :func:`set_env_var` and the
    interactive editor's live validator, so both reject identically.
    """
    if not _ENV_NAME_RE.match(name):
        return "must be a valid environment variable name ([A-Za-z_][A-Za-z0-9_]*)"
    if name.startswith("MAIT_CODE_"):
        return (
            "MAIT_CODE_* variables are first-class settings — "
            "set them via their settings.toml key instead"
        )
    return None


def set_env_var(name: str, value: str) -> EnvOutcome:
    """Add or update a custom [env] variable and persist it.

    Also applies the change to the current process environment (unless a
    shell export shadows it), so follow-on work in the same process sees
    the new value without a restart.

    Raises:
        SettingError: The name is not a valid environment variable name,
            or is a reserved ``MAIT_CODE_*`` key.
    """
    msg = env_name_error(name)
    if msg is not None:
        raise SettingError(f"env.{name}: {msg}")

    env = config.read_env_table()
    old_value = env.get(name)
    env[name] = value
    config.write_settings_file(config.read_settings_file(), env=env)
    config._settings_cache = None

    warnings: list[str] = []
    shadow, source = config._env_effective(name, value)
    if source == "env":
        if shadow != value:
            warnings.append(
                f"{name} is set in your shell environment ({shadow!r}); "
                "it overrides the [env] value until you unset it."
            )
    else:
        os.environ[name] = value
        config._injected_env.add(name)

    return EnvOutcome(
        name=name, old_value=old_value, new_value=value, warnings=warnings
    )


def unset_env_var(name: str) -> EnvOutcome:
    """Remove a custom [env] variable and persist the change.

    Also removes it from the current process environment when it was
    injected from the table (a real shell export is left alone).

    Raises:
        SettingError: The variable is not in the [env] table.
    """
    env = config.read_env_table()
    if name not in env:
        raise SettingError(
            f"env.{name} is not set in the [env] table. "
            "Run `mait-code settings list` to see the configured variables."
        )
    old_value = env.pop(name)
    config.write_settings_file(config.read_settings_file(), env=env)
    config._settings_cache = None

    if name in config._injected_env:
        os.environ.pop(name, None)
        config._injected_env.discard(name)

    return EnvOutcome(name=name, old_value=old_value, new_value=None)


def move_data_dir(old: Path, new: Path) -> None:
    """Relocate the data directory from *old* to *new*.

    Moves atomically where the filesystem allows (a rename) and copies
    otherwise. Refuses when *new* already exists and is non-empty, so an
    existing install at the target is never clobbered.

    Raises:
        SettingError: *old* does not exist, or *new* exists and is non-empty.
    """
    old, new = Path(old), Path(new)
    if old.resolve() == new.resolve():
        return
    if not old.exists():
        raise SettingError(
            f"current data directory {old} does not exist; nothing to move."
        )
    if new.exists():
        if any(new.iterdir()):
            raise SettingError(
                f"target data directory {new} already exists and is not empty."
            )
        new.rmdir()
    new.parent.mkdir(parents=True, exist_ok=True)
    # shutil.move renames within a filesystem, copy-then-removes across one.
    shutil.move(str(old), str(new))
