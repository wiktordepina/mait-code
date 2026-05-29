"""Central registry of mait-code configuration knobs.

Single source of truth for every ``MAIT_CODE_*`` environment variable the
framework reads as *user configuration*: its key, default, and whether
changing it requires re-embedding stored memories. Both the running code
(via :func:`data_dir` and the shared default constants) and
``mait-code settings`` (via :func:`resolve`) read from here, so each
default is defined exactly once.

Internal flags (e.g. ``MAIT_CODE_NESTED``) and structural constants
(``MAIT_CODE_HOOK_PREFIX``) are deliberately excluded — they are not
user-facing settings.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    # Registry
    "Setting",
    "SETTINGS",
    "resolve",
    "get",
    "get_int",
    "get_float",
    "validate_settings",
    # Settings file I/O
    "read_settings_file",
    "write_settings_file",
    # Resolvers
    "data_dir",
    # Settings view
    "ResolvedSetting",
    "SettingsSnapshot",
    "collect_settings",
    "render",
    "render_json",
    # Defaults
    "DEFAULT_DATA_DIR_DISPLAY",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_EMBEDDING_PROVIDER",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_BEDROCK_MODEL_ID",
    "DEFAULT_BEDROCK_REGION",
]


# Defaults, defined once and shared with the embedding providers and the
# settings registry below.
DEFAULT_DATA_DIR_DISPLAY = "~/.claude/mait-code-data"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_EMBEDDING_PROVIDER = "local"
DEFAULT_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_BEDROCK_MODEL_ID = "amazon.titan-embed-text-v2:0"
DEFAULT_BEDROCK_REGION = "eu-west-2"


@dataclass(frozen=True)
class Setting:
    """One configuration knob shown by ``mait-code settings``.

    Most settings are *settable*: backed by an environment variable, with a
    value resolved env → file → default. Two extra flavours exist:

    * **Derived** (``settable=False``): a read-only value computed at display
      time by :attr:`derive` (e.g. database paths derived from ``data-dir``).
      These have no environment variable and never appear as an assignable
      line in the settings file.
    * **Advanced** (``advanced=True``): a real settable knob that is written
      *commented-out* in the generated settings file, so the hardcoded
      default stays authoritative until the user deliberately uncomments it.

    Attributes:
        key: Stable, kebab-case identifier shown by ``mait-code settings``.
        env: The environment variable that backs it (empty for derived).
        default: Display string for the default value (``<data-dir>``-style
            placeholders are allowed where the real default is derived).
        requires_migration: ``True`` when changing it invalidates stored
            embeddings (provider/model changes need a re-embed).
        secret: ``True`` when the value should be masked in output.
        help: One-line description.
        kind: Value type for typed accessors — ``"str"``, ``"int"`` or
            ``"float"``. Drives :func:`get_int` / :func:`get_float` coercion.
        settable: ``False`` marks a derived, display-only value.
        advanced: ``True`` writes the knob commented-out in the settings file.
        derive: For derived settings, a zero-arg callable returning the
            computed value as a string. Must lazy-import any heavy deps so
            ``config`` stays a light, stdlib-only leaf.
        validate: Optional callable taking the raw string value and returning
            an error message, or ``None`` when valid. Run by ``doctor``.
    """

    key: str
    env: str
    default: str
    requires_migration: bool = False
    secret: bool = False
    help: str = ""
    kind: str = "str"
    settable: bool = True
    advanced: bool = False
    derive: Callable[[], str] | None = None
    validate: Callable[[str], str | None] | None = None


SETTINGS: tuple[Setting, ...] = (
    Setting(
        "data-dir",
        "MAIT_CODE_DATA_DIR",
        DEFAULT_DATA_DIR_DISPLAY,
        help="Where memories, logs and personalised files live.",
    ),
    Setting(
        "log-level",
        "MAIT_CODE_LOG_LEVEL",
        DEFAULT_LOG_LEVEL,
        help="Log verbosity: DEBUG, INFO, WARNING or ERROR.",
    ),
    Setting(
        "log-file",
        "MAIT_CODE_LOG_FILE",
        "<state-dir>/mait-code.log",
        help="Override the log file path.",
    ),
    Setting(
        "embedding-provider",
        "MAIT_CODE_EMBEDDING_PROVIDER",
        DEFAULT_EMBEDDING_PROVIDER,
        requires_migration=True,
        help="Embedding backend: 'local' or 'bedrock'.",
    ),
    Setting(
        "embedding-model",
        "MAIT_CODE_EMBEDDING_MODEL",
        DEFAULT_EMBEDDING_MODEL,
        requires_migration=True,
        help="Local embedding model (used when provider is 'local').",
    ),
    Setting(
        "bedrock-model-id",
        "MAIT_CODE_BEDROCK_MODEL_ID",
        DEFAULT_BEDROCK_MODEL_ID,
        requires_migration=True,
        help="Bedrock model id (used when provider is 'bedrock').",
    ),
    Setting(
        "bedrock-region",
        "MAIT_CODE_BEDROCK_REGION",
        DEFAULT_BEDROCK_REGION,
        help="AWS region for the Bedrock embedding client.",
    ),
)


_settings_cache: dict[str, str] | None = None


def _load_settings() -> dict[str, str]:
    """Return the cached settings-file contents, loading on first call."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = read_settings_file()
    return _settings_cache


def resolve(setting: Setting) -> tuple[str, str]:
    """Return ``(value, source)`` for a setting.

    Resolution order (highest priority wins):

    1. **Environment variable** — ``source = "env"``
    2. **Settings file** — ``source = "settings"``
    3. **Hardcoded default** — ``source = "default"``

    Derived settings (``settable=False``) short-circuit to their computed
    value with source ``"derived"``.

    This *reports* configuration; it does not validate it — that is
    ``doctor``'s job.
    """
    if not setting.settable and setting.derive is not None:
        return setting.derive(), "derived"
    raw = os.environ.get(setting.env)
    if raw is not None and raw.strip() != "":
        return raw, "env"
    file_values = _load_settings()
    if setting.key in file_values:
        return file_values[setting.key], "settings"
    return setting.default, "default"


def get(key: str) -> str:
    """Return the resolved value for a setting by its kebab-case key.

    Convenience wrapper around :func:`resolve` that discards the source.

    Raises:
        KeyError: If *key* is not a registered setting.
    """
    return resolve(_by_key()[key])[0]


def get_int(key: str) -> int:
    """Return a setting coerced to ``int``.

    Falls back to the setting's hardcoded default (logging a warning) when
    the resolved value cannot be parsed, so a fat-fingered settings file
    degrades to stock behaviour rather than crashing a hook. ``doctor`` is
    responsible for surfacing the bad value loudly.

    Raises:
        KeyError: If *key* is not a registered setting.
    """
    setting = _by_key()[key]
    value, _ = resolve(setting)
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning(
            "setting %r is not an integer (%r); using default %r",
            key,
            value,
            setting.default,
        )
        return int(setting.default)


def get_float(key: str) -> float:
    """Return a setting coerced to ``float``.

    Like :func:`get_int`, falls back to the hardcoded default on a bad value.

    Raises:
        KeyError: If *key* is not a registered setting.
    """
    setting = _by_key()[key]
    value, _ = resolve(setting)
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning(
            "setting %r is not a number (%r); using default %r",
            key,
            value,
            setting.default,
        )
        return float(setting.default)


def validate_settings() -> list[str]:
    """Return a list of human-readable validation errors (empty when healthy).

    Runs every setting's per-value :attr:`Setting.validate` callable, plus
    the cross-field invariants below. Called by ``doctor``; it reads the
    resolved configuration but never mutates it.
    """
    errors: list[str] = []
    for setting in SETTINGS:
        if setting.validate is None:
            continue
        value, _ = resolve(setting)
        msg = setting.validate(value)
        if msg is not None:
            errors.append(f"{setting.key}: {msg}")
    errors.extend(_cross_field_errors())
    return errors


def _cross_field_errors() -> list[str]:
    """Cross-field setting invariants. Extended as grouped knobs are added."""
    return []


def data_dir() -> Path:
    """Return the mait-code data directory — the canonical resolver.

    Honours ``$MAIT_CODE_DATA_DIR`` when set to a non-empty value;
    otherwise ``~/.claude/mait-code-data``. Computed at call time so tests
    that relocate ``$HOME`` are honoured.
    """
    override = os.environ.get("MAIT_CODE_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".claude" / "mait-code-data"


# ---------------------------------------------------------------------------
# Settings file I/O (TOML)
# ---------------------------------------------------------------------------

_SETTINGS_BY_KEY: dict[str, Setting] = {}


def _by_key() -> dict[str, Setting]:
    """Lazy-init lookup from kebab-case key to Setting."""
    if not _SETTINGS_BY_KEY:
        _SETTINGS_BY_KEY.update({s.key: s for s in SETTINGS})
    return _SETTINGS_BY_KEY


def read_settings_file(path: Path | None = None) -> dict[str, str]:
    """Read the settings TOML file.

    Args:
        path: Override the settings file path (defaults to
            :func:`~mait_code.cli._paths.settings_path`).

    Returns:
        A flat ``{key: value}`` dict with kebab-case keys and string
        values. Returns ``{}`` if the file is missing or malformed.
    """
    if path is None:
        from mait_code.cli._paths import settings_path

        path = settings_path()
    if not path.exists():
        return {}
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: str(v) for k, v in raw.items() if isinstance(v, str)}


def _render_settings_toml(values: dict[str, str]) -> str:
    """Generate a commented TOML string with all settings.

    Three groups are written in order:

    1. **Primary** settable knobs — uncommented (placeholder defaults stay
       commented unless an explicit value is provided).
    2. **Advanced** settable knobs — always commented-out, showing the
       default as the example value so the hardcoded default stays
       authoritative until the user uncomments a line.
    3. **Derived** read-only values — informational comments only; never an
       assignable line.
    """
    lines = [
        "# mait-code settings",
        "# Written by mait-code install/update. Safe to edit by hand.",
        "# Environment variables (MAIT_CODE_*) override these values when set.",
        "",
    ]

    for setting in SETTINGS:
        if not setting.settable or setting.advanced:
            continue
        lines.append(f"# {setting.help}")
        has_value = setting.key in values
        value = values.get(setting.key, setting.default)
        is_placeholder = "<" in setting.default and not has_value
        if is_placeholder:
            lines.append(f'# {setting.key} = "{value}"')
        else:
            lines.append(f'{setting.key} = "{value}"')
        lines.append("")

    advanced = [s for s in SETTINGS if s.settable and s.advanced]
    if advanced:
        lines.append(_SECTION_RULE)
        lines.append(
            "# Advanced — uncomment to override. Defaults shown; safe to leave alone."
        )
        lines.append(_SECTION_RULE)
        lines.append("")
        for setting in advanced:
            lines.append(f"# {setting.help}")
            value = values.get(setting.key, setting.default)
            lines.append(f'# {setting.key} = "{value}"')
            lines.append("")

    derived = [s for s in SETTINGS if not s.settable]
    if derived:
        lines.append(_SECTION_RULE)
        lines.append(
            "# Derived — read-only, shown by `mait-code settings`. Not configurable here."
        )
        lines.append(_SECTION_RULE)
        lines.append("")
        for setting in derived:
            lines.append(f"# {setting.key}: {setting.help}")
        lines.append("")

    return "\n".join(lines)


_SECTION_RULE = "# " + "-" * 73


def write_settings_file(values: dict[str, str], *, path: Path | None = None) -> Path:
    """Write the settings TOML file atomically.

    Generates a fully commented TOML with all registered settings.
    Values not in *values* are written with their defaults.

    Args:
        values: Setting values to write (kebab-case keys).
        path: Override the settings file path (defaults to
            :func:`~mait_code.cli._paths.settings_path`).

    Returns:
        The path the file was written to.
    """
    if path is None:
        from mait_code.cli._paths import settings_path

        path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _render_settings_toml(values)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


# ---------------------------------------------------------------------------
# Settings view — read-only snapshot for `mait-code settings`.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedSetting:
    """A setting with its resolved value and provenance, for display."""

    key: str
    value: str
    source: str  # "env", "settings", or "default"
    requires_migration: bool


@dataclass(frozen=True)
class SettingsSnapshot:
    """All resolved settings, plus any detected configuration drift."""

    settings: tuple[ResolvedSetting, ...]
    drift: str | None = None


def _mask(value: str) -> str:
    """Mask a secret AWS-style: keep only the last four characters."""
    if len(value) <= 4:
        return "••••"
    return "…" + value[-4:]


def collect_settings() -> SettingsSnapshot:
    """Resolve every setting for display, and flag embedding-provider drift.

    Drift is detected when the env var overrides the settings file value
    for ``embedding-provider`` — this means the runtime provider differs
    from what was configured, and memories may need re-embedding.

    Returns:
        A read-only :class:`SettingsSnapshot`.
    """
    rows: list[ResolvedSetting] = []
    env_provider: str | None = None
    file_provider: str | None = None
    for setting in SETTINGS:
        value, source = resolve(setting)
        if setting.key == "embedding-provider":
            raw_env = os.environ.get(setting.env)
            if raw_env and raw_env.strip():
                env_provider = raw_env
            file_values = _load_settings()
            file_provider = file_values.get(setting.key)
        if setting.secret and source == "env":
            value = _mask(value)
        rows.append(
            ResolvedSetting(setting.key, value, source, setting.requires_migration)
        )

    drift: str | None = None
    if env_provider and file_provider and env_provider != file_provider:
        drift = (
            f"env var overrides embedding-provider to '{env_provider}', "
            f"but settings file says '{file_provider}' — run "
            f"mc-tool-memory reindex to re-embed if intentional"
        )
    return SettingsSnapshot(settings=tuple(rows), drift=drift)


def render_json(snapshot: SettingsSnapshot) -> str:
    """Render the snapshot as a JSON document."""
    return json.dumps(
        {
            "settings": [
                {
                    "key": r.key,
                    "value": r.value,
                    "source": r.source,
                    "requires_migration": r.requires_migration,
                }
                for r in snapshot.settings
            ],
            "drift": snapshot.drift,
        },
        indent=2,
    )


def render(snapshot: SettingsSnapshot) -> None:
    """Print the snapshot to the shared console (read-only, provenance-aware).

    Imports rich lazily so this module stays a light, stdlib-only leaf for
    the hook/tool processes that import it only for :func:`data_dir`.
    """
    from rich.table import Table
    from rich.text import Text

    from mait_code.console import console

    from mait_code.cli._paths import settings_path

    header = Text("mait-code settings", style="accent")
    header.append("   (read-only)", style="muted")
    console.print(header)
    sp = settings_path()
    sp_display = str(sp).replace(str(Path.home()), "~")
    file_line = Text("settings file: ", style="muted")
    file_line.append(sp_display, style="")
    if not sp.exists():
        file_line.append("  (not found)", style="warn")
    console.print(file_line)
    console.rule(style="muted")

    table = Table(box=None, pad_edge=False, header_style="muted")
    table.add_column("SETTING", style="bold", no_wrap=True)
    table.add_column("VALUE")
    table.add_column("SOURCE", no_wrap=True)
    for row in snapshot.settings:
        if row.source == "default":
            value_style = "muted"
        else:
            value_style = ""
        value = Text(row.value, style=value_style)
        if row.source == "env":
            source_style = "warn"
        elif row.source == "settings":
            source_style = ""
        else:
            source_style = "muted"
        source = Text(row.source, style=source_style)
        if row.requires_migration:
            source.append("  ⚠", style="warn")
        table.add_row(row.key, value, source)
    console.print(table)

    if any(r.requires_migration for r in snapshot.settings):
        console.print()
        note = Text("⚠ ", style="warn")
        note.append(
            "changing these re-embeds stored memories — set the env var, then "
            "run mc-tool-memory reindex.",
            style="muted",
        )
        console.print(note, soft_wrap=True)
    if snapshot.drift:
        console.print()
        drift = Text("⚠ ", style="warn")
        drift.append(snapshot.drift, style="warn")
        console.print(drift, soft_wrap=True)
