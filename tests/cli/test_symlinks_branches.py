"""Branch coverage for the symlink helpers.

The install/uninstall end-to-end tests exercise the happy paths
(create, back up, already-linked, remove). These tests pin down the
remaining branches the helpers carry: the *updated* (stale-target)
path, the missing-source no-ops, the early returns in
``remove_claude_md_symlink``, and the dangling-symlink handling in
``_remove_links_into``.

All filesystem effects land under ``tmp_path`` — no real ``~/.claude``
is touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mait_code.cli._symlinks import (
    SymlinkResult,
    _link_to,
    remove_agent_symlinks,
    remove_claude_md_symlink,
    remove_skill_symlinks,
    symlink_agents,
    symlink_skills,
)


# --- _link_to: the stale-target "updated" branch (lines 52-55) ---


def test_link_to_repoints_stale_symlink(tmp_path: Path) -> None:
    """An existing symlink to a stale target is unlinked and repointed."""
    old_target = tmp_path / "old"
    new_target = tmp_path / "new"
    old_target.mkdir()
    new_target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(old_target)

    result = SymlinkResult()
    _link_to(new_target, link, result)

    assert link.readlink() == new_target
    assert result.updated == [link]
    assert result.created == []
    assert result.already_linked == []


# --- symlink_skills / symlink_agents: missing-source no-ops (lines 95, 114) ---


def test_symlink_skills_missing_dir_is_noop(tmp_path: Path) -> None:
    """No ``skills/`` directory in the source means nothing to link."""
    source = tmp_path / "src"
    source.mkdir()  # deliberately no skills/ subdir
    claude_dir = tmp_path / "claude"

    result = symlink_skills(source, claude_dir)

    assert result == SymlinkResult()
    assert not (claude_dir / "skills").exists()


def test_symlink_agents_missing_dir_is_noop(tmp_path: Path) -> None:
    """No ``agents/`` directory in the source means nothing to link."""
    source = tmp_path / "src"
    source.mkdir()  # deliberately no agents/ subdir
    claude_dir = tmp_path / "claude"

    result = symlink_agents(source, claude_dir)

    assert result == SymlinkResult()
    assert not (claude_dir / "agents").exists()


def test_symlink_agents_ignores_gitkeep_and_dirs(tmp_path: Path) -> None:
    """Only real files are linked; ``.gitkeep`` and subdirs are skipped."""
    source = tmp_path / "src"
    agents_src = source / "agents"
    agents_src.mkdir(parents=True)
    (agents_src / ".gitkeep").write_text("")
    (agents_src / "subdir").mkdir()  # not a file — skipped
    (agents_src / "real.md").write_text("agent\n")
    claude_dir = tmp_path / "claude"

    result = symlink_agents(source, claude_dir)

    linked = {p.name for p in result.created}
    assert linked == {"real.md"}
    assert (claude_dir / "agents" / "real.md").is_symlink()


# --- remove_claude_md_symlink: early returns (lines 134, 137-138, 143-144) ---


def test_remove_claude_md_not_a_symlink(tmp_path: Path) -> None:
    """A plain (non-symlink) CLAUDE.md is left alone and reported False."""
    source = tmp_path / "src"
    source.mkdir()
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    (claude_dir / "CLAUDE.md").write_text("user's own\n")

    assert remove_claude_md_symlink(source, claude_dir) is False
    # Untouched.
    assert (claude_dir / "CLAUDE.md").read_text() == "user's own\n"


def test_remove_claude_md_missing(tmp_path: Path) -> None:
    """No CLAUDE.md at all is a no-op returning False."""
    source = tmp_path / "src"
    source.mkdir()
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()

    assert remove_claude_md_symlink(source, claude_dir) is False


def test_remove_claude_md_readlink_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``readlink`` raises after the is_symlink check, we bail out (False)."""
    source = tmp_path / "src"
    source.mkdir()
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    link = claude_dir / "CLAUDE.md"
    link.symlink_to(source / "config" / "CLAUDE.md")

    real_readlink = Path.readlink

    def flaky_readlink(self: Path):
        # Only the CLAUDE.md link should explode; leave others intact.
        if self.name == "CLAUDE.md":
            raise OSError("readlink boom")
        return real_readlink(self)

    monkeypatch.setattr(Path, "readlink", flaky_readlink)

    assert remove_claude_md_symlink(source, claude_dir) is False
    assert link.is_symlink()  # untouched


def test_remove_claude_md_pointing_outside_source(tmp_path: Path) -> None:
    """A CLAUDE.md symlink pointing outside ``source_dir`` is preserved."""
    source = tmp_path / "src"
    source.mkdir()
    foreign = tmp_path / "foreign.md"
    foreign.write_text("not ours\n")
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    link = claude_dir / "CLAUDE.md"
    link.symlink_to(foreign)

    assert remove_claude_md_symlink(source, claude_dir) is False
    assert link.is_symlink()  # still there


# --- _remove_links_into: missing dir + non-symlink entries (lines 155, 160) ---


def test_remove_skill_symlinks_missing_dir(tmp_path: Path) -> None:
    """No ``skills/`` dir under claude_dir means an empty removal list."""
    source = tmp_path / "src"
    source.mkdir()
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()  # no skills/ subdir

    assert remove_skill_symlinks(source, claude_dir) == []


def test_remove_skill_symlinks_ignores_non_symlink_entries(tmp_path: Path) -> None:
    """Real files/dirs sitting in skills/ are skipped, not removed."""
    source = tmp_path / "src"
    skills_src = source / "skills"
    skills_src.mkdir(parents=True)
    real_skill = skills_src / "alpha"
    real_skill.mkdir()
    (real_skill / "SKILL.md").write_text("alpha\n")

    claude_dir = tmp_path / "claude"
    skills_dst = claude_dir / "skills"
    skills_dst.mkdir(parents=True)
    symlink_skills(source, claude_dir)
    # A foreign real directory (not a symlink) that must survive.
    (skills_dst / "foreign-dir").mkdir()
    (skills_dst / "foreign-file").write_text("x\n")

    removed = remove_skill_symlinks(source, claude_dir)

    assert {p.name for p in removed} == {"alpha"}
    assert (skills_dst / "foreign-dir").is_dir()
    assert (skills_dst / "foreign-file").is_file()


# --- _remove_links_into: dangling symlinks (resolve path on Python 3.13) ---
#
# NOTE: on Python 3.13 ``Path.resolve(strict=False)`` no longer raises for a
# missing target (or even a symlink loop), so the ``except OSError`` raw-target
# branch in ``_remove_links_into`` (source lines 163-175) is unreachable on this
# runtime. These tests exercise the dangling case via the non-raising resolve
# path: a link into source is still removed, one outside source is preserved.


def test_remove_agent_symlinks_dangling_into_source(tmp_path: Path) -> None:
    """A dangling symlink whose target lives under source is removed."""
    source = tmp_path / "src"
    agents_src = source / "agents"
    agents_src.mkdir(parents=True)
    target = agents_src / "gone.md"
    target.write_text("agent\n")

    claude_dir = tmp_path / "claude"
    agents_dst = claude_dir / "agents"
    agents_dst.mkdir(parents=True)
    symlink_agents(source, claude_dir)

    # Break the target so resolve() fails — the symlink dangles.
    target.unlink()
    assert (agents_dst / "gone.md").is_symlink()

    removed = remove_agent_symlinks(source, claude_dir)

    assert {p.name for p in removed} == {"gone.md"}
    assert not (agents_dst / "gone.md").is_symlink()


def test_remove_agent_symlinks_dangling_outside_source(tmp_path: Path) -> None:
    """A dangling symlink pointing outside source is preserved."""
    source = tmp_path / "src"
    (source / "agents").mkdir(parents=True)
    foreign_target = tmp_path / "elsewhere" / "ghost.md"
    foreign_target.parent.mkdir()
    foreign_target.write_text("ghost\n")

    claude_dir = tmp_path / "claude"
    agents_dst = claude_dir / "agents"
    agents_dst.mkdir(parents=True)
    link = agents_dst / "ghost.md"
    link.symlink_to(foreign_target)
    foreign_target.unlink()  # now dangling, raw target outside source

    removed = remove_agent_symlinks(source, claude_dir)

    assert removed == []
    assert link.is_symlink()  # untouched
