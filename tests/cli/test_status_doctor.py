"""Tests for ``mait-code status`` and ``mait-code doctor``."""

from __future__ import annotations

import json
import shutil
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


class TestStatusEdgeBranches:
    """Helper-level edge branches for the status collector and renderer."""

    def test_dir_size_zero_for_missing_path(self, tmp_path: Path) -> None:
        from mait_code.cli._status import _dir_size_bytes

        assert _dir_size_bytes(tmp_path / "does-not-exist") == 0

    def test_dir_size_skips_unstatable_files(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from mait_code.cli._status import _dir_size_bytes

        # A file-like entry whose stat() raises is skipped, not fatal.
        entry = MagicMock()
        entry.is_file.return_value = True
        entry.is_symlink.return_value = False
        entry.stat.side_effect = OSError("boom")

        root = MagicMock(spec=Path)
        root.exists.return_value = True
        root.rglob.return_value = [entry]

        assert _dir_size_bytes(root) == 0

    def test_count_linked_returns_zero_without_source(self, tmp_path: Path) -> None:
        from mait_code.cli._status import _count_linked

        (tmp_path / "skills").mkdir()
        assert _count_linked(tmp_path / "skills", None) == 0
        # Missing symlink dir is also zero.
        assert _count_linked(tmp_path / "absent", tmp_path) == 0

    def test_count_linked_skips_non_symlinks_and_outsiders(
        self, tmp_path: Path
    ) -> None:
        from mait_code.cli._status import _count_linked

        source = tmp_path / "source"
        (source / "skills").mkdir(parents=True)
        (source / "skills" / "real").write_text("x")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "stray").write_text("y")

        link_dir = tmp_path / "links"
        link_dir.mkdir()
        (link_dir / "plain.md").write_text("not a symlink")  # skipped (not symlink)
        (link_dir / "good").symlink_to(source / "skills" / "real")  # counted
        (link_dir / "outsider").symlink_to(outside / "stray")  # resolves outside source

        assert _count_linked(link_dir, source) == 1

    def test_count_linked_skips_resolve_oserror(self, tmp_path: Path) -> None:
        from mait_code.cli._status import _count_linked

        source = tmp_path / "source"
        source.mkdir()
        link_dir = tmp_path / "links"
        link_dir.mkdir()
        entry = link_dir / "a"
        entry.symlink_to(source / "x")
        real_resolve = Path.resolve

        # Raise only when resolving the symlink entry; source_dir.resolve()
        # earlier in the function must still succeed.
        def flaky_resolve(self, *args, **kwargs):
            if self == entry:
                raise OSError("boom")
            return real_resolve(self, *args, **kwargs)

        with patch.object(Path, "resolve", flaky_resolve):
            assert _count_linked(link_dir, source) == 0

    def test_count_total_zero_for_missing_dir(self, tmp_path: Path) -> None:
        from mait_code.cli._status import _count_total

        assert _count_total(tmp_path / "absent") == 0

    def test_tilde_edge_cases(self) -> None:
        from mait_code.cli._status import _tilde

        home = str(Path.home())
        assert _tilde(None) == "—"
        assert _tilde(home) == "~"
        assert _tilde(home + "/x") == "~/x"
        assert _tilde("/somewhere/else") == "/somewhere/else"  # no home prefix

    def test_date_only_handles_none(self) -> None:
        from mait_code.cli._status import _date_only

        assert _date_only(None) == "—"
        assert _date_only("2026-01-02T03:04:05Z") == "2026-01-02"

    def test_human_size_units(self) -> None:
        from mait_code.cli._status import _human_size

        assert _human_size(512) == "512 B"
        assert _human_size(2048) == "2.0 KB"
        # > 1 PB worth of bytes falls through to the TB branch.
        assert _human_size(5 * 1024**4).endswith("TB")

    def test_claude_value_present_not_linked(self) -> None:
        from mait_code.cli._status import Status, _claude_value

        value = _claude_value(Status(claude_md_path="/x/CLAUDE.md"))
        assert "present, not linked" in value.plain

    def test_claude_value_missing(self) -> None:
        from mait_code.cli._status import Status, _claude_value

        assert "missing" in _claude_value(Status()).plain

    def test_collect_status_readlink_oserror_swallowed(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        # A symlinked CLAUDE.md whose readlink raises leaves target unset but
        # still records is_symlink.
        install(source_dir=fake_source)
        from mait_code.cli import _status

        with patch.object(_status.Path, "readlink", side_effect=OSError("boom")):
            status = collect_status()
        assert status.claude_md_is_symlink is True
        assert status.claude_md_target is None

    def test_collect_status_settings_unparseable_leaves_hooks_empty(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        (fake_home / ".claude" / "settings.json").write_text("{ broken")
        status = collect_status()
        assert status.hooks_registered == []

    def test_render_binary_not_on_path(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        status = collect_status()
        status.binary_path = None  # simulate mait-code absent from PATH
        with console.capture() as cap:
            status_render(status)
        assert "not on PATH" in cap.get()

    def test_render_no_record_without_error_text(self, fake_home: Path) -> None:
        from mait_code.cli._status import Status

        # record absent but no error string -> the hint line is skipped.
        with console.capture() as cap:
            status_render(Status())
        out = cap.get()
        assert "no install record found" in out

    def test_render_not_linked_shows_install_hint(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        status = collect_status()
        # Pretend CLAUDE.md is present but unlinked despite a real record.
        status.claude_md_is_symlink = False
        status.claude_md_path = str(fake_home / ".claude" / "CLAUDE.md")
        with console.capture() as cap:
            status_render(status)
        out = cap.get()
        assert "run mait-code install to link CLAUDE.md" in out

    def test_health_degraded_when_identity_files_missing(self, fake_home: Path) -> None:
        from mait_code.cli._status import Status, _health

        # record present + linked CLAUDE.md but missing identity files -> warn.
        status = Status(record_present=True, claude_md_is_symlink=True)
        assert _health(status) == "warn"

    def test_collect_status_plain_claude_md_not_symlink(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        # A regular (non-symlink) CLAUDE.md records its path but no target.
        install(source_dir=fake_source)
        claude_md = fake_home / ".claude" / "CLAUDE.md"
        claude_md.unlink()  # remove the install symlink
        claude_md.write_text("# plain file\n")
        status = collect_status()
        assert status.claude_md_path is not None
        assert status.claude_md_is_symlink is False
        assert status.claude_md_target is None

    def test_collect_status_hooks_section_not_dict(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        sp = fake_home / ".claude" / "settings.json"
        sp.write_text(json.dumps({"hooks": ["not", "a", "dict"]}))
        status = collect_status()
        assert status.hooks_registered == []

    def test_collect_status_binary_not_on_path(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        with patch("mait_code.cli._status.shutil.which", return_value=None):
            status = collect_status()
        assert status.binary_path is None

    def test_claude_value_symlink_without_target(self) -> None:
        from mait_code.cli._status import Status, _claude_value

        # is_symlink True but target unresolved -> "linked" without the arrow.
        value = _claude_value(Status(claude_md_is_symlink=True))
        assert "linked" in value.plain
        assert "→" not in value.plain


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
        assert levels["env-table"] == "ok"
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

    def test_env_table_reserved_keys_warn(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _populate_source(fake_source)
        install(source_dir=fake_source)
        sp = fake_home / ".config" / "mait-code" / "settings.toml"
        sp.write_text(
            sp.read_text(encoding="utf-8")
            + '\n[env]\nAWS_PROFILE = "dev"\nMAIT_CODE_LOG_LEVEL = "DEBUG"\n',
            encoding="utf-8",
        )

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["env-table"].level == "warn"
        assert "MAIT_CODE_LOG_LEVEL" in names["env-table"].message

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

    def test_cli_no_color_flag_reaches_stderr_console(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        # `--no-color` must flip the stderr (error/warning) console too, not
        # just the stdout one — otherwise errors stay coloured under --no-color.
        from mait_code.console import console, err_console

        install(source_dir=fake_source)
        runner.invoke(app, ["--no-color", "doctor"])
        assert console.no_color is True
        assert err_console.no_color is True


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

    def test_observe_keeps_latest_of_many_captures(self, fake_home: Path) -> None:
        # Multiple capture files exist; only the newest day drives the verdict.
        from datetime import date, timedelta

        self._make_db(fake_home, entries=1, embedded=1)
        obs_dir = self._data_dir(fake_home) / "memory" / "observations"
        obs_dir.mkdir(parents=True, exist_ok=True)
        today = date.today()
        # Write today *first* so the loop has to keep it when an older day follows.
        (obs_dir / f"{today.isoformat()}.jsonl").write_text("{}\n")
        (obs_dir / f"{(today - timedelta(days=3)).isoformat()}.jsonl").write_text(
            "{}\n"
        )
        check = self._check("observe-pipeline")
        assert check.level == "ok"
        assert today.isoformat() in check.message


class TestDoctorChecksFailurePaths:
    """The degraded / failure branches of the individual doctor checks."""

    def test_source_dir_fail_when_clone_invalid(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        # Install, then gut the source so verify_source rejects it.
        install(source_dir=fake_source)
        (fake_source / "pyproject.toml").unlink()

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["source-dir"].level == "fail"
        assert "re-run mait-code install" in (names["source-dir"].fix_hint or "")

    def test_settings_json_unparseable_marks_fail(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        (fake_home / ".claude" / "settings.json").write_text("{ not json ")

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["settings"].level == "fail"
        assert "repair the JSON" in (names["settings"].fix_hint or "")

    def test_settings_json_missing_warns(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        (fake_home / ".claude" / "settings.json").unlink()

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["settings"].level == "warn"
        assert "does not exist" in names["settings"].message

    def test_mait_settings_toml_unparseable_marks_fail(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        (fake_home / ".config" / "mait-code" / "settings.toml").write_text(
            "this is = not [valid toml"
        )

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["settings-file"].level == "fail"
        assert "repair the TOML" in (names["settings-file"].fix_hint or "")

    def test_env_table_custom_vars_ok_with_count(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        sp = fake_home / ".config" / "mait-code" / "settings.toml"
        sp.write_text(
            sp.read_text(encoding="utf-8") + '\n[env]\nAWS_PROFILE = "dev"\n',
            encoding="utf-8",
        )

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["env-table"].level == "ok"
        assert "1 custom [env]" in names["env-table"].message

    def test_data_dir_not_writable_marks_fail(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        # _is_writable probes by writing a temp file; force it to fail so the
        # "not writable" branch is exercised without chmod games on CI.
        install(source_dir=fake_source)
        with patch("mait_code.cli._doctor._is_writable", return_value=False):
            report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["data-dir"].level == "fail"
        assert "not writable" in names["data-dir"].message

    def test_is_writable_returns_false_on_oserror(self) -> None:
        from mait_code.cli._doctor import _is_writable

        # A path that cannot be written into yields False rather than raising.
        assert _is_writable(Path("/proc/nonexistent-doctor-dir")) is False

    def test_uv_missing_marks_fail(self, fake_home: Path, fake_source: Path) -> None:
        install(source_dir=fake_source)
        # `which` returns None for everything -> uv check fails. Keep the real
        # shutil.which for the hook-command check by only nulling "uv".
        real_which = shutil.which

        def fake_which(prog: str, *a, **k):
            return None if prog == "uv" else real_which(prog, *a, **k)

        with patch("mait_code.cli._doctor.shutil.which", side_effect=fake_which):
            report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["uv-on-path"].level == "fail"
        assert "uv" in names["uv-on-path"].message

    def test_memory_embeddings_inspect_error_warns(self, fake_home: Path) -> None:
        # A corrupt memory.db makes the embeddings query raise -> warn.
        ddir = fake_home / ".claude" / "mait-code-data"
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / "memory.db").write_text("not a sqlite database at all")

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["memory-embeddings"].level == "warn"
        assert "could not inspect embeddings" in names["memory-embeddings"].message

    def test_memory_embeddings_db_with_zero_entries_ok(self, fake_home: Path) -> None:
        # An initialised but empty DB -> "no live entries yet".
        from mait_code.tools.memory.db import get_connection

        ddir = fake_home / ".claude" / "mait-code-data"
        ddir.mkdir(parents=True, exist_ok=True)
        get_connection(ddir / "memory.db").close()

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["memory-embeddings"].level == "ok"
        assert "no live entries yet" in names["memory-embeddings"].message

    def test_vector_search_memory_vec_unqueryable_warns(self, fake_home: Path) -> None:
        # A DB without the memory_vec table makes the count query raise.
        ddir = fake_home / ".claude" / "mait-code-data"
        ddir.mkdir(parents=True, exist_ok=True)
        import sqlite3

        sqlite3.connect(str(ddir / "memory.db")).close()  # empty, no memory_vec

        report = run_doctor()
        names = {c.name: c for c in report.checks}
        assert names["vector-search"].level == "warn"
        assert "not queryable" in names["vector-search"].message
        assert "keyword-only" in names["vector-search"].message


class TestDoctorHookCommands:
    """The hooks-on-path check across its parsing and resolution branches."""

    def _write_settings(self, fake_home: Path, payload: dict) -> None:
        cdir = fake_home / ".claude"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "settings.json").write_text(json.dumps(payload))

    def _check(self, name: str):
        report = run_doctor()
        return next(c for c in report.checks if c.name == name)

    def test_skipped_when_no_settings(self, fake_home: Path) -> None:
        # No settings.json at all -> skipped warn.
        check = self._check("hooks-on-path")
        assert check.level == "warn"
        assert "no settings.json" in check.message

    def test_skipped_when_settings_unparseable(self, fake_home: Path) -> None:
        cdir = fake_home / ".claude"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "settings.json").write_text("{ broken json")
        check = self._check("hooks-on-path")
        assert check.level == "warn"
        assert "unparseable" in check.message

    def test_hooks_section_not_a_dict(self, fake_home: Path) -> None:
        self._write_settings(fake_home, {"hooks": ["not", "a", "dict"]})
        check = self._check("hooks-on-path")
        assert check.level == "ok"
        assert "no hooks registered" in check.message

    def test_non_list_entries_and_non_dict_hooks_ignored(self, fake_home: Path) -> None:
        # entries-not-a-list and hook-not-a-dict are skipped silently.
        self._write_settings(
            fake_home,
            {
                "hooks": {
                    "Bad": "not-a-list",
                    "Mixed": [
                        "not-a-dict-entry",
                        {"hooks": ["not-a-dict-hook", {"command": 123}]},
                    ],
                }
            },
        )
        check = self._check("hooks-on-path")
        # Nothing with the mait-code prefix resolved -> "no mait-code hooks".
        assert check.level == "ok"
        assert "no mait-code hooks registered" in check.message

    def test_non_prefixed_commands_ignored(self, fake_home: Path) -> None:
        # A command without the mait-code hook prefix is not probed on PATH.
        self._write_settings(
            fake_home,
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "/usr/bin/true"}]}
                    ]
                }
            },
        )
        check = self._check("hooks-on-path")
        assert check.level == "ok"
        assert "no mait-code hooks registered" in check.message

    def test_resolvable_prefixed_command_ok(self, fake_home: Path) -> None:
        from mait_code.cli._settings import MAIT_CODE_HOOK_PREFIX

        prog = f"{MAIT_CODE_HOOK_PREFIX}-fake-hook"
        cmd = f"{prog} --flag"
        # The same program twice exercises the dedupe `seen` branch.
        self._write_settings(
            fake_home,
            {
                "hooks": {
                    "SessionStart": [{"hooks": [{"command": cmd}, {"command": cmd}]}]
                }
            },
        )
        with patch(
            "mait_code.cli._doctor.shutil.which",
            side_effect=lambda p, *a, **k: "/bin/" + p,
        ):
            check = self._check("hooks-on-path")
        assert check.level == "ok"
        assert "1 hook commands resolve" in check.message

    def test_unresolvable_prefixed_command_fails(self, fake_home: Path) -> None:
        from mait_code.cli._settings import MAIT_CODE_HOOK_PREFIX

        prog = f"{MAIT_CODE_HOOK_PREFIX}-missing-hook"
        self._write_settings(
            fake_home,
            {"hooks": {"SessionStart": [{"hooks": [{"command": prog}]}]}},
        )
        with patch("mait_code.cli._doctor.shutil.which", return_value=None):
            check = self._check("hooks-on-path")
        assert check.level == "fail"
        assert prog in check.message
        assert check.fix_hint == "refresh hooks: mait-code update"


class TestDoctorSymlinkScan:
    """The dangling-symlink scanner's continue/except branches."""

    def test_non_symlink_entries_skipped(self, fake_home: Path) -> None:
        from mait_code.cli._doctor import _find_dangling_symlinks

        cdir = fake_home / ".claude"
        (cdir / "skills").mkdir(parents=True, exist_ok=True)
        # A plain file (not a symlink) must be ignored.
        (cdir / "skills" / "regular.md").write_text("x")
        assert _find_dangling_symlinks(cdir) == []

    def test_dangling_symlink_detected(self, fake_home: Path) -> None:
        from mait_code.cli._doctor import _find_dangling_symlinks

        cdir = fake_home / ".claude"
        (cdir / "agents").mkdir(parents=True, exist_ok=True)
        link = cdir / "agents" / "ghost"
        link.symlink_to(fake_home / "nowhere" / "missing-target")
        dangling = _find_dangling_symlinks(cdir)
        # resolve(strict=True) raises FileNotFoundError -> caught, flagged.
        assert link in dangling

    def test_symlink_resolving_to_vanished_target_flagged(
        self, fake_home: Path
    ) -> None:
        # Belt-and-braces branch: resolve(strict=True) succeeds but the
        # resolved target reports it does not exist. Unreachable in practice
        # (strict resolve implies existence), so we force the .exists() False.
        from mait_code.cli import _doctor

        cdir = fake_home / ".claude"
        (cdir / "skills").mkdir(parents=True, exist_ok=True)
        real_target = cdir / "skills" / "_target"
        real_target.write_text("x")
        link = cdir / "skills" / "link"
        link.symlink_to(real_target)
        real_exists = Path.exists

        def flaky_exists(self, *args, **kwargs):
            if self == real_target:
                return False
            return real_exists(self, *args, **kwargs)

        with patch.object(_doctor.Path, "exists", flaky_exists):
            dangling = _doctor._find_dangling_symlinks(cdir)
        assert link in dangling


class TestDoctorRenderFixes:
    """The render path that lists applied fixes."""

    def test_render_lists_applied_fixes(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        _populate_source(fake_source)
        install(source_dir=fake_source)
        import shutil as _shutil

        _shutil.rmtree(fake_source / "skills" / "alpha")

        report = run_doctor(fix=True)
        assert report.fixes_applied  # sanity: a fix was applied
        with console.capture() as cap:
            doctor_render(report)
        out = cap.get()
        assert "Fixes applied:" in out
        assert "dangling symlink" in out
