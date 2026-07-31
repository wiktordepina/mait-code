"""Curated tool-approval presets for Claude Code's permission system.

Claude Code prompts for approval on every ``Bash`` call unless a rule in
``permissions.allow`` matches. The genuinely safe, high-frequency commands
(``git status``, ``wc``, ``uv run ruff``, ``mc-tool-board list``) get approved
dozens of times a session for no benefit, which trains the reflex of approving
without reading. This module owns a small, hand-curated catalogue of such rules
plus the read/merge/scope machinery to write them into the right settings file.

**Scopes.** Claude Code unions ``permissions.allow`` across three files, so a
rule's origin has to be visible or the UI misrepresents what is in effect:

===================  ==========================================  ==============
Scope                File                                        Notes
===================  ==========================================  ==============
``global``           ``~/.claude/settings.json``                  everywhere
``project-shared``   ``<repo>/.claude/settings.json``             committed
``project-local``    ``<repo>/.claude/settings.local.json``       gitignored
===================  ==========================================  ==============

``project-local`` is the default target: approval preferences are personal, and
writing them into a committed file changes behaviour for everyone who clones the
repo.

**The prefix hazard.** A ``Bash(<prefix>:*)`` rule is a *raw string prefix*
match, so it cannot express "this subcommand but not that flag" — and it does
not respect word boundaries. Two consequences drive what is in the catalogue:

* ``Bash(mc-tool-board next:*)`` would also permit ``next --claim``, which
  claims a card; ``Bash(mc-tool-memory entities:*)`` would permit
  ``entities merge``, which rewrites the graph. Both are excluded.
* ``Bash(mc-tool-memory review:*)`` would also permit ``mc-tool-memory
  reviewed``, a *different, mutating* subcommand that merely shares a prefix.
  Excluded for the same reason, despite reading as safe.

:func:`matches_command` implements the permissive (raw-prefix) reading
deliberately: the catalogue is guarded against the worst case a real matcher
might do, not the best case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mait_code.cli._paths import claude_dir
from mait_code.cli._settings import write_settings_file

__all__ = [
    # Catalogue
    "ALLOW_PRESETS",
    "MUTATING_INVOCATIONS",
    "MUTATING_VERBS",
    "TIERS",
    "Preset",
    "preset_by_id",
    "preset_groups",
    # Scopes
    "DEFAULT_SCOPE",
    "SCOPES",
    "Scope",
    "available_scopes",
    "repo_root",
    "scope_by_id",
    "scope_path",
    # Reading
    "PermissionsFileError",
    "PresetState",
    "ScopeSnapshot",
    "allow_rules",
    "matches_command",
    "read_scopes",
    "resolve_states",
    # Writing
    "WriteOutcome",
    "disable_preset",
    "enable_preset",
    # Rendering
    "presets_json",
    "render_presets",
]


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------

TIERS = ("read-only", "writes-workspace")
"""Valid :attr:`Preset.tier` values.

``read-only`` touches nothing on disk. ``writes-workspace`` may rewrite tracked
files in the repo or drop caches — reversible through git, but not read-only,
so the UI labels it and the user opts in knowing that.
"""


@dataclass(frozen=True)
class Preset:
    """One opt-in bundle of ``permissions.allow`` rules.

    Attributes:
        id: Stable kebab-case identifier — the key the TUI and tests address a
            preset by. Never reuse or renumber; the settings files store the
            patterns, not the id, so a rename silently orphans nothing but does
            break any user-facing reference.
        group: Display group heading in the settings tree.
        label: Short human-readable name.
        rationale: One line on why this is safe to auto-approve, and (for
            ``writes-workspace``) what it writes.
        patterns: The literal ``permissions.allow`` entries this preset owns.
        tier: One of :data:`TIERS`.
    """

    id: str
    group: str
    label: str
    rationale: str
    patterns: tuple[str, ...]
    tier: str = "read-only"


ALLOW_PRESETS: tuple[Preset, ...] = (
    # -- Git (read-only) ---------------------------------------------------
    Preset(
        id="git-status",
        group="Git (read-only)",
        label="git status",
        rationale="Reports the working tree; has no mutating flags.",
        patterns=("Bash(git status:*)",),
    ),
    Preset(
        id="git-diff",
        group="Git (read-only)",
        label="git diff",
        rationale="Prints changes; no flag writes to the repository.",
        patterns=("Bash(git diff:*)",),
    ),
    Preset(
        id="git-log",
        group="Git (read-only)",
        label="git log",
        rationale="Reads history only.",
        patterns=("Bash(git log:*)",),
    ),
    Preset(
        id="git-show",
        group="Git (read-only)",
        label="git show",
        rationale="Reads objects only; also covers show-ref and show-branch.",
        patterns=("Bash(git show:*)",),
    ),
    Preset(
        id="git-blame",
        group="Git (read-only)",
        label="git blame",
        rationale="Reads line provenance only.",
        patterns=("Bash(git blame:*)",),
    ),
    # -- File inspection ---------------------------------------------------
    Preset(
        id="list-dir",
        group="File inspection",
        label="ls",
        rationale="Lists directories; also matches lsof/lsblk, both read-only.",
        patterns=("Bash(ls:*)",),
    ),
    Preset(
        id="count-lines",
        group="File inspection",
        label="wc",
        rationale="Counts lines, words and bytes.",
        patterns=("Bash(wc:*)",),
    ),
    Preset(
        id="head-tail",
        group="File inspection",
        label="head / tail",
        rationale="Prints the ends of a file. Note that tail -f blocks.",
        patterns=("Bash(head:*)", "Bash(tail:*)"),
    ),
    Preset(
        id="file-stat",
        group="File inspection",
        label="file / stat",
        rationale="Reports file type and metadata.",
        patterns=("Bash(file:*)", "Bash(stat:*)"),
    ),
    Preset(
        id="disk-usage",
        group="File inspection",
        label="du / tree",
        rationale="Summarises sizes and directory shape.",
        patterns=("Bash(du:*)", "Bash(tree:*)"),
    ),
    # -- Project tooling ---------------------------------------------------
    Preset(
        id="uv-tree",
        group="Project tooling",
        label="uv tree",
        rationale="Prints the resolved dependency tree; does not touch the lock.",
        patterns=("Bash(uv tree:*)",),
    ),
    Preset(
        id="pyright",
        group="Project tooling",
        label="uv run pyright",
        rationale="Type-checks without modifying sources.",
        patterns=("Bash(uv run pyright:*)",),
    ),
    Preset(
        id="ruff-check",
        group="Project tooling",
        label="uv run ruff check",
        rationale=(
            "Lints the tree. Prefix matching also permits --fix, which rewrites "
            "tracked sources — reversible with git, but not read-only."
        ),
        patterns=("Bash(uv run ruff check:*)",),
        tier="writes-workspace",
    ),
    Preset(
        id="ruff-format",
        group="Project tooling",
        label="uv run ruff format",
        rationale="Reformats tracked sources in place; reversible with git.",
        patterns=("Bash(uv run ruff format:*)",),
        tier="writes-workspace",
    ),
    Preset(
        id="pytest",
        group="Project tooling",
        label="uv run pytest",
        rationale=(
            "Runs the project's own test code and writes .pytest_cache — safe "
            "for this repo, but it does execute arbitrary project code."
        ),
        patterns=("Bash(uv run pytest:*)",),
        tier="writes-workspace",
    ),
    # -- mait-code tools ---------------------------------------------------
    Preset(
        id="board-read",
        group="mait-code tools",
        label="mc-tool-board (read-only)",
        rationale=(
            "list/show/export/summary only. 'next' is excluded: --claim mutates "
            "and prefix matching cannot exclude a flag."
        ),
        patterns=(
            "Bash(mc-tool-board list:*)",
            "Bash(mc-tool-board show:*)",
            "Bash(mc-tool-board export:*)",
            "Bash(mc-tool-board summary:*)",
        ),
    ),
    Preset(
        id="memory-read",
        group="mait-code tools",
        label="mc-tool-memory (read-only)",
        rationale=(
            "search/list/stats/relationships only. 'entities' is excluded "
            "(entities merge mutates) and so is 'review' — as a raw prefix it "
            "would also permit the mutating 'reviewed'."
        ),
        patterns=(
            "Bash(mc-tool-memory search:*)",
            "Bash(mc-tool-memory list:*)",
            "Bash(mc-tool-memory stats:*)",
            "Bash(mc-tool-memory relationships:*)",
        ),
    ),
    Preset(
        id="reminders-read",
        group="mait-code tools",
        label="mc-tool-reminders list",
        rationale=(
            "Lists active reminders. 'check' is excluded pending confirmation "
            "that it does not mark reminders notified."
        ),
        patterns=("Bash(mc-tool-reminders list:*)",),
    ),
    Preset(
        id="inbox-read",
        group="mait-code tools",
        label="mc-tool-inbox (read-only)",
        rationale="list/count only; 'drain' pulls from the Bridge and mutates.",
        patterns=(
            "Bash(mc-tool-inbox list:*)",
            "Bash(mc-tool-inbox count:*)",
        ),
    ),
)
"""The curated catalogue, in display order."""


MUTATING_VERBS: tuple[str, ...] = (
    "add",
    "checkout",
    "claim",
    "clean",
    "commit",
    "delete",
    "drain",
    "install",
    "merge",
    "mv",
    "push",
    "rebase",
    "remove",
    "reset",
    "restore",
    "retire",
    "rm",
    "set",
    "store",
    "supersede",
    "sync",
    "write",
)
"""Command tokens that must never appear in a ``read-only`` preset's pattern.

A blunt instrument on purpose — it catches a mutating subcommand slipping into
the catalogue by inattention, which is the realistic failure mode.
"""


MUTATING_INVOCATIONS: tuple[str, ...] = (
    "git push origin main",
    "git reset --hard HEAD~1",
    "git commit -m wip",
    "git checkout -- .",
    "git clean -fdx",
    "git rebase -i HEAD~3",
    "rm -rf /tmp/scratch",
    "uv add requests",
    "uv sync --extra bedrock",
    "uv pip install requests",
    "find . -delete",
    "find . -exec rm {} ;",
    "mc-tool-board next --claim",
    "mc-tool-board add title",
    "mc-tool-board complete 3 --summary done",
    "mc-tool-board remove 3",
    "mc-tool-board archive 3",
    "mc-tool-board edit 3 --title x",
    "mc-tool-memory entities merge 1 2",
    "mc-tool-memory store --text x",
    "mc-tool-memory delete 3",
    "mc-tool-memory retire 3",
    "mc-tool-memory reviewed 3",
    "mc-tool-memory supersede 3 --text x",
    "mc-tool-memory reindex",
    "mc-tool-memory restore",
    "mc-tool-inbox drain",
    "mc-tool-inbox add note",
    "mc-tool-inbox remove 1",
    "mc-tool-reminders set tomorrow",
    "mc-tool-reminders dismiss 1",
    "mc-tool-reminders check",
)
"""Concrete mutating command lines no catalogue pattern may permit.

Every entry is a real invocation of a tool the catalogue also covers, chosen so
a careless preset (``Bash(mc-tool-board next:*)``) fails the guard test rather
than shipping.
"""


def preset_by_id(preset_id: str) -> Preset:
    """Return the preset with *preset_id*.

    Raises:
        KeyError: If no such preset exists.
    """
    for preset in ALLOW_PRESETS:
        if preset.id == preset_id:
            return preset
    raise KeyError(preset_id)


def preset_groups() -> tuple[tuple[str, tuple[Preset, ...]], ...]:
    """Return the catalogue grouped by :attr:`Preset.group`, in display order."""
    order: list[str] = []
    buckets: dict[str, list[Preset]] = {}
    for preset in ALLOW_PRESETS:
        if preset.group not in buckets:
            buckets[preset.group] = []
            order.append(preset.group)
        buckets[preset.group].append(preset)
    return tuple((name, tuple(buckets[name])) for name in order)


# --------------------------------------------------------------------------
# Scopes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """One settings file that Claude Code reads permission rules from.

    Attributes:
        id: Stable identifier (``global``, ``project-shared``, ``project-local``).
        label: Short display name.
        help: The consequence of choosing this scope, in a few words. Kept
            terse on purpose — it rides inside a radio-button label in a
            half-width pane, and a longer sentence truncates to uselessness
            exactly where the committed/gitignored distinction matters most.
        project: ``True`` when the scope lives inside the repo and is therefore
            unavailable outside a git working tree.
    """

    id: str
    label: str
    help: str
    project: bool


SCOPES: tuple[Scope, ...] = (
    Scope(
        id="global",
        label="Global",
        help="every project",
        project=False,
    ),
    Scope(
        id="project-shared",
        label="Project (shared)",
        help="committed — affects teammates",
        project=True,
    ),
    Scope(
        id="project-local",
        label="Project (local)",
        help="gitignored — just you",
        project=True,
    ),
)
"""Every scope, in the order the picker offers them."""

DEFAULT_SCOPE = "project-local"
"""Where a toggle writes unless the user picks otherwise.

Approval preferences are personal; defaulting to the committed project file
would change behaviour for everyone who clones the repo.
"""


def scope_by_id(scope_id: str) -> Scope:
    """Return the scope with *scope_id*.

    Raises:
        KeyError: If no such scope exists.
    """
    for scope in SCOPES:
        if scope.id == scope_id:
            return scope
    raise KeyError(scope_id)


def repo_root(start: Path | None = None) -> Path | None:
    """Return the git working-tree root containing *start*, or ``None``.

    Walks up looking for a ``.git`` entry rather than shelling out to git —
    this runs on every settings-tree render, and a subprocess per render is
    not worth it. Works for worktrees and submodules too, where ``.git`` is a
    file rather than a directory.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def scope_path(scope_id: str, *, root: Path | None = None) -> Path | None:
    """Return the settings file backing *scope_id*.

    Args:
        scope_id: One of the :data:`SCOPES` ids.
        root: The repo root for project scopes. ``None`` means "not in a repo",
            and project scopes then resolve to ``None`` rather than raising —
            the caller greys the row out.

    Returns:
        The path, or ``None`` when a project scope has no repo to live in.

    Raises:
        KeyError: If *scope_id* is not a known scope.
    """
    scope = scope_by_id(scope_id)
    if not scope.project:
        return claude_dir() / "settings.json"
    if root is None:
        return None
    if scope.id == "project-shared":
        return root / ".claude" / "settings.json"
    return root / ".claude" / "settings.local.json"


def available_scopes(*, root: Path | None = None) -> tuple[Scope, ...]:
    """Return the scopes writable in the current context.

    Outside a git repo this is the global scope alone.
    """
    return tuple(s for s in SCOPES if scope_path(s.id, root=root) is not None)


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


class PermissionsFileError(RuntimeError):
    """A settings file could not be read, or is not a JSON object.

    Raised rather than swallowed so a malformed file is reported to the user
    instead of being silently replaced. :func:`mait_code.cli._settings.
    read_settings_file` returns ``{}`` on a parse error, which is the right
    behaviour at install time and exactly the wrong behaviour here — it would
    turn "your JSON has a trailing comma" into "your settings are gone".
    """


def _read_document(path: Path) -> dict[str, Any]:
    """Read a settings.json, distinguishing "missing" from "malformed".

    Returns:
        The parsed object, or ``{}`` when the file does not exist.

    Raises:
        PermissionsFileError: If the file exists but is unreadable, is not
            valid JSON, or does not hold a JSON object.
    """
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PermissionsFileError(f"{path} could not be read: {exc}") from exc
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PermissionsFileError(
            f"{path} is not valid JSON (line {exc.lineno}, column {exc.colno}): "
            f"{exc.msg}. Fix it by hand — refusing to overwrite it."
        ) from exc
    if not isinstance(parsed, dict):
        raise PermissionsFileError(
            f"{path} does not contain a JSON object — refusing to overwrite it."
        )
    return parsed


def allow_rules(path: Path) -> tuple[str, ...]:
    """Return the ``permissions.allow`` entries in the settings file at *path*.

    Non-string entries and a non-list ``allow`` are tolerated (they are the
    user's, not ours) and simply contribute nothing.

    Raises:
        PermissionsFileError: If the file exists but cannot be parsed.
    """
    document = _read_document(path)
    permissions = document.get("permissions")
    if not isinstance(permissions, dict):
        return ()
    allow = permissions.get("allow")
    if not isinstance(allow, list):
        return ()
    return tuple(rule for rule in allow if isinstance(rule, str))


def matches_command(pattern: str, command: str) -> bool:
    """Return ``True`` if a ``Bash(...)`` *pattern* would permit *command*.

    Implements the permissive reading of Claude Code's prefix matching: a
    ``:*`` suffix matches any command whose text starts with the prefix, with
    **no word-boundary requirement**. That is what makes
    ``Bash(mc-tool-memory review:*)`` dangerous — it also spans ``reviewed``.
    Modelling the worst case here means the catalogue guard in the test suite
    rejects such a pattern instead of trusting a friendlier matcher.

    Non-``Bash(...)`` patterns never match; a pattern without ``:*`` matches
    only the exact command.
    """
    if not (pattern.startswith("Bash(") and pattern.endswith(")")):
        return False
    body = pattern[len("Bash(") : -1]
    if body.endswith(":*"):
        return command.startswith(body[: -len(":*")])
    return command == body


@dataclass(frozen=True)
class PresetState:
    """Where a preset currently stands across the three scopes.

    Attributes:
        preset: The catalogue entry.
        enabled_scopes: Scope ids holding *every* pattern of the preset.
        partial_scopes: Scope ids holding some but not all of them — usually a
            hand-edited file, and worth showing rather than rounding to "off".
    """

    preset: Preset
    enabled_scopes: tuple[str, ...] = ()
    partial_scopes: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        """``True`` when the preset is fully present in at least one scope."""
        return bool(self.enabled_scopes)

    @property
    def origin(self) -> str | None:
        """The first scope that fully enables this preset, if any."""
        return self.enabled_scopes[0] if self.enabled_scopes else None


@dataclass
class ScopeSnapshot:
    """The allow rules read from each available scope.

    Attributes:
        rules: Scope id → the rules found there.
        errors: Scope id → the message for a scope that could not be read.
    """

    rules: dict[str, tuple[str, ...]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def read_scopes(*, root: Path | None = None) -> ScopeSnapshot:
    """Read the allow rules from every available scope.

    A scope whose file is malformed lands in :attr:`ScopeSnapshot.errors`
    rather than aborting the whole render — one broken file should not blank
    the settings tree.
    """
    snapshot = ScopeSnapshot()
    for scope in available_scopes(root=root):
        path = scope_path(scope.id, root=root)
        assert path is not None  # available_scopes filtered these out
        try:
            snapshot.rules[scope.id] = allow_rules(path)
        except PermissionsFileError as exc:
            snapshot.errors[scope.id] = str(exc)
    return snapshot


def resolve_states(*, root: Path | None = None) -> tuple[PresetState, ...]:
    """Resolve every catalogue preset against the on-disk scopes."""
    snapshot = read_scopes(root=root)
    states: list[PresetState] = []
    for preset in ALLOW_PRESETS:
        enabled: list[str] = []
        partial: list[str] = []
        for scope_id, rules in snapshot.rules.items():
            present = sum(1 for pattern in preset.patterns if pattern in rules)
            if present == len(preset.patterns):
                enabled.append(scope_id)
            elif present:
                partial.append(scope_id)
        states.append(
            PresetState(
                preset=preset,
                enabled_scopes=tuple(enabled),
                partial_scopes=tuple(partial),
            )
        )
    return tuple(states)


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

_BACKED_UP: set[Path] = set()
"""Files already backed up in this process — the backup is once per file.

Module state so a session of toggling presets leaves one backup per settings
file rather than one per keystroke.
"""


@dataclass(frozen=True)
class WriteOutcome:
    """What a single :func:`enable_preset` / :func:`disable_preset` write did.

    Attributes:
        preset_id: The preset that was toggled.
        scope_id: The scope written to.
        path: The settings file written.
        added: Patterns appended to ``permissions.allow``.
        removed: Patterns deleted from it.
        backup: The backup taken before the first write to *path*, if any.
    """

    preset_id: str
    scope_id: str
    path: Path
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    backup: Path | None = None

    @property
    def changed(self) -> bool:
        """``True`` when the file was actually rewritten."""
        return bool(self.added or self.removed)


def _backup(path: Path) -> Path | None:
    """Copy *path* aside once per process before the first write to it."""
    if path in _BACKED_UP or not path.exists():
        _BACKED_UP.add(path)
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = path.parent / f"{path.name}.bak-{stamp}"
    destination.write_bytes(path.read_bytes())
    _BACKED_UP.add(path)
    return destination


def _resolve_target(scope_id: str, root: Path | None) -> Path:
    """Return the writable path for *scope_id*, or explain why there isn't one."""
    path = scope_path(scope_id, root=root)
    if path is None:
        raise PermissionsFileError(
            f"the {scope_by_id(scope_id).label!r} scope needs a git repository; "
            "there is none here — use the global scope instead."
        )
    return path


def _write_allow(path: Path, document: dict[str, Any], allow: list[str]) -> None:
    """Persist *allow* into *document*'s permissions block and write it out.

    Unrelated keys — top-level and inside ``permissions`` — are preserved,
    and an empty result drops the key rather than leaving ``"allow": []``.
    """
    permissions = document.get("permissions")
    permissions = dict(permissions) if isinstance(permissions, dict) else {}
    if allow:
        permissions["allow"] = allow
    else:
        permissions.pop("allow", None)
    if permissions:
        document["permissions"] = permissions
    else:
        document.pop("permissions", None)
    write_settings_file(path, document)


def enable_preset(
    preset_id: str,
    scope_id: str,
    *,
    root: Path | None = None,
) -> WriteOutcome:
    """Add a preset's patterns to *scope_id*'s ``permissions.allow``.

    Idempotent: patterns already present are left alone rather than duplicated,
    and a preset that is already fully enabled writes nothing at all. Existing
    rules keep their order — new patterns are appended.

    Args:
        preset_id: A catalogue preset id.
        scope_id: Which settings file to write.
        root: Repo root for project scopes (see :func:`repo_root`).

    Returns:
        A :class:`WriteOutcome`; ``changed`` is ``False`` for a no-op.

    Raises:
        KeyError: If *preset_id* or *scope_id* is unknown.
        PermissionsFileError: If the scope is unavailable here, or the target
            file exists but cannot be parsed.
    """
    preset = preset_by_id(preset_id)
    path = _resolve_target(scope_id, root)
    document = _read_document(path)
    existing = allow_rules(path)
    missing = tuple(p for p in preset.patterns if p not in existing)
    if not missing:
        return WriteOutcome(preset_id=preset_id, scope_id=scope_id, path=path)
    backup = _backup(path)
    _write_allow(path, document, [*existing, *missing])
    return WriteOutcome(
        preset_id=preset_id,
        scope_id=scope_id,
        path=path,
        added=missing,
        backup=backup,
    )


def disable_preset(
    preset_id: str,
    *,
    scope_id: str | None = None,
    root: Path | None = None,
) -> tuple[WriteOutcome, ...]:
    """Remove a preset's patterns from one scope, or from every scope holding it.

    Passing *scope_id* targets that file alone. Leaving it ``None`` removes the
    preset wherever it appears — Claude Code unions the three files, so leaving
    a copy behind in another scope would keep the rule in force while the UI
    showed it off.

    Only this preset's own patterns are touched; hand-written rules that merely
    look similar are left in place, as is their order.

    Returns:
        One :class:`WriteOutcome` per scope actually rewritten — empty when the
        preset was not present anywhere.

    Raises:
        KeyError: If *preset_id* or *scope_id* is unknown.
        PermissionsFileError: If a targeted scope is unavailable or malformed.
    """
    preset = preset_by_id(preset_id)
    targets = [scope_id] if scope_id else [s.id for s in available_scopes(root=root)]
    outcomes: list[WriteOutcome] = []
    for target in targets:
        path = _resolve_target(target, root)
        try:
            document = _read_document(path)
            existing = allow_rules(path)
        except PermissionsFileError:
            # An explicit target must surface its error; a sweep skips a broken
            # file rather than refusing to disable anywhere.
            if scope_id:
                raise
            continue
        doomed = tuple(p for p in preset.patterns if p in existing)
        if not doomed:
            continue
        backup = _backup(path)
        _write_allow(path, document, [r for r in existing if r not in doomed])
        outcomes.append(
            WriteOutcome(
                preset_id=preset_id,
                scope_id=target,
                path=path,
                removed=doomed,
                backup=backup,
            )
        )
    return tuple(outcomes)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def presets_json(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Return every preset's state as plain dicts, for ``--json`` output."""
    return [
        {
            "id": state.preset.id,
            "group": state.preset.group,
            "label": state.preset.label,
            "tier": state.preset.tier,
            "patterns": list(state.preset.patterns),
            "enabled": state.enabled,
            "enabled_scopes": list(state.enabled_scopes),
            "partial_scopes": list(state.partial_scopes),
        }
        for state in resolve_states(root=root)
    ]


def render_presets(*, root: Path | None = None) -> None:
    """Print the enabled tool-approval presets to the shared console.

    The read-only counterpart of the settings TUI's Tool approvals group: it
    reports what is switched on and in which file, so the non-TTY view is not
    silent about rules that are actually in force. Rich is imported lazily to
    match :func:`mait_code.config.render`.
    """
    from rich.table import Table
    from rich.text import Text

    from mait_code.console import console

    snapshot = read_scopes(root=root)
    states = resolve_states(root=root)

    console.rule(style="muted")
    header = Text("tool approvals", style="accent")
    header.append("   (read-only)", style="muted")
    console.print(header)

    for scope in SCOPES:
        path = scope_path(scope.id, root=root)
        line = Text(f"{scope.label}: ", style="muted")
        if path is None:
            line.append("unavailable (not in a git repository)", style="muted")
        else:
            line.append(str(path).replace(str(Path.home()), "~"))
            if scope.id in snapshot.errors:
                line.append("  (unreadable)", style="warn")
            elif not path.exists():
                line.append("  (not created yet)", style="muted")
        console.print(line)

    enabled = [s for s in states if s.enabled_scopes or s.partial_scopes]
    if not enabled:
        console.print(
            Text(
                f"no presets enabled — {len(states)} available in 'mait-code settings'",
                style="muted",
            )
        )
    else:
        table = Table(box=None, pad_edge=False, header_style="muted")
        table.add_column("PRESET", style="bold", no_wrap=True)
        table.add_column("TIER", no_wrap=True)
        table.add_column("SCOPE", no_wrap=True)
        for state in enabled:
            scopes = [scope_by_id(s).label for s in state.enabled_scopes] + [
                f"{scope_by_id(s).label} (partial)" for s in state.partial_scopes
            ]
            tier_style = "" if state.preset.tier == "read-only" else "warn"
            table.add_row(
                state.preset.label,
                Text(state.preset.tier, style=tier_style),
                ", ".join(scopes),
            )
        console.print(table)

    for scope_id, message in snapshot.errors.items():
        console.print(Text(f"⚠ {scope_by_id(scope_id).label}: {message}", style="warn"))
