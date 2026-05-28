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


class _FakeGit:
    """Stub for update's injected runner + capture.

    Records mutating commands and answers the two read-only git queries
    (`git branch --show-current` and the tag list) from a configured
    state, so tests can simulate "on a branch" vs "detached HEAD at a
    tag" without a real git repo.
    """

    def __init__(self, *, branch: str = "", tags: list[str] | None = None) -> None:
        self.branch = branch
        self.tags = tags if tags is not None else []
        self.run_calls: list[tuple[list[str], Path | None]] = []

    def run(self, cmd: list[str], *, cwd: Path | None = None) -> None:
        self.run_calls.append((cmd, cwd))

    def capture(self, cmd: list[str], *, cwd: Path | None = None) -> str:
        if cmd == ["git", "branch", "--show-current"]:
            return self.branch
        if cmd == ["git", "tag", "--list", "--sort=-v:refname", "v*"]:
            return "\n".join(self.tags)
        return ""

    def ran(self, prefix: list[str]) -> bool:
        return any(cmd[: len(prefix)] == prefix for cmd, _ in self.run_calls)


def _install_first(fake_source: Path, provider: str = "local") -> None:
    install(source_dir=fake_source, embedding_provider=provider)


class TestUpdateDetachedHead:
    """Regression tests for the bug where `git pull` ran in detached HEAD."""

    def test_detached_head_checks_out_latest_tag(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source)
        git = _FakeGit(branch="", tags=["v0.15.1", "v0.15.0", "v0.14.1"])

        summary = update(runner=git.run, capture=git.capture)

        # Must NOT run a bare `git pull` (the original bug).
        assert not git.ran(["git", "pull"])
        # Should fetch then checkout the latest tag.
        assert git.ran(["git", "fetch", "origin", "--tags"])
        assert (["git", "checkout", "v0.15.1"], fake_source.resolve()) in git.run_calls
        assert summary.landed_on == "v0.15.1"

    def test_detached_head_no_tags_raises(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source)
        git = _FakeGit(branch="", tags=[])

        with pytest.raises(ValueError, match="detached HEAD and has no v\\* tags"):
            update(runner=git.run, capture=git.capture)


class TestUpdateOnBranch:
    def test_branch_fast_forwards(self, fake_home: Path, fake_source: Path) -> None:
        _install_first(fake_source)
        git = _FakeGit(branch="main", tags=["v0.15.1"])

        summary = update(runner=git.run, capture=git.capture)

        assert git.ran(["git", "fetch", "origin", "--tags"])
        assert git.ran(["git", "merge", "--ff-only"])
        # No tag checkout when on a branch.
        assert not git.ran(["git", "checkout"])
        assert summary.landed_on == "branch main"

    def test_no_pull_on_branch_skips_fetch_and_merge(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source)
        git = _FakeGit(branch="main", tags=["v0.15.1"])

        summary = update(no_pull=True, runner=git.run, capture=git.capture)

        assert not git.ran(["git", "fetch"])
        assert not git.ran(["git", "merge"])
        assert summary.fetched is False
        assert summary.landed_on == "branch main"


class TestUpdateRef:
    def test_ref_checks_out_after_fetch(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source)
        git = _FakeGit(branch="", tags=["v0.15.1"])

        summary = update(ref="v0.14.1", runner=git.run, capture=git.capture)

        assert git.ran(["git", "fetch", "origin", "--tags"])
        assert (["git", "checkout", "v0.14.1"], fake_source.resolve()) in git.run_calls
        assert summary.landed_on == "v0.14.1"

    def test_ref_with_no_pull_skips_fetch(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source)
        git = _FakeGit(branch="", tags=["v0.15.1"])

        update(ref="v0.14.1", no_pull=True, runner=git.run, capture=git.capture)

        assert not git.ran(["git", "fetch"])
        assert (["git", "checkout", "v0.14.1"], fake_source.resolve()) in git.run_calls


class TestUpdateReinstall:
    def test_uv_tool_install_invoked(self, fake_home: Path, fake_source: Path) -> None:
        _install_first(fake_source)
        git = _FakeGit(branch="main", tags=[])

        update(no_pull=True, runner=git.run, capture=git.capture)

        assert git.ran(["uv", "tool", "install"])

    def test_bedrock_provider_passes_extra(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source, provider="bedrock")
        git = _FakeGit(branch="main", tags=[])

        update(no_pull=True, runner=git.run, capture=git.capture)

        uv_call = next(
            cmd for cmd, _ in git.run_calls if cmd[:3] == ["uv", "tool", "install"]
        )
        assert uv_call[3].endswith("[bedrock]")

    def test_bumps_record(self, fake_home: Path, fake_source: Path) -> None:
        _install_first(fake_source)
        before = read_record()
        git = _FakeGit(branch="main", tags=[])

        update(no_pull=True, runner=git.run, capture=git.capture)

        after = read_record()
        assert after.installed_at >= before.installed_at

    def test_refreshes_symlinks(self, fake_home: Path, fake_source: Path) -> None:
        _install_first(fake_source)
        new_skill = fake_source / "skills" / "fresh"
        new_skill.mkdir()
        (new_skill / "SKILL.md").write_text("fresh skill\n")

        git = _FakeGit(branch="main", tags=[])
        summary = update(no_pull=True, runner=git.run, capture=git.capture)

        link = fake_home / ".claude" / "skills" / "fresh"
        assert link.is_symlink()
        assert any(p.name == "fresh" for p in summary.skills.created)

    def test_no_record_raises(self, fake_home: Path) -> None:
        from mait_code.cli._record import RecordError

        git = _FakeGit()
        with pytest.raises(RecordError, match="No install record"):
            update(no_pull=True, runner=git.run, capture=git.capture)


class TestUpdateReadsProviderFromSettings:
    """The embedding provider comes from the centralised settings file that
    `mait-code install` writes (0.19.0+). Update reads it to pick the
    reinstall extra, and fails clearly when the file is missing rather than
    silently defaulting (which would drop the bedrock extra).
    """

    @staticmethod
    def _settings_toml(fake_home: Path) -> Path:
        return fake_home / ".config" / "mait-code" / "settings.toml"

    @staticmethod
    def _uv_target(git: _FakeGit) -> str:
        cmd = next(c for c, _ in git.run_calls if c[:3] == ["uv", "tool", "install"])
        return cmd[3]

    def test_local_provider_omits_bedrock_extra(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source, provider="local")
        git = _FakeGit(branch="main", tags=[])

        update(no_pull=True, runner=git.run, capture=git.capture)

        assert not self._uv_target(git).endswith("[bedrock]")

    def test_bedrock_provider_keeps_extra_across_update(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source, provider="bedrock")
        git = _FakeGit(branch="main", tags=[])

        update(no_pull=True, runner=git.run, capture=git.capture)

        assert self._uv_target(git).endswith("[bedrock]")

    def test_missing_settings_file_raises(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _install_first(fake_source, provider="bedrock")
        self._settings_toml(fake_home).unlink()  # simulate a pre-0.19.0 install
        git = _FakeGit(branch="main", tags=[])

        with pytest.raises(ValueError, match="mait-code install"):
            update(no_pull=True, runner=git.run, capture=git.capture)

        # Bailed before reinstalling — no chance to drop the bedrock extra.
        assert not git.ran(["uv", "tool", "install"])


class TestUpdateCommand:
    def test_cli_invokes_update(
        self, fake_home: Path, fake_source: Path, monkeypatch
    ) -> None:
        _install_first(fake_source)

        git = _FakeGit(branch="main", tags=[])
        monkeypatch.setattr("mait_code.cli._update.default_runner", git.run)
        monkeypatch.setattr("mait_code.cli._update.default_capture", git.capture)

        result = runner.invoke(app, ["update", "--no-pull"])
        assert result.exit_code == 0, result.output
        assert "Updated mait-code" in result.output

    def test_cli_no_record_exits_1(self, fake_home: Path) -> None:
        result = runner.invoke(app, ["update", "--no-pull"])
        assert result.exit_code == 1
        assert "No install record" in result.output

    def test_cli_missing_settings_exits_1(
        self, fake_home: Path, fake_source: Path, monkeypatch
    ) -> None:
        _install_first(fake_source)
        (fake_home / ".config" / "mait-code" / "settings.toml").unlink()
        git = _FakeGit(branch="main", tags=[])
        monkeypatch.setattr("mait_code.cli._update.default_runner", git.run)
        monkeypatch.setattr("mait_code.cli._update.default_capture", git.capture)

        result = runner.invoke(app, ["update", "--no-pull"])
        assert result.exit_code == 1
        assert "mait-code install" in result.output
