"""Tests for ``mait-code version`` and adjacent scaffolding."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import mait_code
from mait_code.cli import (
    InstallRecord,
    RecordError,
    app,
    install_record_path,
    mait_code_state_dir,
    read_record,
    write_record,
    xdg_data_home,
)

runner = CliRunner()


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == mait_code.__version__


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    # Typer's no_args_is_help shows help and exits 2 (missing command).
    assert result.exit_code in (0, 2)
    assert "mait-code" in result.stdout.lower() or "mait-code" in result.output.lower()


class TestPaths:
    def test_xdg_data_home_default(self, fake_home: Path) -> None:
        assert xdg_data_home() == fake_home / ".local" / "share"

    def test_xdg_data_home_honours_override(self, monkeypatch, fake_home: Path) -> None:
        custom = fake_home / "custom-data"
        monkeypatch.setenv("XDG_DATA_HOME", str(custom))
        assert xdg_data_home() == custom

    def test_mait_code_state_dir(self, fake_home: Path) -> None:
        assert mait_code_state_dir() == fake_home / ".local" / "share" / "mait-code"

    def test_install_record_path(self, fake_home: Path) -> None:
        expected = fake_home / ".local" / "share" / "mait-code" / "install.json"
        assert install_record_path() == expected


class TestInstallRecord:
    def test_new_stamps_timestamp_and_resolves_source(self, tmp_path: Path) -> None:
        source = tmp_path / "src"
        source.mkdir()
        record = InstallRecord.new(source_dir=source)
        assert record.source_dir == str(source.resolve())
        assert "T" in record.updated_at  # ISO 8601
        # A fresh install has no earlier date, so both timestamps agree.
        assert record.first_installed_at == record.updated_at
        assert record.schema_version == 2

    def test_new_preserves_first_installed_at(self, tmp_path: Path) -> None:
        """``update`` passes the original date so it survives reinstalls."""
        source = tmp_path / "src"
        source.mkdir()
        record = InstallRecord.new(
            source_dir=source,
            first_installed_at="2026-01-01T00:00:00+00:00",
        )
        assert record.first_installed_at == "2026-01-01T00:00:00+00:00"
        assert record.updated_at != record.first_installed_at

    def test_round_trip(self, fake_home: Path) -> None:
        record = InstallRecord(
            source_dir="/some/path",
            first_installed_at="2026-05-27T10:00:00+00:00",
            updated_at="2026-06-01T12:00:00+00:00",
        )
        path = write_record(record)
        assert path.exists()
        loaded = read_record()
        assert loaded == record

    def test_reads_old_record_with_removed_fields(self, fake_home: Path) -> None:
        """Old install records with version/embedding_provider still parse."""
        import json

        record_path = install_record_path()
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(
                {
                    "source_dir": "/old/path",
                    "version": "0.18.0",
                    "embedding_provider": "bedrock",
                    "installed_at": "2026-05-27T10:00:00+00:00",
                    "schema_version": 1,
                }
            )
        )
        loaded = read_record()
        assert loaded.source_dir == "/old/path"
        # v1 backfills both timestamps from the single ``installed_at``.
        assert loaded.first_installed_at == "2026-05-27T10:00:00+00:00"
        assert loaded.updated_at == "2026-05-27T10:00:00+00:00"
        assert loaded.schema_version == 2

    def test_reads_v1_record_without_schema_version(self, fake_home: Path) -> None:
        """A pre-versioning record (no schema_version) is treated as v1."""
        import json

        record_path = install_record_path()
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(
                {
                    "source_dir": "/old/path",
                    "installed_at": "2026-05-27T10:00:00+00:00",
                }
            )
        )
        loaded = read_record()
        assert loaded.first_installed_at == "2026-05-27T10:00:00+00:00"
        assert loaded.updated_at == "2026-05-27T10:00:00+00:00"
        assert loaded.schema_version == 2

    def test_read_missing_raises(self, fake_home: Path) -> None:
        try:
            read_record()
        except RecordError as exc:
            assert "No install record" in str(exc)
        else:
            raise AssertionError("Expected RecordError")

    def test_read_malformed_json_raises(self, fake_home: Path) -> None:
        path = install_record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        try:
            read_record()
        except RecordError as exc:
            assert "not valid JSON" in str(exc)
        else:
            raise AssertionError("Expected RecordError")

    def test_non_object_json_raises(self, fake_home: Path) -> None:
        # Valid JSON that decodes to a list (not an object) is rejected
        # before any field access.
        path = install_record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2, 3]")
        try:
            read_record()
        except RecordError as exc:
            assert "not a JSON object" in str(exc)
        else:
            raise AssertionError("Expected RecordError")

    def test_future_schema_version_raises(self, fake_home: Path) -> None:
        path = install_record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"source_dir":"/","version":"x","embedding_provider":"local",'
            '"installed_at":"2026-05-27T00:00:00+00:00","schema_version":999}'
        )
        try:
            read_record()
        except RecordError as exc:
            assert "schema_version=999" in str(exc)
        else:
            raise AssertionError("Expected RecordError")

    def test_missing_fields_raises(self, fake_home: Path) -> None:
        path = install_record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"source_dir":"/"}')
        try:
            read_record()
        except RecordError as exc:
            assert "missing required fields" in str(exc)
        else:
            raise AssertionError("Expected RecordError")
