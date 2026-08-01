"""Tests for the tool-approval preset catalogue and its settings-file writes.

Two halves. The first is a set of *guard* tests over the catalogue itself:
these don't exercise code so much as pin the curation, so a preset that quietly
permits a mutating command fails the suite rather than shipping. The second
drives the read/merge machinery against real files under a fake ``$HOME``,
including from inside a git repo — the target must not move with the cwd.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mait_code.cli import _permissions as perms

_GIT_STATUS = perms.preset_by_id("git-status").patterns
_HEAD_TAIL = perms.preset_by_id("head-tail").patterns


@pytest.fixture(autouse=True)
def _reset_backup_state() -> None:
    """Clear the once-per-process backup ledger between tests."""
    perms._BACKED_UP.clear()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A directory that looks like a git working tree."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Catalogue guards
# ---------------------------------------------------------------------------


def test_no_preset_permits_a_mutating_command() -> None:
    """The core safety property: nothing in the catalogue permits a mutation.

    Checked against :data:`MUTATING_INVOCATIONS` — concrete command lines for
    the same tools the catalogue covers — using the *permissive* raw-prefix
    matcher, so a preset has to be safe even under the worst reading of Claude
    Code's matching rules.
    """
    offenders = [
        (preset.id, pattern, command)
        for preset in perms.ALLOW_PRESETS
        for pattern in preset.patterns
        for command in perms.MUTATING_INVOCATIONS
        if perms.matches_command(pattern, command)
    ]
    assert offenders == []


def test_read_only_presets_contain_no_mutating_verb() -> None:
    """A blunt second net: no read-only pattern names a mutating subcommand."""
    offenders = [
        (preset.id, pattern, token)
        for preset in perms.ALLOW_PRESETS
        if preset.tier == "read-only"
        for pattern in preset.patterns
        for token in pattern[len("Bash(") : -1].removesuffix(":*").split()
        if token in perms.MUTATING_VERBS
    ]
    assert offenders == []


def test_patterns_are_not_shared_between_presets() -> None:
    """Disable removes a preset's own patterns; overlap would delete a neighbour's."""
    seen: dict[str, str] = {}
    for preset in perms.ALLOW_PRESETS:
        for pattern in preset.patterns:
            assert pattern not in seen, (
                f"{pattern} claimed by both {seen.get(pattern)} and {preset.id}"
            )
            seen[pattern] = preset.id


def test_catalogue_is_well_formed() -> None:
    ids = [preset.id for preset in perms.ALLOW_PRESETS]
    assert len(ids) == len(set(ids)), "preset ids must be unique"
    for preset in perms.ALLOW_PRESETS:
        assert preset.tier in perms.TIERS
        assert preset.patterns, f"{preset.id} has no patterns"
        assert preset.rationale.endswith("."), f"{preset.id} rationale reads oddly"
        for pattern in preset.patterns:
            assert pattern.startswith("Bash(") and pattern.endswith(")")


def test_preset_groups_preserve_catalogue_order() -> None:
    grouped = [p.id for _, presets in perms.preset_groups() for p in presets]
    assert grouped == [p.id for p in perms.ALLOW_PRESETS]


@pytest.mark.parametrize(
    ("pattern", "command", "expected"),
    [
        ("Bash(git status:*)", "git status", True),
        ("Bash(git status:*)", "git status --short", True),
        ("Bash(git status:*)", "git stash", False),
        ("Bash(mc-tool-memory search:*)", "mc-tool-memory store x", False),
        # No wildcard means exact match only. Measured: Bash(git push) refuses
        # git push --dry-run.
        ("Bash(wc)", "wc", True),
        ("Bash(wc)", "wc -l file", False),
        # Non-Bash rules are none of this module's business.
        ("Read(~/**)", "git status", False),
        # --- measured against Claude Code 2.1.220 -------------------------
        # `:*` stops at a token boundary; it does not span into a longer
        # subcommand. This pair replaces an earlier raw-prefix assumption
        # that claimed the opposite.
        ("Bash(mc-tool-memory review:*)", "mc-tool-memory reviewed 3", False),
        ("Bash(git diff:*)", "git difftool --extcmd=sh", False),
        ("Bash(git branch:*)", "git branchfoo", False),
        # ...but any continuation *after* the boundary is permitted, flags
        # included — which is why narrowing must happen in the prefix.
        ("Bash(git branch:*)", "git branch -D main", True),
        # The space form is a real wildcard, not the literal text "git *".
        ("Bash(git *)", "git push origin main", True),
        ("Bash(git *)", "git status", True),
        ("Bash(git *)", "gitfoo", False),
        ("Bash(mc-tool-board *)", "mc-tool-board remove 1", True),
        # Space and colon forms were indistinguishable on every probe pair,
        # including the bare command with no arguments.
        ("Bash(git push *)", "git push", True),
        ("Bash(git push:*)", "git push", True),
        ("Bash(git push *)", "git pushfoo", False),
        ("Bash(git push:*)", "git pushfoo", False),
    ],
)
def test_matches_command(pattern: str, command: str, expected: bool) -> None:
    assert perms.matches_command(pattern, command) is expected


def test_space_and_colon_forms_agree() -> None:
    """Measured equivalence: `cmd *` and `cmd:*` behaved identically throughout.

    Pinned as a property so a future change to one form cannot silently
    diverge from the other.
    """
    commands = [
        "git push",
        "git push --dry-run",
        "git pushfoo",
        "git status",
        "gitfoo",
    ]
    for prefix in ("git", "git push"):
        for command in commands:
            space = perms.matches_command(f"Bash({prefix} *)", command)
            colon = perms.matches_command(f"Bash({prefix}:*)", command)
            assert space == colon, f"{prefix!r} disagreed on {command!r}"


# ---------------------------------------------------------------------------
# Target file — the launch directory must not be an input
# ---------------------------------------------------------------------------


def test_settings_path_is_the_global_file(fake_home: Path) -> None:
    assert perms.settings_path() == fake_home / ".claude" / "settings.json"


def test_target_file_ignores_the_working_directory(
    fake_home: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression guard: cwd must not reach the resolved target.

    A repo with its own ``.claude`` settings is the exact shape that used to
    capture the write; the file resolves to ``$HOME`` from inside it, from a
    nested subdirectory, and from a directory in no repo at all.
    """
    _write(
        repo / ".claude" / "settings.local.json",
        {"permissions": {"allow": list(_GIT_STATUS)}},
    )
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)
    elsewhere = fake_home / "not-a-repo"
    elsewhere.mkdir()

    expected = fake_home / ".claude" / "settings.json"
    for where in (repo, nested, elsewhere):
        monkeypatch.chdir(where)
        assert perms.settings_path() == expected


def test_state_ignores_a_preset_sitting_in_a_project_file(
    fake_home: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The accepted gap, pinned.

    A preset in a repo settings file is still unioned in by Claude Code, but
    this module reports it off and cannot remove it. Asserted so the trade-off
    is a decision on the record rather than a surprise.
    """
    project_file = repo / ".claude" / "settings.local.json"
    _write(
        project_file,
        {"permissions": {"allow": list(perms.preset_by_id("git-status").patterns)}},
    )
    monkeypatch.chdir(repo)
    states = {s.preset.id: s for s in perms.resolve_states()}
    assert states["git-status"].enabled is False
    assert perms.disable_preset("git-status").changed is False
    # Not merely "reported no change" — the project file is genuinely untouched,
    # so the rule really is still in force rather than quietly swept.
    assert json.loads(project_file.read_text(encoding="utf-8")) == {
        "permissions": {"allow": list(perms.preset_by_id("git-status").patterns)}
    }


def test_resolved_state_is_identical_from_any_directory(
    fake_home: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    perms.enable_preset("git-log")
    _write(
        repo / ".claude" / "settings.json",
        {"permissions": {"allow": [_HEAD_TAIL[0]]}},
    )
    nested = repo / "src"
    nested.mkdir(parents=True)

    renders = []
    for where in (repo, nested, fake_home):
        monkeypatch.chdir(where)
        renders.append(perms.presets_json())
    assert renders[0] == renders[1] == renders[2]
    # And the global rule is what is reflected, not the repo's half-preset.
    rows = {row["id"]: row for row in renders[0]}
    assert rows["git-log"]["enabled"] is True
    assert rows["head-tail"]["partial"] is False


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_allow_rules_of_a_missing_file(tmp_path: Path) -> None:
    assert perms.allow_rules(tmp_path / "nope.json") == ()


def test_allow_rules_tolerates_odd_shapes(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    _write(path, {"permissions": {"allow": ["Bash(ls:*)", 7, None]}})
    assert perms.allow_rules(path) == ("Bash(ls:*)",)

    _write(path, {"permissions": "nonsense"})
    assert perms.allow_rules(path) == ()

    _write(path, {"permissions": {"allow": "nonsense"}})
    assert perms.allow_rules(path) == ()


def test_malformed_file_raises_rather_than_reading_empty(tmp_path: Path) -> None:
    """The clobber guard: a broken file must not look like an empty one."""
    path = tmp_path / "settings.json"
    path.write_text('{"permissions": {"allow": ["Bash(ls:*)",]}}', encoding="utf-8")
    with pytest.raises(perms.PermissionsFileError, match="not valid JSON"):
        perms.allow_rules(path)


def test_non_object_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(perms.PermissionsFileError, match="JSON object"):
        perms.allow_rules(path)


def test_empty_file_reads_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("   \n", encoding="utf-8")
    assert perms.allow_rules(path) == ()


def test_resolve_states_reports_an_enabled_preset(fake_home: Path) -> None:
    _write(
        perms.settings_path(),
        {"permissions": {"allow": list(perms.preset_by_id("git-status").patterns)}},
    )
    states = {s.preset.id: s for s in perms.resolve_states()}
    assert states["git-status"].enabled is True
    assert states["git-status"].partial is False
    assert states["git-diff"].enabled is False


def test_resolve_states_flags_a_partial_preset(fake_home: Path) -> None:
    """A hand-edited file holding half a preset reads as partial, not off."""
    _write(perms.settings_path(), {"permissions": {"allow": [_HEAD_TAIL[0]]}})
    states = {s.preset.id: s for s in perms.resolve_states()}
    assert states["head-tail"].enabled is False
    assert states["head-tail"].partial is True


def test_read_allow_carries_a_parse_error(fake_home: Path) -> None:
    """A broken file reports itself rather than blanking the view."""
    path = perms.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text("{oops", encoding="utf-8")
    snapshot = perms.read_allow()
    assert snapshot.rules == ()
    assert snapshot.error is not None
    assert "not valid JSON" in snapshot.error
    # And every preset reads off rather than raising out of the render.
    assert all(not s.enabled for s in perms.resolve_states())


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_enable_creates_the_file(fake_home: Path) -> None:
    outcome = perms.enable_preset("git-status")
    assert outcome.changed
    assert outcome.path == perms.settings_path()
    assert outcome.backup is None  # nothing existed to back up
    document = json.loads(outcome.path.read_text(encoding="utf-8"))
    assert document["permissions"]["allow"] == list(_GIT_STATUS)


def test_enable_writes_globally_from_inside_a_repo(
    fake_home: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No code path may write into a repo's settings files."""
    monkeypatch.chdir(repo)
    outcome = perms.enable_preset("git-status")
    assert outcome.path == fake_home / ".claude" / "settings.json"
    assert not (repo / ".claude" / "settings.json").exists()
    assert not (repo / ".claude" / "settings.local.json").exists()


def test_enable_preserves_unrelated_keys_and_rule_order(fake_home: Path) -> None:
    path = perms.settings_path()
    _write(
        path,
        {
            "model": "opus",
            "hooks": {"SessionStart": [{"hooks": [{"command": "mc-hook-x"}]}]},
            "permissions": {
                "allow": ["Bash(mine:*)"],
                "deny": ["Bash(curl:*)"],
            },
        },
    )
    perms.enable_preset("git-status")
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["model"] == "opus"
    assert document["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "mc-hook-x"
    assert document["permissions"]["deny"] == ["Bash(curl:*)"]
    # The hand-written rule keeps its position; ours is appended after it.
    assert document["permissions"]["allow"] == ["Bash(mine:*)", *_GIT_STATUS]


def test_enable_is_idempotent(fake_home: Path) -> None:
    first = perms.enable_preset("head-tail")
    second = perms.enable_preset("head-tail")
    assert first.changed is True
    assert second.changed is False
    assert second.added == ()
    document = json.loads(second.path.read_text(encoding="utf-8"))
    assert document["permissions"]["allow"] == list(_HEAD_TAIL)


def test_enable_completes_a_partial_preset(fake_home: Path) -> None:
    """Only the missing half is written; the present half isn't duplicated."""
    path = perms.settings_path()
    _write(path, {"permissions": {"allow": [_HEAD_TAIL[0]]}})
    outcome = perms.enable_preset("head-tail")
    assert outcome.added == _HEAD_TAIL[1:]
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["permissions"]["allow"] == list(_HEAD_TAIL)


def test_enable_backs_up_once_per_file(fake_home: Path) -> None:
    path = perms.settings_path()
    _write(path, {"permissions": {"allow": ["Bash(mine:*)"]}})
    first = perms.enable_preset("git-status")
    second = perms.enable_preset("git-log")
    assert first.backup is not None
    assert first.backup.exists()
    assert json.loads(first.backup.read_text(encoding="utf-8")) == {
        "permissions": {"allow": ["Bash(mine:*)"]}
    }
    # Second write to the same file doesn't spawn another backup.
    assert second.backup is None
    assert len(list(path.parent.glob("*.bak-*"))) == 1


def test_enable_refuses_a_malformed_target(fake_home: Path) -> None:
    path = perms.settings_path()
    path.parent.mkdir(parents=True)
    original = '{"permissions": {"allow": [,]}}'
    path.write_text(original, encoding="utf-8")
    with pytest.raises(perms.PermissionsFileError):
        perms.enable_preset("git-status")
    assert path.read_text(encoding="utf-8") == original


def test_enable_rejects_an_unknown_id(fake_home: Path) -> None:
    with pytest.raises(KeyError):
        perms.enable_preset("no-such-preset")


def test_disable_removes_the_preset(fake_home: Path) -> None:
    perms.enable_preset("git-log")
    outcome = perms.disable_preset("git-log")
    assert outcome.changed is True
    assert outcome.removed == perms.preset_by_id("git-log").patterns
    states = {s.preset.id: s for s in perms.resolve_states()}
    assert states["git-log"].enabled is False


def test_disable_clears_a_partial_preset(fake_home: Path) -> None:
    _write(perms.settings_path(), {"permissions": {"allow": [_HEAD_TAIL[0]]}})
    outcome = perms.disable_preset("head-tail")
    assert outcome.removed == (_HEAD_TAIL[0],)
    states = {s.preset.id: s for s in perms.resolve_states()}
    assert states["head-tail"].partial is False


def test_disable_leaves_neighbouring_rules_alone(fake_home: Path) -> None:
    path = perms.settings_path()
    hand_written = "Bash(git status --short)"
    assert hand_written not in _GIT_STATUS  # must not be one of ours
    _write(path, {"permissions": {"allow": ["Bash(mine:*)", hand_written]}})
    perms.enable_preset("git-status")
    perms.disable_preset("git-status")
    document = json.loads(path.read_text(encoding="utf-8"))
    # The near-identical hand-written rule is untouched — only this preset's own
    # patterns are removed, never anything that merely resembles them.
    assert document["permissions"]["allow"] == ["Bash(mine:*)", hand_written]


def test_disable_drops_an_emptied_permissions_block(fake_home: Path) -> None:
    outcome = perms.enable_preset("git-status")
    perms.disable_preset("git-status")
    document = json.loads(outcome.path.read_text(encoding="utf-8"))
    assert "permissions" not in document


def test_disable_when_absent_writes_nothing(fake_home: Path) -> None:
    outcome = perms.disable_preset("git-status")
    assert outcome.changed is False
    assert not perms.settings_path().exists()


def test_disable_refuses_a_malformed_target(fake_home: Path) -> None:
    path = perms.settings_path()
    path.parent.mkdir(parents=True)
    original = "{oops"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(perms.PermissionsFileError):
        perms.disable_preset("git-log")
    assert path.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_presets_json_shape(fake_home: Path) -> None:
    # One full preset and half of another, so both booleans are exercised.
    _write(
        perms.settings_path(),
        {"permissions": {"allow": [*_GIT_STATUS, _HEAD_TAIL[0]]}},
    )
    rows = {row["id"]: row for row in perms.presets_json()}
    assert len(rows) == len(perms.ALLOW_PRESETS)
    assert rows["git-status"]["enabled"] is True
    assert rows["git-status"]["partial"] is False
    assert rows["head-tail"]["enabled"] is False
    assert rows["head-tail"]["partial"] is True
    assert rows["git-status"]["tier"] == "read-only"
    assert rows["ruff-check"]["tier"] == "writes-workspace"
    assert rows["git-diff"]["enabled"] is False


def test_render_presets_names_the_file(
    fake_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    perms.enable_preset("git-status")
    perms.render_presets()
    out = capsys.readouterr().out
    assert "git status" in out
    assert "~/.claude/settings.json" in out
    assert "enabled" in out


def test_render_presets_with_nothing_enabled(
    fake_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    perms.render_presets()
    assert "no presets enabled" in capsys.readouterr().out


def test_render_presets_reports_a_broken_file(
    fake_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = perms.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text("{oops", encoding="utf-8")
    perms.render_presets()
    assert "unreadable" in capsys.readouterr().out


def test_every_pattern_is_boundary_terminated() -> None:
    """The structural guard behind the sibling-prefix class of hole.

    A raw prefix has no word boundary, so ``Bash(stat:*)`` reaches ``static-sh``
    — a shell — and ``Bash(tail:*)`` reaches ``tailscale``. Which siblings exist
    is machine-dependent, so the catalogue is shaped to make the question moot:
    every wildcard prefix ends in a space, which no sibling command name can
    cross. :data:`MUTATING_INVOCATIONS` names concrete instances, but this test
    is the one that generalises.
    """
    offenders = [
        (preset.id, pattern)
        for preset in perms.ALLOW_PRESETS
        for pattern in preset.patterns
        if pattern.endswith(":*)") and not pattern[: -len(":*)")].endswith(" ")
    ]
    assert offenders == [], (
        "wildcard patterns must end in a space to enforce a word boundary; "
        "pair them with an exact 'Bash(cmd)' rule for the bare invocation"
    )


def test_bare_and_argument_forms_are_both_covered() -> None:
    """The space-terminated prefix cannot match a bare invocation on its own.

    Each preset therefore ships both forms; without the exact pattern, enabling
    'git diff' would silently stop covering `git diff` with no arguments.
    """
    for preset in perms.ALLOW_PRESETS:
        wildcards = [p for p in preset.patterns if p.endswith(":*)")]
        exacts = {p for p in preset.patterns if not p.endswith(":*)")}
        for wildcard in wildcards:
            bare = wildcard[: -len(" :*)")] + ")"
            assert bare in exacts, f"{preset.id}: {wildcard} has no bare counterpart"
