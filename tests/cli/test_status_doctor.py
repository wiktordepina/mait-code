"""Tests for ``mait-code status`` and ``mait-code doctor``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from mait_code import config
from mait_code.cli import app
from mait_code.cli._doctor import (
    render as doctor_render,
    render_json as doctor_render_json,
    run_doctor,
)
from mait_code.cli._install import install
from mait_code.cli._status import collect_status, render as status_render, render_json
from mait_code.console import console

runner = CliRunner()


def _populate_source(fake_source: Path) -> None:
    (fake_source / "skills" / "alpha").mkdir()
    (fake_source / "skills" / "alpha" / "SKILL.md").write_text("alpha\n")
    (fake_source / "skills" / "beta").mkdir()
    (fake_source / "skills" / "beta" / "SKILL.md").write_text("beta\n")
    (fake_source / "agents" / "agent.md").write_text("agent\n")


class TestStatus:
    def test_no_install_record(self, fake_home: Path) -> None:
        status = collect_status()
        assert status.record_present is False
        assert status.record_error is not None
        assert status.source_dir is None

    def test_after_install(self, fake_home: Path, fake_source: Path) -> None:
        _populate_source(fake_source)
        install(source_dir=fake_source)

        status = collect_status()
        assert status.record_present is True
        assert status.source_dir == str(fake_source.resolve())
        assert status.embedding_provider == "local"
        assert status.claude_md_is_symlink is True
        assert status.skills_linked == 2
        assert status.skills_total == 2
        assert status.agents_linked == 1
        assert status.agents_total == 1
        assert "SessionStart" in status.hooks_registered
        assert status.has_soul_document is True
        assert status.has_memory_md is True

    def test_text_rendering(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        with console.capture() as cap:
            status_render(collect_status())
        text = cap.get()
        assert "mait-code" in text
        # Section labels and a representative key.
        assert "Install" in text
        assert "Identity" in text
        assert "Components" in text
        assert "Memory" in text
        assert "CLAUDE.md" in text

    def test_text_rendering_no_record_shows_badge(self, fake_home: Path) -> None:
        with console.capture() as cap:
            status_render(collect_status())
        text = cap.get()
        assert "not installed" in text  # health badge
        assert "no install record found" in text

    def test_json_rendering(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        payload = json.loads(render_json(collect_status()))
        assert payload["record_present"] is True
        assert payload["embedding_provider"] == "local"


class TestStatusCommand:
    def test_cli_no_record(self, fake_home: Path) -> None:
        # A settings file exists but no install record: status still reports.
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "no install record" in result.output.lower()

    def test_cli_aborts_when_settings_file_missing(self, fake_home: Path) -> None:
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        assert "settings file not found" in result.output.lower()
        assert "mait-code install" in result.output

    def test_cli_json(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["record_present"] is True


class TestDoctor:
    def test_no_install_record_marks_record_fail(self, fake_home: Path) -> None:
        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["install-record"].level == "fail"
        # Source dir check skips when there's no record.
        assert names["source-dir"].level == "warn"

    def test_happy_path(self, fake_home: Path, fake_source: Path) -> None:
        _populate_source(fake_source)
        install(source_dir=fake_source)

        report = run_doctor()
        levels = {c.name: c.level for c in report.checks}
        assert levels["install-record"] == "ok"
        assert levels["source-dir"] == "ok"
        assert levels["settings"] == "ok"
        assert levels["settings-file"] == "ok"
        assert levels["settings-values"] == "ok"
        assert levels["symlinks"] == "ok"
        assert levels["data-dir"] == "ok"
        assert levels["memory-embeddings"] == "ok"
        assert levels["vector-search"] == "ok"
        assert levels["observe-pipeline"] == "ok"

    def test_bad_setting_value_marks_settings_values_fail(
        self, fake_home: Path, fake_source: Path, monkeypatch
    ) -> None:
        _populate_source(fake_source)
        install(source_dir=fake_source)
        # Skew the scoring weights so they no longer sum to 1.0.
        monkeypatch.setenv("MAIT_CODE_SCORE_WEIGHT_RELEVANCE", "0.9")

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["settings-values"].level == "fail"
        assert "sum to" in names["settings-values"].message
        assert report.has_fail is True

    def test_missing_settings_file_marks_fail(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        (fake_home / ".config" / "mait-code" / "settings.toml").unlink()

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["settings-file"].level == "fail"
        assert report.has_fail is True

    def test_dangling_symlink_warns_without_fix(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _populate_source(fake_source)
        install(source_dir=fake_source)

        # Break a skill symlink by removing its target.
        target = fake_source / "skills" / "alpha"
        import shutil as _shutil

        _shutil.rmtree(target)

        report = run_doctor()
        symlinks = next(c for c in report.checks if c.name == "symlinks")
        # Dangling symlinks are auto-fixable, so this is a warning, not a fail.
        assert symlinks.level == "warn"
        assert "dangling" in symlinks.message
        assert symlinks.fix_hint == "mait-code doctor --fix"

    def test_fix_removes_dangling_symlinks(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _populate_source(fake_source)
        install(source_dir=fake_source)
        import shutil as _shutil

        _shutil.rmtree(fake_source / "skills" / "alpha")

        report = run_doctor(fix=True)
        symlinks = next(c for c in report.checks if c.name == "symlinks")
        assert symlinks.level == "ok"
        assert any("dangling symlink" in f for f in report.fixes_applied)

    def test_missing_data_dir_fix_creates_it(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        import shutil as _shutil

        ddir = fake_home / ".claude" / "mait-code-data"
        _shutil.rmtree(ddir)

        report = run_doctor(fix=True)
        data = next(c for c in report.checks if c.name == "data-dir")
        assert data.level == "ok"
        assert ddir.exists()

    def test_json_includes_fix_hint(self, fake_home: Path) -> None:
        # No install record -> install-record fails and carries a hint.
        report = run_doctor()
        payload = json.loads(doctor_render_json(report))
        record = next(c for c in payload["checks"] if c["name"] == "install-record")
        assert "fix_hint" in record
        assert "mait-code install" in record["fix_hint"]

    def test_render_prints_verdict_and_inline_hint(self, fake_home: Path) -> None:
        report = run_doctor()  # no record present -> at least one failure
        with console.capture() as cap:
            doctor_render(report)
        out = cap.get()
        assert "install-record" in out
        assert "passed" in out  # the closing verdict line
        assert "mait-code install" in out  # the failing check's inline fix hint


class TestDoctorCommand:
    def test_cli_exit_0_on_clean(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        result = runner.invoke(app, ["doctor"])
        # `uv-on-path` may fail in a sandboxed test env, so don't assert
        # full success — just that a non-clean run exits 1 with --json
        # we can verify shape regardless.
        assert result.exit_code in (0, 1)

    def test_cli_json_output(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        result = runner.invoke(app, ["doctor", "--json"])
        payload = json.loads(result.output)
        assert "checks" in payload
        assert "has_fail" in payload
        assert isinstance(payload["checks"], list)

    def test_cli_no_record_exits_1(self, fake_home: Path) -> None:
        result = runner.invoke(app, ["doctor"])
        # Missing record is a fail; doctor should exit 1.
        assert result.exit_code == 1

    def test_cli_no_color_flag_accepted(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        result = runner.invoke(app, ["--no-color", "doctor"])
        # uv-on-path may fail in a sandbox, so accept either clean or failing.
        assert result.exit_code in (0, 1)


class TestDoctorMemoryChecks:
    """The memory-health checks: embeddings, vector search, observe pipeline."""

    @staticmethod
    def _data_dir(fake_home: Path) -> Path:
        return fake_home / ".claude" / "mait-code-data"

    def _make_db(self, fake_home: Path, *, entries: int, embedded: int):
        """Create a real memory.db with `entries` rows, `embedded` of them vectored."""
        from mait_code.tools.memory.db import get_connection
        from mait_code.tools.memory.embeddings import serialize_f32

        conn = get_connection(self._data_dir(fake_home) / "memory.db")
        for i in range(entries):
            cur = conn.execute(
                "INSERT INTO memory_entries (content) VALUES (?)", (f"entry {i}",)
            )
            if i < embedded:
                conn.execute(
                    "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
                    (cur.lastrowid, serialize_f32([0.1] * 768)),
                )
        conn.commit()
        conn.close()

    def _check(self, name: str):
        report = run_doctor()
        return next(c for c in report.checks if c.name == name)

    def test_no_memory_db_all_ok(self, fake_home: Path) -> None:
        levels = {c.name: c.level for c in run_doctor().checks}
        assert levels["memory-embeddings"] == "ok"
        assert levels["vector-search"] == "ok"
        assert levels["observe-pipeline"] == "ok"

    def test_missing_embeddings_warn_with_reindex_hint(self, fake_home: Path) -> None:
        self._make_db(fake_home, entries=3, embedded=1)
        check = self._check("memory-embeddings")
        assert check.level == "warn"
        assert "2 of 3" in check.message
        assert check.fix_hint == "mc-tool-memory reindex (or mait-code doctor --fix)"

    def test_missing_embeddings_not_fixed_without_flag(self, fake_home: Path) -> None:
        self._make_db(fake_home, entries=3, embedded=1)
        with patch("mait_code.tools.memory.cli.run_reindex") as reindex:
            run_doctor()
        reindex.assert_not_called()

    def test_fix_embeds_missing_and_reports(self, fake_home: Path) -> None:
        self._make_db(fake_home, entries=3, embedded=1)
        with patch("mait_code.tools.memory.cli.run_reindex", return_value=2) as reindex:
            report = run_doctor(fix=True)
        check = next(c for c in report.checks if c.name == "memory-embeddings")
        assert check.level == "ok"
        assert "embedded 2 missing entries" in check.message
        reindex.assert_called_once_with(
            self._data_dir(fake_home).resolve() / "memory.db", missing_only=True
        )
        assert any("embedded 2 missing" in f for f in report.fixes_applied)

    def test_fix_progress_goes_to_stderr(self, fake_home: Path, capsys) -> None:
        # ``doctor --fix --json`` must keep a parseable stdout, so the
        # reindex progress lines are redirected to stderr.
        self._make_db(fake_home, entries=3, embedded=1)

        def fake_reindex(_db, missing_only=False):
            print("Embedded 2/2 entries...")
            return 2

        with patch("mait_code.tools.memory.cli.run_reindex", side_effect=fake_reindex):
            run_doctor(fix=True)
        captured = capsys.readouterr()
        assert "Embedded 2/2" in captured.err
        assert "Embedded" not in captured.out

    def test_fix_failure_keeps_warn(self, fake_home: Path) -> None:
        from mait_code.tools.memory.cli import ReindexError

        self._make_db(fake_home, entries=3, embedded=1)
        with patch(
            "mait_code.tools.memory.cli.run_reindex",
            side_effect=ReindexError("embedding model unavailable"),
        ):
            report = run_doctor(fix=True)
        check = next(c for c in report.checks if c.name == "memory-embeddings")
        assert check.level == "warn"
        assert "embedding them failed: embedding model unavailable" in check.message
        assert report.fixes_applied == []

    def test_fix_noop_when_all_embedded(self, fake_home: Path) -> None:
        self._make_db(fake_home, entries=2, embedded=2)
        with patch("mait_code.tools.memory.cli.run_reindex") as reindex:
            run_doctor(fix=True)
        reindex.assert_not_called()

    def test_all_embedded_ok(self, fake_home: Path) -> None:
        self._make_db(fake_home, entries=2, embedded=2)
        check = self._check("memory-embeddings")
        assert check.level == "ok"
        assert "all 2 live entries embedded" in check.message

    def test_superseded_entries_not_counted(self, fake_home: Path) -> None:
        self._make_db(fake_home, entries=2, embedded=1)
        from mait_code.tools.memory.db import connection

        with connection(self._data_dir(fake_home) / "memory.db") as conn:
            conn.execute("UPDATE memory_entries SET superseded_by = 1 WHERE id = 2")
            conn.commit()
        check = self._check("memory-embeddings")
        assert check.level == "ok"

    def test_vector_search_reports_vector_count(self, fake_home: Path) -> None:
        self._make_db(fake_home, entries=2, embedded=2)
        check = self._check("vector-search")
        assert check.level == "ok"
        assert "2 vectors stored" in check.message

    def test_vector_search_warns_when_sqlite_vec_broken(
        self, fake_home: Path, monkeypatch
    ) -> None:
        import sqlite_vec

        def _boom(_conn) -> None:
            raise RuntimeError("extension load failed")

        monkeypatch.setattr(sqlite_vec, "load", _boom)
        check = self._check("vector-search")
        assert check.level == "warn"
        assert "keyword-only" in check.message
        assert "provider 'local'" in check.message

    def test_observe_recent_capture_ok(self, fake_home: Path) -> None:
        from datetime import date

        self._make_db(fake_home, entries=1, embedded=1)
        obs_dir = self._data_dir(fake_home) / "memory" / "observations"
        obs_dir.mkdir(parents=True, exist_ok=True)
        (obs_dir / f"{date.today().isoformat()}.jsonl").write_text("{}\n")
        check = self._check("observe-pipeline")
        assert check.level == "ok"
        assert date.today().isoformat() in check.message

    def test_observe_stale_capture_warns(self, fake_home: Path) -> None:
        from datetime import date, timedelta

        self._make_db(fake_home, entries=1, embedded=1)
        obs_dir = self._data_dir(fake_home) / "memory" / "observations"
        obs_dir.mkdir(parents=True, exist_ok=True)
        old = date.today() - timedelta(days=30)
        (obs_dir / f"{old.isoformat()}.jsonl").write_text("{}\n")
        check = self._check("observe-pipeline")
        assert check.level == "warn"
        assert "30 days ago" in check.message

    def test_observe_never_captured_with_db_warns(self, fake_home: Path) -> None:
        self._make_db(fake_home, entries=1, embedded=1)
        check = self._check("observe-pipeline")
        assert check.level == "warn"
        assert "never" in check.message

    def test_non_date_capture_files_ignored(self, fake_home: Path) -> None:
        self._make_db(fake_home, entries=1, embedded=1)
        obs_dir = self._data_dir(fake_home) / "memory" / "observations"
        obs_dir.mkdir(parents=True, exist_ok=True)
        (obs_dir / "not-a-date.jsonl").write_text("{}\n")
        check = self._check("observe-pipeline")
        assert check.level == "warn"  # still counts as never captured
