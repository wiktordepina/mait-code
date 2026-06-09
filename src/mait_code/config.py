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
    "reset_cache",
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
    "DEFAULT_THEME",
]


# Defaults, defined once and shared with the embedding providers and the
# settings registry below.
DEFAULT_DATA_DIR_DISPLAY = "~/.claude/mait-code-data"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_EMBEDDING_PROVIDER = "local"
DEFAULT_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_BEDROCK_MODEL_ID = "amazon.titan-embed-text-v2:0"
DEFAULT_BEDROCK_REGION = "eu-west-2"
DEFAULT_THEME = "mait-dark"


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
        choices: Optional fixed set of valid values for an enum-like setting
            (e.g. ``embedding-provider`` → ``("local", "bedrock")``). Drives
            the interactive editor's picker; the matching :attr:`validate`
            enforces membership for ``set`` and ``doctor``.
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
    choices: tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Derived-value helpers (Tier 2 display-only settings). Pure — no mkdir — so
# `mait-code settings` stays read-only. Each mirrors a runtime path helper;
# tests in test_config.py pin them together to guard against drift.
# ---------------------------------------------------------------------------


def _display_path(*parts: str) -> str:
    """Join *parts* under the data dir, abbreviating ``$HOME`` to ``~``."""
    text = str(data_dir().joinpath(*parts))
    home = str(Path.home())
    return "~" + text[len(home) :] if text.startswith(home) else text


def _derive_embedding_dim() -> str:
    """Embedding vector size for the configured provider/model."""
    from mait_code.tools.memory.embeddings import _get_embedding_dim

    return str(_get_embedding_dim())


# ---------------------------------------------------------------------------
# Per-value validators (run by `doctor` via validate_settings()).
# ---------------------------------------------------------------------------


def _positive_int(value: str) -> str | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return f"must be an integer, got {value!r}"
    return None if n > 0 else f"must be a positive integer, got {n}"


def _non_negative_int(value: str) -> str | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return f"must be an integer, got {value!r}"
    return None if n >= 0 else f"must be zero or greater, got {n}"


def _non_empty(value: str) -> str | None:
    return None if value.strip() else "must not be empty"


_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def _log_level(value: str) -> str | None:
    return (
        None
        if value.upper() in _LOG_LEVELS
        else f"must be one of {', '.join(_LOG_LEVELS)}, got {value!r}"
    )


# Valid embedding backends. Kept in step with ``cli._install.EMBEDDING_PROVIDERS``
# (pinned by a test) — config stays the leaf, so the constant lives here.
_EMBEDDING_PROVIDERS = ("local", "bedrock")


def _embedding_provider(value: str) -> str | None:
    return (
        None
        if value in _EMBEDDING_PROVIDERS
        else f"must be one of {', '.join(_EMBEDDING_PROVIDERS)}, got {value!r}"
    )


def _unit_interval(value: str) -> str | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return f"must be a number, got {value!r}"
    return None if 0.0 <= f <= 1.0 else f"must be in [0, 1], got {f}"


def _positive_float(value: str) -> str | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return f"must be a number, got {value!r}"
    return None if f > 0.0 else f"must be greater than zero, got {f}"


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
        validate=_log_level,
        choices=_LOG_LEVELS,
    ),
    Setting(
        "log-file",
        "MAIT_CODE_LOG_FILE",
        "<state-dir>/mait-code.log",
        help="Override the log file path.",
    ),
    Setting(
        "theme",
        "MAIT_CODE_THEME",
        DEFAULT_THEME,
        help="TUI colour theme; any registered theme, unknown names fall back to mait-dark.",
        validate=_non_empty,
    ),
    Setting(
        "embedding-provider",
        "MAIT_CODE_EMBEDDING_PROVIDER",
        DEFAULT_EMBEDDING_PROVIDER,
        requires_migration=True,
        help="Embedding backend: 'local' or 'bedrock'.",
        validate=_embedding_provider,
        choices=_EMBEDDING_PROVIDERS,
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
    # --- Tier 3: advanced operational knobs (commented-out by default) ---
    Setting(
        "log-backup-count",
        "MAIT_CODE_LOG_BACKUP_COUNT",
        "14",
        kind="int",
        advanced=True,
        validate=_positive_int,
        help="Days of rotated log files to keep.",
    ),
    Setting(
        "extraction-model",
        "MAIT_CODE_EXTRACTION_MODEL",
        "haiku",
        advanced=True,
        help="Model used for memory extraction (fast/cheap by default).",
    ),
    Setting(
        "reflection-model",
        "MAIT_CODE_REFLECTION_MODEL",
        "haiku",
        advanced=True,
        help="Model used for reflection synthesis.",
    ),
    Setting(
        "llm-timeout",
        "MAIT_CODE_LLM_TIMEOUT",
        "90",
        kind="int",
        advanced=True,
        validate=_positive_int,
        help="Timeout (seconds) for subprocess LLM calls.",
    ),
    Setting(
        "reflection-batch-size",
        "MAIT_CODE_REFLECTION_BATCH_SIZE",
        "50",
        kind="int",
        advanced=True,
        validate=_positive_int,
        help="Default entries processed per reflection (--batch-size overrides).",
    ),
    Setting(
        "reflection-novelty-gate",
        "MAIT_CODE_REFLECTION_NOVELTY_GATE",
        "3",
        kind="int",
        advanced=True,
        validate=_non_negative_int,
        help="Default new entries required to trigger reflection (--min-new overrides).",
    ),
    Setting(
        "git-timeout",
        "MAIT_CODE_GIT_TIMEOUT",
        "5",
        kind="int",
        advanced=True,
        validate=_positive_int,
        help="Timeout (seconds) for git context probes.",
    ),
    # --- Tier 4: scoring / dedup tuning (advanced, validated) ---
    Setting(
        "score-weight-recency",
        "MAIT_CODE_SCORE_WEIGHT_RECENCY",
        "0.3",
        kind="float",
        advanced=True,
        validate=_unit_interval,
        help="Scoring weight for recency (the three weights must sum to 1.0).",
    ),
    Setting(
        "score-weight-importance",
        "MAIT_CODE_SCORE_WEIGHT_IMPORTANCE",
        "0.3",
        kind="float",
        advanced=True,
        validate=_unit_interval,
        help="Scoring weight for importance (the three weights must sum to 1.0).",
    ),
    Setting(
        "score-weight-relevance",
        "MAIT_CODE_SCORE_WEIGHT_RELEVANCE",
        "0.4",
        kind="float",
        advanced=True,
        validate=_unit_interval,
        help="Scoring weight for relevance (the three weights must sum to 1.0).",
    ),
    Setting(
        "half-life-episodic",
        "MAIT_CODE_HALF_LIFE_EPISODIC",
        "3.0",
        kind="float",
        advanced=True,
        validate=_positive_float,
        help="Recency half-life (days) for episodic memories (events, tasks).",
    ),
    Setting(
        "half-life-semantic",
        "MAIT_CODE_HALF_LIFE_SEMANTIC",
        "90.0",
        kind="float",
        advanced=True,
        validate=_positive_float,
        help="Recency half-life (days) for semantic memories (facts, preferences).",
    ),
    Setting(
        "dedup-string-threshold",
        "MAIT_CODE_DEDUP_STRING_THRESHOLD",
        "0.85",
        kind="float",
        advanced=True,
        validate=_unit_interval,
        help="String-similarity threshold above which a memory is a duplicate.",
    ),
    Setting(
        "dedup-vector-threshold",
        "MAIT_CODE_DEDUP_VECTOR_THRESHOLD",
        "0.92",
        kind="float",
        advanced=True,
        validate=_unit_interval,
        help="Cosine-similarity threshold above which a memory is a duplicate.",
    ),
    Setting(
        "dedup-conflict-threshold",
        "MAIT_CODE_DEDUP_CONFLICT_THRESHOLD",
        "0.60",
        kind="float",
        advanced=True,
        validate=_unit_interval,
        help=(
            "Lower edge of the contradiction band. Cosine similarity in "
            "[this, dedup-vector-threshold) flags a possible conflict rather "
            "than merging or storing silently."
        ),
    ),
    Setting(
        "scope-boost-global",
        "MAIT_CODE_SCOPE_BOOST_GLOBAL",
        "0.7",
        kind="float",
        advanced=True,
        validate=_unit_interval,
        help="Relevance multiplier applied to global-scoped memories.",
    ),
    Setting(
        "scope-boost-cross-project",
        "MAIT_CODE_SCOPE_BOOST_CROSS_PROJECT",
        "0.3",
        kind="float",
        advanced=True,
        validate=_unit_interval,
        help="Relevance multiplier applied across project boundaries.",
    ),
    # --- Tier 2: derived, display-only (settable=False) ---
    Setting(
        "embedding-dim",
        "",
        "",
        settable=False,
        kind="int",
        derive=_derive_embedding_dim,
        help="Embedding vector size (derived from provider + model).",
    ),
    Setting(
        "memory-db-path",
        "",
        "",
        settable=False,
        derive=lambda: _display_path("memory.db"),
        help="SQLite store for memories (derived from data-dir).",
    ),
    Setting(
        "reminders-db-path",
        "",
        "",
        settable=False,
        derive=lambda: _display_path("reminders.db"),
        help="SQLite store for reminders (derived from data-dir).",
    ),
    Setting(
        "model-cache-dir",
        "",
        "",
        settable=False,
        derive=lambda: _display_path("models"),
        help="Local embedding-model cache (derived from data-dir; can be ~550MB).",
    ),
    Setting(
        "observations-dir",
        "",
        "",
        settable=False,
        derive=lambda: _display_path("memory", "observations"),
        help="Observation JSONL logs (derived from data-dir).",
    ),
    Setting(
        "project-aliases-path",
        "",
        "",
        settable=False,
        derive=lambda: _display_path("project-aliases.json"),
        help="Project-alias map (derived from data-dir).",
    ),
)


_settings_cache: dict[str, str] | None = None


def _load_settings() -> dict[str, str]:
    """Return the cached settings-file contents, loading on first call."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = read_settings_file()
    return _settings_cache


def reset_cache() -> None:
    """Forget the cached settings-file contents.

    Call after writing the settings file in-process so a subsequent
    :func:`get` reflects the new value rather than the stale cache.
    """
    global _settings_cache
    _settings_cache = None


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


_WEIGHT_KEYS = (
    "score-weight-recency",
    "score-weight-importance",
    "score-weight-relevance",
)


def _cross_field_errors() -> list[str]:
    """Cross-field setting invariants (e.g. scoring weights must sum to 1.0)."""
    errors: list[str] = []
    by_key = _by_key()
    if all(k in by_key for k in _WEIGHT_KEYS):
        total = sum(get_float(k) for k in _WEIGHT_KEYS)
        if abs(total - 1.0) > 1e-6:
            errors.append(
                f"scoring weights sum to {total:.3f}, must be 1.0 "
                "(recency + importance + relevance)"
            )
    return errors


def data_dir() -> Path:
    """Return the mait-code data directory — the canonical resolver.

    Honours ``$MAIT_CODE_DATA_DIR`` when set to a non-empty value;
    otherwise ``~/.claude/mait-code-data``. Computed at call time so tests
    that relocate ``$HOME`` are honoured.

    A leading ``~`` in the override is expanded — otherwise a value like
    ``~/.claude/mait-code-data`` (a literal, unexpanded tilde from the
    environment) would resolve relative to the cwd, scattering data into a
    stray ``~`` directory instead of ``$HOME``.
    """
    override = os.environ.get("MAIT_CODE_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
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
    2. **Advanced** settable knobs — written *active* when *values* carries
       an explicit value (an opt-in via ``settings set``), otherwise
       commented-out showing the default as the example, so the hardcoded
       default stays authoritative until the user opts a line in.
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
            if setting.key in values:
                # Explicitly opted in (e.g. via `settings set`) — write active.
                lines.append(f'{setting.key} = "{values[setting.key]}"')
            else:
                lines.append(f'# {setting.key} = "{setting.default}"')
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
