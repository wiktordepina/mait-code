"""Tests for the tool-approval preset catalogue and its settings-file writes.

Two halves. The first is a set of *guard* tests over the catalogue itself:
these don't exercise code so much as pin the curation, so a preset that quietly
permits a mutating command fails the suite rather than shipping. The second
drives the read/merge/scope machinery against real files under a fake ``$HOME``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mait_code.cli import _permissions as perms


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
        # The word-boundary hazard the catalogue is curated around: a raw
        # prefix spans into a longer, different subcommand.
        ("Bash(mc-tool-memory review:*)", "mc-tool-memory reviewed 3", True),
        ("Bash(mc-tool-memory search:*)", "mc-tool-memory store x", False),
        # No wildcard means exact match only.
        ("Bash(wc)", "wc", True),
        ("Bash(wc)", "wc -l file", False),
        # Non-Bash rules are none of this module's business.
        ("Read(~/**)", "git status", False),
    ],
)
def test_matches_command(pattern: str, command: str, expected: bool) -> None:
    assert perms.matches_command(pattern, command) is expected


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------


def test_scope_paths_in_a_repo(fake_home: Path, repo: Path) -> None:
    assert perms.scope_path("global") == fake_home / ".claude" / "settings.json"
    assert (
        perms.scope_path("project-shared", root=repo)
        == repo / ".claude" / "settings.json"
    )
    assert (
        perms.scope_path("project-local", root=repo)
        == repo / ".claude" / "settings.local.json"
    )


def test_project_scopes_unavailable_outside_a_repo(fake_home: Path) -> None:
    assert perms.scope_path("project-shared") is None
    assert perms.scope_path("project-local") is None
    assert [s.id for s in perms.available_scopes()] == ["global"]


def test_available_scopes_in_a_repo(fake_home: Path, repo: Path) -> None:
    assert [s.id for s in perms.available_scopes(root=repo)] == [
        "global",
        "project-shared",
        "project-local",
    ]


def test_default_scope_is_the_gitignored_one() -> None:
    """Personal approvals must not default into a committed file."""
    assert perms.DEFAULT_SCOPE == "project-local"
    assert perms.scope_by_id(perms.DEFAULT_SCOPE).project is True


def test_repo_root_walks_up(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    assert perms.repo_root(nested) == tmp_path


def test_repo_root_returns_none_outside_a_repo(tmp_path: Path) -> None:
    # tmp_path is not under a git tree, and neither is any parent of it.
    assert perms.repo_root(tmp_path) is None


def test_repo_root_handles_a_worktree_git_file(tmp_path: Path) -> None:
    """Worktrees and submodules carry a ``.git`` *file*, not a directory."""
    (tmp_path / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    assert perms.repo_root(tmp_path) == tmp_path


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


def test_resolve_states_reports_origin_scope(fake_home: Path, repo: Path) -> None:
    _write(
        repo / ".claude" / "settings.local.json",
        {"permissions": {"allow": list(perms.preset_by_id("git-status").patterns)}},
    )
    states = {s.preset.id: s for s in perms.resolve_states(root=repo)}
    assert states["git-status"].enabled_scopes == ("project-local",)
    assert states["git-status"].origin == "project-local"
    assert states["git-diff"].enabled is False


def test_resolve_states_flags_a_partial_preset(fake_home: Path, repo: Path) -> None:
    """A hand-edited file holding half a preset reads as partial, not off."""
    _write(
        repo / ".claude" / "settings.json",
        {"permissions": {"allow": ["Bash(head:*)"]}},
    )
    states = {s.preset.id: s for s in perms.resolve_states(root=repo)}
    assert states["head-tail"].enabled is False
    assert states["head-tail"].partial_scopes == ("project-shared",)


def test_read_scopes_isolates_a_broken_file(fake_home: Path, repo: Path) -> None:
    """One malformed scope must not blank the whole view."""
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text("{oops", encoding="utf-8")
    _write(
        repo / ".claude" / "settings.local.json",
        {"permissions": {"allow": ["Bash(ls:*)"]}},
    )
    snapshot = perms.read_scopes(root=repo)
    assert "project-shared" in snapshot.errors
    assert snapshot.rules["project-local"] == ("Bash(ls:*)",)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_enable_creates_the_file(fake_home: Path, repo: Path) -> None:
    outcome = perms.enable_preset("git-status", "project-local", root=repo)
    assert outcome.changed
    assert outcome.backup is None  # nothing existed to back up
    document = json.loads(outcome.path.read_text(encoding="utf-8"))
    assert document["permissions"]["allow"] == ["Bash(git status:*)"]


def test_enable_preserves_unrelated_keys_and_rule_order(
    fake_home: Path, repo: Path
) -> None:
    path = repo / ".claude" / "settings.local.json"
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
    perms.enable_preset("git-status", "project-local", root=repo)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["model"] == "opus"
    assert document["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "mc-hook-x"
    assert document["permissions"]["deny"] == ["Bash(curl:*)"]
    # The hand-written rule keeps its position; ours is appended after it.
    assert document["permissions"]["allow"] == ["Bash(mine:*)", "Bash(git status:*)"]


def test_enable_is_idempotent(fake_home: Path, repo: Path) -> None:
    first = perms.enable_preset("head-tail", "project-local", root=repo)
    second = perms.enable_preset("head-tail", "project-local", root=repo)
    assert first.changed is True
    assert second.changed is False
    assert second.added == ()
    document = json.loads(second.path.read_text(encoding="utf-8"))
    assert document["permissions"]["allow"] == ["Bash(head:*)", "Bash(tail:*)"]


def test_enable_completes_a_partial_preset(fake_home: Path, repo: Path) -> None:
    """Only the missing half is written; the present half isn't duplicated."""
    path = repo / ".claude" / "settings.local.json"
    _write(path, {"permissions": {"allow": ["Bash(head:*)"]}})
    outcome = perms.enable_preset("head-tail", "project-local", root=repo)
    assert outcome.added == ("Bash(tail:*)",)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["permissions"]["allow"] == ["Bash(head:*)", "Bash(tail:*)"]


def test_enable_in_a_second_scope_is_visible_as_such(
    fake_home: Path, repo: Path
) -> None:
    perms.enable_preset("git-log", "global", root=repo)
    perms.enable_preset("git-log", "project-local", root=repo)
    states = {s.preset.id: s for s in perms.resolve_states(root=repo)}
    assert states["git-log"].enabled_scopes == ("global", "project-local")


def test_enable_backs_up_once_per_file(fake_home: Path, repo: Path) -> None:
    path = repo / ".claude" / "settings.local.json"
    _write(path, {"permissions": {"allow": ["Bash(mine:*)"]}})
    first = perms.enable_preset("git-status", "project-local", root=repo)
    second = perms.enable_preset("git-log", "project-local", root=repo)
    assert first.backup is not None
    assert first.backup.exists()
    assert json.loads(first.backup.read_text(encoding="utf-8")) == {
        "permissions": {"allow": ["Bash(mine:*)"]}
    }
    # Second write to the same file doesn't spawn another backup.
    assert second.backup is None
    assert len(list((repo / ".claude").glob("*.bak-*"))) == 1


def test_enable_refuses_a_malformed_target(fake_home: Path, repo: Path) -> None:
    path = repo / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    original = '{"permissions": {"allow": [,]}}'
    path.write_text(original, encoding="utf-8")
    with pytest.raises(perms.PermissionsFileError):
        perms.enable_preset("git-status", "project-local", root=repo)
    assert path.read_text(encoding="utf-8") == original


def test_enable_outside_a_repo_rejects_project_scopes(fake_home: Path) -> None:
    with pytest.raises(perms.PermissionsFileError, match="git repository"):
        perms.enable_preset("git-status", "project-local", root=None)


def test_enable_rejects_unknown_ids(fake_home: Path, repo: Path) -> None:
    with pytest.raises(KeyError):
        perms.enable_preset("no-such-preset", "project-local", root=repo)
    with pytest.raises(KeyError):
        perms.enable_preset("git-status", "no-such-scope", root=repo)


def test_disable_sweeps_every_scope(fake_home: Path, repo: Path) -> None:
    """Leaving a copy behind would keep the rule in force while the UI said off."""
    perms.enable_preset("git-log", "global", root=repo)
    perms.enable_preset("git-log", "project-local", root=repo)
    outcomes = perms.disable_preset("git-log", root=repo)
    assert {o.scope_id for o in outcomes} == {"global", "project-local"}
    states = {s.preset.id: s for s in perms.resolve_states(root=repo)}
    assert states["git-log"].enabled_scopes == ()


def test_disable_targets_one_scope_when_asked(fake_home: Path, repo: Path) -> None:
    perms.enable_preset("git-log", "global", root=repo)
    perms.enable_preset("git-log", "project-local", root=repo)
    perms.disable_preset("git-log", scope_id="global", root=repo)
    states = {s.preset.id: s for s in perms.resolve_states(root=repo)}
    assert states["git-log"].enabled_scopes == ("project-local",)


def test_disable_leaves_neighbouring_rules_alone(fake_home: Path, repo: Path) -> None:
    path = repo / ".claude" / "settings.local.json"
    _write(path, {"permissions": {"allow": ["Bash(mine:*)", "Bash(git status)"]}})
    perms.enable_preset("git-status", "project-local", root=repo)
    perms.disable_preset("git-status", root=repo)
    document = json.loads(path.read_text(encoding="utf-8"))
    # The near-identical hand-written rule (no ``:*``) is untouched.
    assert document["permissions"]["allow"] == ["Bash(mine:*)", "Bash(git status)"]


def test_disable_drops_an_emptied_permissions_block(
    fake_home: Path, repo: Path
) -> None:
    outcome = perms.enable_preset("git-status", "project-local", root=repo)
    perms.disable_preset("git-status", root=repo)
    document = json.loads(outcome.path.read_text(encoding="utf-8"))
    assert "permissions" not in document


def test_disable_when_absent_writes_nothing(fake_home: Path, repo: Path) -> None:
    assert perms.disable_preset("git-status", root=repo) == ()
    assert not (repo / ".claude" / "settings.local.json").exists()


def test_disable_sweep_skips_a_broken_scope(fake_home: Path, repo: Path) -> None:
    """A broken file elsewhere shouldn't block disabling where it is possible."""
    perms.enable_preset("git-log", "project-local", root=repo)
    (repo / ".claude" / "settings.json").write_text("{oops", encoding="utf-8")
    outcomes = perms.disable_preset("git-log", root=repo)
    assert [o.scope_id for o in outcomes] == ["project-local"]


def test_disable_surfaces_a_broken_explicit_target(fake_home: Path, repo: Path) -> None:
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(perms.PermissionsFileError):
        perms.disable_preset("git-log", scope_id="project-shared", root=repo)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_presets_json_shape(fake_home: Path, repo: Path) -> None:
    perms.enable_preset("git-status", "project-local", root=repo)
    rows = {row["id"]: row for row in perms.presets_json(root=repo)}
    assert len(rows) == len(perms.ALLOW_PRESETS)
    assert rows["git-status"]["enabled"] is True
    assert rows["git-status"]["enabled_scopes"] == ["project-local"]
    assert rows["git-status"]["tier"] == "read-only"
    assert rows["ruff-check"]["tier"] == "writes-workspace"
    assert rows["git-diff"]["enabled"] is False


def test_render_presets_names_the_scope(
    fake_home: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    perms.enable_preset("git-status", "project-local", root=repo)
    perms.render_presets(root=repo)
    out = capsys.readouterr().out
    assert "git status" in out
    assert "Project (local)" in out


def test_render_presets_with_nothing_enabled(
    fake_home: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    perms.render_presets(root=repo)
    assert "no presets enabled" in capsys.readouterr().out


def test_render_presets_reports_a_broken_file(
    fake_home: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text("{oops", encoding="utf-8")
    perms.render_presets(root=repo)
    assert "unreadable" in capsys.readouterr().out
