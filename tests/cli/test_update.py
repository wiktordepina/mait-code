"""Tests for ``mait-code update``."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mait_code.cli import app
from mait_code.cli._install import install
from mait_code.cli._record import read_record
from mait_code.cli._update import update

runner = CliRunner()


class _RecordingRunner:
    """Test stub for the subprocess runner used by `update`."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        self.calls.append((cmd, cwd))


def _install_first(fake_source: Path, provider: str = "local") -> None:
    install(source_dir=fake_source, embedding_provider=provider)


class TestUpdate:
    def test_default_runs_pull_and_reinstall(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source)
        stub = _RecordingRunner()

        summary = update(runner=stub)

        # Expect: git pull, then uv tool install.
        assert stub.calls[0][0] == ["git", "pull"]
        assert stub.calls[0][1] == fake_source.resolve()
        assert stub.calls[1][0][:3] == ["uv", "tool", "install"]
        assert summary.pulled is True
        assert summary.ref is None

    def test_no_pull_skips_git(self, fake_home: Path, fake_source: Path) -> None:
        _install_first(fake_source)
        stub = _RecordingRunner()

        summary = update(no_pull=True, runner=stub)

        assert all(call[0][0] != "git" or call[0][1] != "pull" for call in stub.calls)
        assert summary.pulled is False

    def test_ref_triggers_checkout(self, fake_home: Path, fake_source: Path) -> None:
        _install_first(fake_source)
        stub = _RecordingRunner()

        update(ref="v0.14.1", no_pull=True, runner=stub)

        assert stub.calls[0][0] == ["git", "checkout", "v0.14.1"]

    def test_bedrock_provider_passes_extra(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source, provider="bedrock")
        stub = _RecordingRunner()

        update(no_pull=True, runner=stub)

        uv_call = next(
            call for call in stub.calls if call[0][:3] == ["uv", "tool", "install"]
        )
        # The source-dir argument should have the [bedrock] extra appended.
        assert uv_call[0][3].endswith("[bedrock]")

    def test_bumps_record_installed_at(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source)
        before = read_record()
        stub = _RecordingRunner()

        update(no_pull=True, runner=stub)

        after = read_record()
        assert after.installed_at >= before.installed_at
        # Provider preserved across update.
        assert after.embedding_provider == before.embedding_provider

    def test_refreshes_symlinks_and_settings(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        # Plant a new skill that wasn't there at install time.
        _install_first(fake_source)
        new_skill = fake_source / "skills" / "fresh"
        new_skill.mkdir()
        (new_skill / "SKILL.md").write_text("fresh skill\n")

        stub = _RecordingRunner()
        summary = update(no_pull=True, runner=stub)

        # The new skill should now be linked.
        link = fake_home / ".claude" / "skills" / "fresh"
        assert link.is_symlink()
        # Either it was created or already_linked (depending on what install did).
        assert any(p.name == "fresh" for p in summary.skills.created)

    def test_no_record_raises(self, fake_home: Path) -> None:
        from mait_code.cli._record import RecordError

        with pytest.raises(RecordError, match="No install record"):
            update(no_pull=True, runner=_RecordingRunner())


class TestUpdateCommand:
    def test_cli_invokes_update(
        self, fake_home: Path, fake_source: Path, monkeypatch
    ) -> None:
        _install_first(fake_source)

        recorded: list[list[str]] = []

        def fake_runner(cmd: list[str], *, cwd=None) -> None:
            recorded.append(cmd)

        monkeypatch.setattr(
            "mait_code.cli._update.default_runner",
            fake_runner,
        )

        result = runner.invoke(app, ["update", "--no-pull"])
        assert result.exit_code == 0, result.output
        assert "Updated mait-code" in result.output

    def test_cli_no_record_exits_1(self, fake_home: Path) -> None:
        result = runner.invoke(app, ["update", "--no-pull"])
        assert result.exit_code == 1
        assert "No install record" in result.output
