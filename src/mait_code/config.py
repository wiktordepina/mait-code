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
import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    # Registry
    "Setting",
    "SETTINGS",
    "resolve",
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
    """One user-facing configuration knob, read from an environment variable.

    Attributes:
        key: Stable, kebab-case identifier shown by ``mait-code settings``.
        env: The environment variable that backs it.
        default: Display string for the default value (``<data-dir>``-style
            placeholders are allowed where the real default is derived).
        requires_migration: ``True`` when changing it invalidates stored
            embeddings (provider/model changes need a re-embed).
        secret: ``True`` when the value should be masked in output.
        help: One-line description.
    """

    key: str
    env: str
    default: str
    requires_migration: bool = False
    secret: bool = False
    help: str = ""


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
        "<data-dir>/logs/mait-code.log",
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


def resolve(setting: Setting) -> tuple[str, str]:
    """Return ``(value, source)`` for display.

    ``source`` is ``"env"`` when the variable is set to a non-empty value,
    otherwise ``"default"``. This *reports* configuration; it does not
    validate it — that is ``doctor``'s job.
    """
    raw = os.environ.get(setting.env)
    if raw is not None and raw.strip() != "":
        return raw, "env"
    return setting.default, "default"


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
# Settings view — read-only snapshot for `mait-code settings`.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedSetting:
    """A setting with its resolved value and provenance, for display."""

    key: str
    value: str
    source: str  # "env" or "default"
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


def collect_settings(recorded_provider: str | None = None) -> SettingsSnapshot:
    """Resolve every setting for display, and flag embedding-provider drift.

    Args:
        recorded_provider: The embedding provider stored in the install
            record, if any. When it disagrees with the active provider the
            snapshot carries a drift warning — memories embedded with one
            provider can't be searched with another.

    Returns:
        A read-only :class:`SettingsSnapshot`.
    """
    rows: list[ResolvedSetting] = []
    active_provider: str | None = None
    for setting in SETTINGS:
        value, source = resolve(setting)
        if setting.key == "embedding-provider":
            active_provider = value
        if setting.secret and source == "env":
            value = _mask(value)
        rows.append(
            ResolvedSetting(setting.key, value, source, setting.requires_migration)
        )

    drift: str | None = None
    if recorded_provider and active_provider and recorded_provider != active_provider:
        drift = (
            f"active embedding-provider is '{active_provider}', but memories "
            f"were embedded with '{recorded_provider}' — run "
            f"mc-tool-memory reindex to re-embed"
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

    header = Text("mait-code settings", style="accent")
    header.append("   (read-only)", style="muted")
    console.print(header)
    console.rule(style="muted")

    table = Table(box=None, pad_edge=False, header_style="muted")
    table.add_column("SETTING", style="bold", no_wrap=True)
    table.add_column("VALUE")
    table.add_column("SOURCE", no_wrap=True)
    for row in snapshot.settings:
        value = Text(row.value, style="muted" if row.source == "default" else "")
        source = Text(row.source, style="warn" if row.source == "env" else "muted")
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
