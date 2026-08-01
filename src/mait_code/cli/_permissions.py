"""Curated tool-approval presets for Claude Code's permission system.

Claude Code prompts for approval on every ``Bash`` call unless a rule in
``permissions.allow`` matches. The genuinely safe, high-frequency commands
(``git status``, ``wc``, ``uv run ruff``, ``mc-tool-board list``) get approved
dozens of times a session for no benefit, which trains the reflex of approving
without reading. This module owns a small, hand-curated catalogue of such rules
plus the read/merge machinery to write them into the user's settings file.

**One file, deliberately.** Claude Code unions ``permissions.allow`` across
three files — ``~/.claude/settings.json``, ``<repo>/.claude/settings.json`` and
``<repo>/.claude/settings.local.json``. This module reads and writes the first
of those and nothing else.

Earlier versions offered all three, picking the repo by walking up from the
process's working directory. That made the *launch directory* an invisible
input: the same ``mait-code settings`` invocation showed different state and
pre-selected a different write target depending on which terminal it was opened
from, and from an unrelated repo it would happily target that repo's settings
file. No amount of picker UI fixes an input the user cannot see, so the scope
concept left this surface entirely rather than merely changing its default.

Two consequences, both accepted knowingly.

A catalogue preset written into a project file (by an older version, or by hand)
is still unioned in by Claude Code while this module reports it off, and cannot
be removed from here. The awkward case is a preset present in *both*: the row
reads on, disabling clears only the global copy, and the row then reads off
while the project file keeps the rule in force.

More importantly, a grant can no longer be confined to one repository. For the
``read-only`` tier that costs nothing. For ``writes-workspace`` it is a real
widening — enabling ``uv run pytest`` lets every repo you subsequently open run
its own ``conftest.py`` unprompted, where the previous per-repo default did not.
The UI says so at the point of opting in; restoring the capability properly
means an explicit ``--project <path>`` argument, a named target rather than an
inherited one.

**The prefix hazard.** A ``Bash(<prefix>:*)`` rule permits any continuation
after the prefix, so it cannot express "this subcommand but not that flag".
Two consequences drive what is in the catalogue:

* ``Bash(mc-tool-board next:*)`` would also permit ``next --claim``, which
  claims a card; ``Bash(mc-tool-memory entities:*)`` would permit
  ``entities merge``, which rewrites the graph. Both are excluded.
* ``Bash(git branch:*)`` would also permit ``git branch -D``. A flag is a
  continuation like any other, so narrowing has to happen in the prefix itself.

**The boundary is native, and the trailing space is belt-and-braces.** Every
pattern here is written as a pair — ``Bash(cmd)`` for the bare invocation and
``Bash(cmd :*)`` for anything with arguments. The original rationale was that
``:*`` was a *raw* string prefix, so ``Bash(git diff:*)`` would also reach
``git difftool --extcmd=<cmd>`` and the trailing space was the only thing
restoring a word boundary.

Measurement against Claude Code 2.1.220 falsified that premise: ``:*`` respects
a token boundary on its own. ``Bash(git diff:*)`` refuses ``git difftool``, and
``Bash(git branch:*)`` refuses ``git branchfoo`` while still permitting
``git branch -D``. The ``difftool`` escape does not exist on this version.

The pair form is kept anyway. It costs nothing, it states the intended boundary
explicitly rather than relying on an undocumented matcher detail, and it holds
if a future version changes the rule. What it is *not* is the thing standing
between the catalogue and arbitrary code execution.
:data:`MUTATING_INVOCATIONS` carries a concrete example of each shape so the
guard test fails if the boundary is ever dropped.

:func:`matches_command` models the measured semantics, staying pessimistic only
where measurement ran out — the catalogue is guarded against the worst case a
real matcher might plausibly do, not the friendliest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
    # Target file
    "settings_path",
    # Reading
    "AllowSnapshot",
    "PermissionsFileError",
    "PresetState",
    "allow_rules",
    "matches_command",
    "read_allow",
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
        patterns=(
            "Bash(git status)",
            "Bash(git status :*)",
        ),
    ),
    Preset(
        id="git-diff",
        group="Git (read-only)",
        label="git diff",
        rationale=(
            "Prints changes; no flag writes to the repository. Split in two so the "
            "boundary between 'git diff' and its siblings is stated in the rule "
            "rather than left to the matcher."
        ),
        # The trailing space states the word boundary explicitly. Measured against
        # 2.1.220 `:*` already stops at a token boundary, so 'git difftool' is
        # refused either way — the space makes that independent of an undocumented
        # matcher detail. The first pattern covers bare `git diff`, which the
        # space-terminated prefix would otherwise miss.
        patterns=("Bash(git diff)", "Bash(git diff :*)"),
    ),
    Preset(
        id="git-log",
        group="Git (read-only)",
        label="git log",
        rationale="Reads history only.",
        patterns=(
            "Bash(git log)",
            "Bash(git log :*)",
        ),
    ),
    Preset(
        id="git-show",
        group="Git (read-only)",
        label="git show",
        rationale="Reads objects only. Bounded to `git show`, not show-ref/show-branch.",
        patterns=(
            "Bash(git show)",
            "Bash(git show :*)",
        ),
    ),
    Preset(
        id="git-blame",
        group="Git (read-only)",
        label="git blame",
        rationale="Reads line provenance only.",
        patterns=(
            "Bash(git blame)",
            "Bash(git blame :*)",
        ),
    ),
    # -- File inspection ---------------------------------------------------
    Preset(
        id="list-dir",
        group="File inspection",
        label="ls",
        rationale="Lists directories. Bounded to `ls` itself, not lsof/lsblk.",
        patterns=(
            "Bash(ls)",
            "Bash(ls :*)",
        ),
    ),
    Preset(
        id="count-lines",
        group="File inspection",
        label="wc",
        rationale="Counts lines, words and bytes.",
        patterns=(
            "Bash(wc)",
            "Bash(wc :*)",
        ),
    ),
    Preset(
        id="head-tail",
        group="File inspection",
        label="head / tail",
        rationale="Prints the ends of a file. Note that tail -f blocks.",
        patterns=("Bash(head)", "Bash(head :*)", "Bash(tail)", "Bash(tail :*)"),
    ),
    Preset(
        id="file-stat",
        group="File inspection",
        label="file / stat",
        rationale="Reports file type and metadata.",
        patterns=("Bash(file)", "Bash(file :*)", "Bash(stat)", "Bash(stat :*)"),
    ),
    Preset(
        id="disk-usage",
        group="File inspection",
        label="du / tree",
        rationale="Summarises sizes and directory shape.",
        patterns=("Bash(du)", "Bash(du :*)", "Bash(tree)", "Bash(tree :*)"),
    ),
    # -- Project tooling ---------------------------------------------------
    Preset(
        id="uv-tree",
        group="Project tooling",
        label="uv tree",
        rationale="Prints the resolved dependency tree; does not touch the lock.",
        patterns=(
            "Bash(uv tree)",
            "Bash(uv tree :*)",
        ),
    ),
    Preset(
        id="pyright",
        group="Project tooling",
        label="uv run pyright",
        rationale="Type-checks without modifying sources.",
        patterns=(
            "Bash(uv run pyright)",
            "Bash(uv run pyright :*)",
        ),
    ),
    Preset(
        id="ruff-check",
        group="Project tooling",
        label="uv run ruff check",
        rationale=(
            "Lints the tree. Prefix matching also permits --fix, which rewrites "
            "tracked sources — reversible with git, but not read-only."
        ),
        patterns=(
            "Bash(uv run ruff check)",
            "Bash(uv run ruff check :*)",
        ),
        tier="writes-workspace",
    ),
    Preset(
        id="ruff-format",
        group="Project tooling",
        label="uv run ruff format",
        rationale="Reformats tracked sources in place; reversible with git.",
        patterns=(
            "Bash(uv run ruff format)",
            "Bash(uv run ruff format :*)",
        ),
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
        patterns=(
            "Bash(uv run pytest)",
            "Bash(uv run pytest :*)",
        ),
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
            "Bash(mc-tool-board list)",
            "Bash(mc-tool-board list :*)",
            "Bash(mc-tool-board show)",
            "Bash(mc-tool-board show :*)",
            "Bash(mc-tool-board export)",
            "Bash(mc-tool-board export :*)",
            "Bash(mc-tool-board summary)",
            "Bash(mc-tool-board summary :*)",
        ),
    ),
    Preset(
        id="memory-read",
        group="mait-code tools",
        label="mc-tool-memory (read-only)",
        rationale=(
            "search/list/stats/relationships only. 'entities' is excluded "
            "because 'entities merge' mutates, and 'review' is left out so the "
            "read-only preset stays clear of the review write path."
        ),
        patterns=(
            "Bash(mc-tool-memory search)",
            "Bash(mc-tool-memory search :*)",
            "Bash(mc-tool-memory list)",
            "Bash(mc-tool-memory list :*)",
            "Bash(mc-tool-memory stats)",
            "Bash(mc-tool-memory stats :*)",
            "Bash(mc-tool-memory relationships)",
            "Bash(mc-tool-memory relationships :*)",
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
        patterns=(
            "Bash(mc-tool-reminders list)",
            "Bash(mc-tool-reminders list :*)",
        ),
    ),
    Preset(
        id="inbox-read",
        group="mait-code tools",
        label="mc-tool-inbox (read-only)",
        rationale="list/count only; 'drain' pulls from the Bridge and mutates.",
        patterns=(
            "Bash(mc-tool-inbox list)",
            "Bash(mc-tool-inbox list :*)",
            "Bash(mc-tool-inbox count)",
            "Bash(mc-tool-inbox count :*)",
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
    # `git difftool -x/--extcmd` runs an arbitrary command once per changed file,
    # and shares a prefix with the wholly-innocent `git diff`. Listed because a
    # rule guarding "git diff" is the obvious thing to write and the wrong one.
    "git difftool --extcmd=rm",
    "git difftool -x rm",
    # Real binaries that share a prefix with a genuinely read-only command. Which
    # of these exist is machine-dependent — that is the point. A prefix rule with
    # no word boundary is hostage to whatever happens to be installed, so the
    # catalogue is guarded against the ones we know and shaped so the rest cannot
    # apply either. `static-sh` is a shell; `tailscale` reconfigures a VPN;
    # `file-roller` extracts archives to disk.
    "static-sh -c rm -rf /tmp/x",
    "tailscale up --advertise-exit-node",
    "tailscale logout",
    "file-roller --extract-to=/tmp x.zip",
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
# Target file
# --------------------------------------------------------------------------


def settings_path() -> Path:
    """Return the one settings file this module reads and writes.

    Always ``~/.claude/settings.json`` — resolved from ``$HOME``, never from
    the process's working directory, so every entry point behaves identically
    whichever directory it was launched from.
    """
    return claude_dir() / "settings.json"


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

    Models the three grant forms as measured against Claude Code 2.1.220 (the
    method and results are recorded under "Granting ``allowed-tools``" in
    ``docs/development.md``):

    - ``Bash(cmd)`` — exact match only. ``Bash(git push)`` does not permit
      ``git push --dry-run``.
    - ``Bash(cmd:*)`` — prefix match **at a token boundary**. It permits any
      continuation after the boundary, so ``Bash(git branch:*)`` does span
      ``git branch -D``; it does not permit a longer token, so ``git branchfoo``
      is refused.
    - ``Bash(cmd *)`` — the older space form. Indistinguishable from ``cmd:*``
      on every probe pair tested, and modelled identically here. It is a real
      wildcard, not the literal text ``cmd *``: ``Bash(git *)`` permits
      ``git push``.

    The boundary test itself is deliberately pessimistic where measurement ran
    out. A continuation starting with an alphanumeric or ``_`` is treated as
    the same token (refused, as observed); anything else is treated as a new
    token (permitted), which over-matches rather than under-matches so the
    catalogue guard errs toward rejecting a pattern.

    Shell operators are not modelled. The real matcher decomposes a compound
    command and requires every part to be permitted — ``Bash(git push:*)``
    refuses ``git push --dry-run || git commit -m x`` — so treating the whole
    string as one command over-matches here, which is the safe direction for a
    guard.

    Non-``Bash(...)`` patterns never match.
    """
    if not (pattern.startswith("Bash(") and pattern.endswith(")")):
        return False
    body = pattern[len("Bash(") : -1]
    for suffix in (":*", " *"):
        if body.endswith(suffix):
            prefix = body[: -len(suffix)]
            if not command.startswith(prefix):
                return False
            rest = command[len(prefix) :]
            return not rest or not (rest[0].isalnum() or rest[0] == "_")
    return command == body


@dataclass(frozen=True)
class PresetState:
    """Where a preset currently stands in the settings file.

    Attributes:
        preset: The catalogue entry.
        enabled: ``True`` when *every* pattern of the preset is present.
        partial: ``True`` when some but not all of them are — usually a
            hand-edited file, and worth showing rather than rounding to "off".
    """

    preset: Preset
    enabled: bool = False
    partial: bool = False


@dataclass(frozen=True)
class AllowSnapshot:
    """The allow rules read from the settings file, or why they could not be.

    Attributes:
        rules: The ``permissions.allow`` entries found, empty when the file is
            missing or unreadable.
        error: The message for a file that could not be parsed, else ``None``.
            Carried rather than raised so one broken file reports itself in
            place instead of blanking the whole settings tree.
    """

    rules: tuple[str, ...] = ()
    error: str | None = None


def read_allow() -> AllowSnapshot:
    """Read the allow rules from the settings file, isolating a parse error."""
    try:
        return AllowSnapshot(rules=allow_rules(settings_path()))
    except PermissionsFileError as exc:
        return AllowSnapshot(error=str(exc))


def resolve_states() -> tuple[PresetState, ...]:
    """Resolve every catalogue preset against the on-disk settings file."""
    rules = read_allow().rules
    states: list[PresetState] = []
    for preset in ALLOW_PRESETS:
        present = sum(1 for pattern in preset.patterns if pattern in rules)
        states.append(
            PresetState(
                preset=preset,
                enabled=present == len(preset.patterns),
                partial=0 < present < len(preset.patterns),
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
        path: The settings file written.
        added: Patterns appended to ``permissions.allow``.
        removed: Patterns deleted from it.
        backup: The backup taken before the first write to *path*, if any.
    """

    preset_id: str
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


def enable_preset(preset_id: str) -> WriteOutcome:
    """Add a preset's patterns to the settings file's ``permissions.allow``.

    Idempotent: patterns already present are left alone rather than duplicated,
    and a preset that is already fully enabled writes nothing at all. Existing
    rules keep their order — new patterns are appended.

    Args:
        preset_id: A catalogue preset id.

    Returns:
        A :class:`WriteOutcome`; ``changed`` is ``False`` for a no-op.

    Raises:
        KeyError: If *preset_id* is unknown.
        PermissionsFileError: If the settings file exists but cannot be parsed.
    """
    preset = preset_by_id(preset_id)
    path = settings_path()
    document = _read_document(path)
    existing = allow_rules(path)
    missing = tuple(p for p in preset.patterns if p not in existing)
    if not missing:
        return WriteOutcome(preset_id=preset_id, path=path)
    backup = _backup(path)
    _write_allow(path, document, [*existing, *missing])
    return WriteOutcome(
        preset_id=preset_id,
        path=path,
        added=missing,
        backup=backup,
    )


def disable_preset(preset_id: str) -> WriteOutcome:
    """Remove a preset's patterns from the settings file.

    Only this preset's own patterns are touched; hand-written rules that merely
    look similar are left in place, as is their order. Removing a preset that
    is only partially present clears whichever of its patterns are there.

    Returns:
        A :class:`WriteOutcome`; ``changed`` is ``False`` when the preset was
        not present at all.

    Raises:
        KeyError: If *preset_id* is unknown.
        PermissionsFileError: If the settings file exists but cannot be parsed.
    """
    preset = preset_by_id(preset_id)
    path = settings_path()
    document = _read_document(path)
    existing = allow_rules(path)
    doomed = tuple(p for p in preset.patterns if p in existing)
    if not doomed:
        return WriteOutcome(preset_id=preset_id, path=path)
    backup = _backup(path)
    _write_allow(path, document, [r for r in existing if r not in doomed])
    return WriteOutcome(
        preset_id=preset_id,
        path=path,
        removed=doomed,
        backup=backup,
    )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def presets_json() -> list[dict[str, Any]]:
    """Return every preset's state as plain dicts, for ``--json`` output."""
    return [
        {
            "id": state.preset.id,
            "group": state.preset.group,
            "label": state.preset.label,
            "tier": state.preset.tier,
            "patterns": list(state.preset.patterns),
            "enabled": state.enabled,
            "partial": state.partial,
        }
        for state in resolve_states()
    ]


def render_presets() -> None:
    """Print the enabled tool-approval presets to the shared console.

    The read-only counterpart of the settings TUI's Tool approvals group: it
    reports what is switched on, so the non-TTY view is not silent about rules
    that are actually in force. Rich is imported lazily to match
    :func:`mait_code.config.render`.
    """
    from rich.table import Table
    from rich.text import Text

    from mait_code.console import console

    snapshot = read_allow()
    states = resolve_states()
    path = settings_path()

    console.rule(style="muted")
    header = Text("tool approvals", style="accent")
    header.append("   (read-only)", style="muted")
    console.print(header)

    line = Text("file: ", style="muted")
    line.append(str(path).replace(str(Path.home()), "~"))
    if snapshot.error is not None:
        line.append("  (unreadable)", style="warn")
    elif not path.exists():
        line.append("  (not created yet)", style="muted")
    console.print(line)

    enabled = [s for s in states if s.enabled or s.partial]
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
        table.add_column("STATE", no_wrap=True)
        for state in enabled:
            tier_style = "" if state.preset.tier == "read-only" else "warn"
            table.add_row(
                state.preset.label,
                Text(state.preset.tier, style=tier_style),
                "enabled" if state.enabled else "partial",
            )
        console.print(table)

    if snapshot.error is not None:
        console.print(Text(f"⚠ {snapshot.error}", style="warn"))
