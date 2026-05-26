"""Tests for ``mait-code uninstall``."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mait_code.cli import app
from mait_code.cli._install import install
from mait_code.cli._paths import install_record_path
from mait_code.cli._uninstall import uninstall

runner = CliRunner()


def _populate_source(fake_source: Path) -> None:
    skill = fake_source / "skills" / "alpha"
    skill.mkdir()
    (skill / "SKILL.md").write_text("alpha\n")
    (fake_source / "agents" / "agent.md").write_text("agent\n")


def _safe_runner_success(_cmd: list[str]) -> bool:
    return True


def _safe_runner_failure(_cmd: list[str]) -> bool:
    return False


class TestUninstall:
    def test_removes_symlinks_and_settings(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _populate_source(fake_source)
        install(source_dir=fake_source)

        # Confirm preconditions: links exist, settings carries our env.
        assert (fake_home / ".claude" / "CLAUDE.md").is_symlink()
        assert (fake_home / ".claude" / "skills" / "alpha").is_symlink()
        assert install_record_path().exists()

        summary = uninstall(safe_runner=_safe_runner_success)

        assert summary.claude_md_removed is True
        assert any(p.name == "alpha" for p in summary.skills_removed)
        assert any(p.name == "agent.md" for p in summary.agents_removed)
        assert summary.settings_cleaned is True
        assert summary.uv_tool_uninstalled is True
        # Record is gone.
        assert not install_record_path().exists()
        # Symlinks gone.
        assert not (fake_home / ".claude" / "CLAUDE.md").exists()
        assert not (fake_home / ".claude" / "skills" / "alpha").exists()

    def test_data_dir_preserved_by_default(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        data_dir = fake_home / ".claude" / "mait-code-data"
        assert data_dir.exists()

        summary = uninstall(safe_runner=_safe_runner_success)
        assert summary.data_dir_removed is False
        assert data_dir.exists()
        assert (data_dir / "soul_document.md").exists()

    def test_purge_data_removes_data_dir(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        data_dir = fake_home / ".claude" / "mait-code-data"

        summary = uninstall(purge_data=True, safe_runner=_safe_runner_success)
        assert summary.data_dir_removed is True
        assert not data_dir.exists()

    def test_idempotent(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        uninstall(safe_runner=_safe_runner_success)
        # Second run with no record. Should succeed without raising.
        summary = uninstall(safe_runner=_safe_runner_success)
        assert summary.had_record is False
        assert summary.claude_md_removed is False
        assert summary.skills_removed == []

    def test_keep_uv_tool_skips_subprocess(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)

        called: list[list[str]] = []

        def recording_safe(cmd: list[str]) -> bool:
            called.append(cmd)
            return True

        uninstall(keep_uv_tool=True, safe_runner=recording_safe)
        assert called == []  # uv tool uninstall was not invoked

    def test_uv_tool_uninstall_failure_is_warning(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        summary = uninstall(safe_runner=_safe_runner_failure)
        assert summary.uv_tool_uninstalled is False
        assert any("uv tool uninstall" in w for w in summary.warnings)

    def test_preserves_foreign_settings(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        # Set up a settings.json with both mait-code and user entries
        # before install — install will merge, uninstall should strip
        # only mait-code's.
        settings_path = fake_home / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(
                {
                    "theme": "dark",
                    "mcpServers": {"foreign": {"command": "x"}},
                }
            )
        )
        install(source_dir=fake_source)
        uninstall(safe_runner=_safe_runner_success)

        final = json.loads(settings_path.read_text())
        assert final.get("theme") == "dark"
        assert "foreign" in final.get("mcpServers", {})
        # mait-code entries gone.
        assert "MAIT_CODE_EMBEDDING_PROVIDER" not in final.get("env", {})


class TestUninstallCommand:
    def test_cli_invokes_uninstall(
        self, fake_home: Path, fake_source: Path, monkeypatch
    ) -> None:
        install(source_dir=fake_source)

        monkeypatch.setattr(
            "mait_code.cli._uninstall._safe_default_runner",
            _safe_runner_success,
        )

        result = runner.invoke(app, ["uninstall"])
        assert result.exit_code == 0, result.output
        assert "Uninstalled mait-code" in result.output
        assert not install_record_path().exists()

    def test_cli_purge_data(
        self, fake_home: Path, fake_source: Path, monkeypatch
    ) -> None:
        install(source_dir=fake_source)
        monkeypatch.setattr(
            "mait_code.cli._uninstall._safe_default_runner",
            _safe_runner_success,
        )

        result = runner.invoke(app, ["uninstall", "--purge-data"])
        assert result.exit_code == 0, result.output
        assert "Removed data directory" in result.output
        assert not (fake_home / ".claude" / "mait-code-data").exists()
