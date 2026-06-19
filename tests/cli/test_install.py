"""Tests for ``mait-code install`` and its helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mait_code.cli import (
    app,
    install_record_path,
    merge_settings,
    read_record,
    unmerge_settings,
)
from mait_code.cli._install import install, verify_source
from mait_code.cli._settings import (
    _entry_is_mait_code,
    read_settings_file as read_claude_settings,
    write_settings_file as write_claude_settings,
)
from mait_code.cli._symlinks import (
    remove_claude_md_symlink,
    remove_skill_symlinks,
    symlink_claude_md,
    symlink_skills,
)

runner = CliRunner()


def _populate_fake_source_with_skills_and_agents(fake_source: Path) -> None:
    """Add a couple of skills and an agent so symlink tests have content."""
    skill_a = fake_source / "skills" / "alpha"
    skill_a.mkdir()
    (skill_a / "SKILL.md").write_text("alpha skill\n")

    skill_b = fake_source / "skills" / "beta"
    skill_b.mkdir()
    (skill_b / "SKILL.md").write_text("beta skill\n")

    (fake_source / "skills" / ".gitkeep").write_text("")

    (fake_source / "agents" / "agent-one.md").write_text("agent\n")
    (fake_source / "agents" / ".gitkeep").write_text("")


class TestVerifySource:
    def test_accepts_fake_source(self, fake_source: Path) -> None:
        verify_source(fake_source)  # does not raise

    def test_rejects_nonexistent(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a directory"):
            verify_source(tmp_path / "nope")

    def test_rejects_missing_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "mait_code").mkdir(parents=True)
        with pytest.raises(ValueError, match="no pyproject.toml"):
            verify_source(tmp_path)

    def test_rejects_wrong_project_name(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "other"\n')
        (tmp_path / "src" / "mait_code").mkdir(parents=True)
        with pytest.raises(ValueError, match="not the mait-code project"):
            verify_source(tmp_path)

    def test_rejects_missing_package_dir(self, tmp_path: Path) -> None:
        # Right project name in pyproject, but no src/mait_code package — the
        # final structural check rejects it as "not a mait-code clone".
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "mait-code"\n')
        with pytest.raises(ValueError, match="src/mait_code is missing"):
            verify_source(tmp_path)


class TestInstallHappyPath:
    def test_creates_data_dirs(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        data_dir = fake_home / ".claude" / "mait-code-data"
        assert (data_dir / "memory" / "observations").is_dir()
        assert (data_dir / "memory" / "reflections").is_dir()
        # memory/graph is deliberately not created.
        assert not (data_dir / "memory" / "graph").exists()

    def test_copies_templates(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        data_dir = fake_home / ".claude" / "mait-code-data"
        assert (data_dir / "soul_document.md").read_text() == "# soul template\n"
        assert (data_dir / "user_context.md").read_text() == (
            "# user context template\n"
        )

    def test_creates_memory_md(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        memory = fake_home / ".claude" / "mait-code-data" / "memory" / "MEMORY.md"
        assert memory.exists()
        assert memory.read_text().startswith("# Memory")

    def test_symlinks_claude_md(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        link = fake_home / ".claude" / "CLAUDE.md"
        assert link.is_symlink()
        assert link.readlink() == (fake_source / "config" / "CLAUDE.md").resolve()

    def test_symlinks_skills_and_agents(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _populate_fake_source_with_skills_and_agents(fake_source)
        install(source_dir=fake_source)
        skills = fake_home / ".claude" / "skills"
        assert (skills / "alpha").is_symlink()
        assert (skills / "beta").is_symlink()
        assert not (skills / ".gitkeep").exists()
        agents = fake_home / ".claude" / "agents"
        assert (agents / "agent-one.md").is_symlink()

    def test_merges_settings(self, fake_home: Path, fake_source: Path) -> None:
        # Pre-existing user settings with an unrelated key.
        existing = fake_home / ".claude" / "settings.json"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text(
            json.dumps({"theme": "dark", "hooks": {}, "mcpServers": {}})
        )

        install(source_dir=fake_source, embedding_provider="bedrock")

        merged = json.loads(existing.read_text())
        assert merged["theme"] == "dark"  # user key preserved
        assert "SessionStart" in merged["hooks"]
        assert merged["env"]["MAIT_CODE_EMBEDDING_PROVIDER"] == "bedrock"

    def test_writes_install_record(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source, embedding_provider="local")
        record = read_record()
        assert record.source_dir == str(fake_source.resolve())

    def test_writes_settings_file(self, fake_home: Path, fake_source: Path) -> None:
        from mait_code.config import read_settings_file

        install(source_dir=fake_source, embedding_provider="bedrock")

        assert read_settings_file()["embedding-provider"] == "bedrock"

    def test_rejects_invalid_provider(self, fake_home: Path, fake_source: Path) -> None:
        with pytest.raises(ValueError, match="--embedding-provider must be one of"):
            install(source_dir=fake_source, embedding_provider="invalid")


class TestInstallIdempotency:
    def test_running_twice_is_safe(self, fake_home: Path, fake_source: Path) -> None:
        _populate_fake_source_with_skills_and_agents(fake_source)
        first = install(source_dir=fake_source)
        second = install(source_dir=fake_source)
        # First run creates the links; second run sees them already linked.
        assert second.claude_md.already_linked or second.claude_md.updated
        assert len(second.skills.already_linked) >= len(first.skills.created)

    def test_templates_not_overwritten(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        data_dir = fake_home / ".claude" / "mait-code-data"
        data_dir.mkdir(parents=True)
        (data_dir / "soul_document.md").write_text("MY PERSONALISED VERSION\n")
        install(source_dir=fake_source)
        assert (data_dir / "soul_document.md").read_text() == (
            "MY PERSONALISED VERSION\n"
        )


class TestInstallBackup:
    def test_existing_non_symlink_claude_md_backed_up(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        claude_dir = fake_home / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("user's own CLAUDE.md\n")

        install(source_dir=fake_source)

        assert (claude_dir / "CLAUDE.md").is_symlink()
        assert (claude_dir / "CLAUDE.md.backup").read_text() == (
            "user's own CLAUDE.md\n"
        )


class TestInstallCommand:
    def test_cli_invokes_install(self, fake_home: Path, fake_source: Path) -> None:
        result = runner.invoke(
            app,
            ["install", "--from", str(fake_source), "--embedding-provider", "local"],
        )
        assert result.exit_code == 0, result.output
        assert "Installed mait-code" in result.output
        assert install_record_path().exists()

    def test_cli_bad_provider_exits_1(self, fake_home: Path, fake_source: Path) -> None:
        result = runner.invoke(
            app,
            ["install", "--from", str(fake_source), "--embedding-provider", "nope"],
        )
        assert result.exit_code == 1


class TestSymlinkHelpers:
    def test_remove_claude_md_restores_backup(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        claude_dir = fake_home / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("original\n")

        symlink_claude_md(fake_source, claude_dir)
        assert (claude_dir / "CLAUDE.md").is_symlink()
        assert (claude_dir / "CLAUDE.md.backup").read_text() == "original\n"

        removed = remove_claude_md_symlink(fake_source, claude_dir)
        assert removed is True
        # Backup is restored.
        assert (claude_dir / "CLAUDE.md").read_text() == "original\n"
        assert not (claude_dir / "CLAUDE.md.backup").exists()

    def test_remove_skill_symlinks_only_targets_source(
        self, fake_home: Path, fake_source: Path, tmp_path: Path
    ) -> None:
        _populate_fake_source_with_skills_and_agents(fake_source)
        claude_dir = fake_home / ".claude"
        symlink_skills(fake_source, claude_dir)

        # Plant a foreign skill symlink that should NOT be removed.
        foreign_src = tmp_path / "foreign-skill"
        foreign_src.mkdir()
        foreign_link = claude_dir / "skills" / "foreign"
        foreign_link.symlink_to(foreign_src)

        removed = remove_skill_symlinks(fake_source, claude_dir)
        removed_names = {p.name for p in removed}
        assert "alpha" in removed_names
        assert "beta" in removed_names
        assert "foreign" not in removed_names
        # Foreign link is still there.
        assert foreign_link.is_symlink()


class TestSettingsHelpers:
    def test_merge_preserves_user_keys(self) -> None:
        src = {"hooks": {"X": [{"hooks": [{"command": "mc-hook-x"}]}]}}
        dst = {"theme": "dark"}
        result = merge_settings(src, dst, user_settings={"embedding-provider": "local"})
        assert result["theme"] == "dark"
        assert "X" in result["hooks"]
        assert result["env"]["MAIT_CODE_EMBEDDING_PROVIDER"] == "local"

    def test_unmerge_strips_mait_code_entries(self) -> None:
        settings = {
            "theme": "dark",
            "hooks": {
                "SessionStart": [
                    {"hooks": [{"command": "mc-hook-session-start"}]},
                    {"hooks": [{"command": "other-tool-hook"}]},
                ]
            },
            "mcpServers": {"mait-reminders": {}, "other-server": {}},
            "env": {"MAIT_CODE_EMBEDDING_PROVIDER": "local", "USER_VAR": "x"},
        }
        cleaned = unmerge_settings(settings)
        # mait-code hook entry stripped, other-tool-hook kept.
        assert len(cleaned["hooks"]["SessionStart"]) == 1
        assert "mait-reminders" not in cleaned["mcpServers"]
        assert "other-server" in cleaned["mcpServers"]
        assert "MAIT_CODE_EMBEDDING_PROVIDER" not in cleaned["env"]
        assert cleaned["env"]["USER_VAR"] == "x"
        assert cleaned["theme"] == "dark"

    def test_unmerge_drops_empty_sections(self) -> None:
        settings = {
            "hooks": {
                "SessionStart": [{"hooks": [{"command": "mc-hook-x"}]}],
            },
            "mcpServers": {"mait-reminders": {}},
            "env": {"MAIT_CODE_EMBEDDING_PROVIDER": "local"},
        }
        cleaned = unmerge_settings(settings)
        assert "hooks" not in cleaned
        assert "mcpServers" not in cleaned
        assert "env" not in cleaned

    def test_merge_with_no_hooks_or_servers(self) -> None:
        # Empty source + empty dest: neither a hooks nor mcpServers section
        # is created (the `if merged_hooks` / `if merged_servers` guards stay
        # false), but the env table is always written.
        result = merge_settings({}, {}, user_settings={"embedding-provider": "local"})
        assert "hooks" not in result
        assert "mcpServers" not in result
        assert result["env"]["MAIT_CODE_EMBEDDING_PROVIDER"] == "local"

    def test_merge_carries_source_mcp_servers(self) -> None:
        # Exercise the mcpServers merge loop body: a source server is copied
        # in alongside a pre-existing user server.
        src = {"mcpServers": {"mait-reminders": {"command": "mc"}}}
        dst = {"mcpServers": {"user-server": {"command": "u"}}}
        result = merge_settings(src, dst, user_settings={})
        assert result["mcpServers"]["mait-reminders"] == {"command": "mc"}
        assert result["mcpServers"]["user-server"] == {"command": "u"}

    def test_unmerge_ignores_non_list_hook_section(self) -> None:
        # A hook section whose value isn't a list is left untouched (the
        # `continue` guard) — we only filter list-shaped entry collections.
        settings = {"hooks": {"Weird": "not-a-list"}}
        cleaned = unmerge_settings(settings)
        assert cleaned["hooks"]["Weird"] == "not-a-list"

    def test_entry_is_mait_code_guards(self) -> None:
        # Defensive shape checks: a non-dict entry, a non-list inner `hooks`,
        # and a non-dict element inside it all return False (not ours).
        assert _entry_is_mait_code("not-a-dict") is False
        assert _entry_is_mait_code({"hooks": "not-a-list"}) is False
        assert _entry_is_mait_code({"hooks": ["not-a-dict"]}) is False
        # A real mait-code command is recognised.
        assert _entry_is_mait_code({"hooks": [{"command": "mc-hook-x"}]}) is True


class TestSettingsFileIO:
    def test_read_missing_returns_empty(self, tmp_path: Path) -> None:
        assert read_claude_settings(tmp_path / "nope.json") == {}

    def test_read_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        bad = tmp_path / "settings.json"
        bad.write_text("{ not valid json", encoding="utf-8")
        assert read_claude_settings(bad) == {}

    def test_read_non_object_returns_empty(self, tmp_path: Path) -> None:
        # Valid JSON that isn't a top-level object (a list) is rejected.
        f = tmp_path / "settings.json"
        f.write_text("[1, 2, 3]", encoding="utf-8")
        assert read_claude_settings(f) == {}

    def test_write_round_trips(self, tmp_path: Path) -> None:
        f = tmp_path / "deep" / "settings.json"
        write_claude_settings(f, {"theme": "dark"})
        assert read_claude_settings(f) == {"theme": "dark"}

    def test_write_cleans_up_tempfile_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # os.replace failing mid-write must unlink the partial tempfile and
        # re-raise rather than leaving scratch debris behind.
        import mait_code.cli._settings as settings_mod

        f = tmp_path / "settings.json"

        def boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(settings_mod.os, "replace", boom)
        with pytest.raises(OSError, match="disk full"):
            write_claude_settings(f, {"theme": "dark"})
        assert not list(tmp_path.glob("settings.json.*.tmp"))
