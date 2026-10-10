"""The embedding record and the ``vectors_usable`` guard over search, dedup and writes."""

import logging
import sqlite3
from unittest.mock import patch

import pytest

from mait_code.tools.memory import embeddings
from mait_code.tools.memory.embeddings import (
    EmbeddingRecord,
    configured_record,
    read_embedding_record,
    serialize_f32,
    vectors_usable,
    verify_and_adopt,
    write_embedding_record,
)

OTHER_MODEL = EmbeddingRecord("local", "some/other-model", 768)


@pytest.fixture(autouse=True)
def _fresh_warnings(monkeypatch):
    """Each test sees the once-per-process warning afresh, through caplog.

    setup_logging() (run by earlier tests) sets propagate=False on the
    "mait_code" logger; caplog captures at root, so restore propagation.
    """
    monkeypatch.setattr(embeddings, "_warned", set())
    monkeypatch.setattr(logging.getLogger("mait_code"), "propagate", True)


def _vector(conn: sqlite3.Connection, entry_id: int, vec: list[float]) -> None:
    conn.execute(
        "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
        (entry_id, serialize_f32(vec)),
    )


def _embed_all(conn: sqlite3.Connection, record: EmbeddingRecord | None) -> None:
    """Give every entry a vector, recorded as built by *record* (None: unknown)."""
    for (entry_id,) in conn.execute("SELECT id FROM memory_entries").fetchall():
        _vector(conn, entry_id, [0.1] * 768)
    if record is not None:
        write_embedding_record(conn, record)
    conn.commit()


class TestRecord:
    def test_no_record_reads_none(self, memory_db):
        assert read_embedding_record(memory_db) is None

    def test_round_trip(self, memory_db):
        write_embedding_record(memory_db, OTHER_MODEL)
        assert read_embedding_record(memory_db) == OTHER_MODEL

    def test_defaults_to_configured(self, memory_db):
        write_embedding_record(memory_db)
        assert read_embedding_record(memory_db) == configured_record()

    def test_defaults_to_the_loaded_provider_over_settings(
        self, memory_db, monkeypatch
    ):
        """A provider loaded before a settings change made the vectors."""

        class Loaded(embeddings.EmbeddingProvider):
            provider_name = "local"
            model_name = "loaded/model"  # type: ignore[assignment]
            dimension = 768  # type: ignore[assignment]

            def embed(self, texts):
                return [[0.1] * 768 for _ in texts]

        monkeypatch.setattr(embeddings, "_provider", Loaded())
        write_embedding_record(memory_db)
        assert read_embedding_record(memory_db) == EmbeddingRecord(
            "local", "loaded/model", 768
        )

    def test_missing_table_reads_none(self, memory_db):
        memory_db.execute("DROP TABLE memory_meta")
        assert read_embedding_record(memory_db) is None

    def test_configured_record_reads_live(self, monkeypatch):
        """Settings changed after import are seen — no import-time constant."""
        monkeypatch.setenv("MAIT_CODE_EMBEDDING_PROVIDER", "bedrock")
        monkeypatch.setenv("MAIT_CODE_BEDROCK_MODEL_ID", "amazon.titan-embed-text-v1")
        assert configured_record() == EmbeddingRecord(
            "bedrock", "amazon.titan-embed-text-v1", 1536
        )


class TestVectorsUsable:
    def test_empty(self, memory_db):
        status = vectors_usable(memory_db)
        assert (status.usable, status.state) == (True, "empty")

    def test_empty_with_stale_record_is_usable(self, memory_db):
        """Nothing stored means nothing to disagree with."""
        write_embedding_record(memory_db, OTHER_MODEL)
        status = vectors_usable(memory_db)
        assert (status.usable, status.state) == (True, "empty")

    def test_empty_with_mismatched_declared_width(self, memory_db):
        from mait_code.tools.memory.cli import _recreate_vec_table

        _recreate_vec_table(memory_db, 256)
        status = vectors_usable(memory_db)
        assert (status.usable, status.state) == (False, "dimension")
        assert "256d" in status.reason

    def test_unknown_is_permissive(self, populated_db):
        _embed_all(populated_db, None)
        status = vectors_usable(populated_db)
        assert (status.usable, status.state) == (True, "unknown")
        assert status.recorded is None

    def test_match(self, populated_db):
        _embed_all(populated_db, configured_record())
        status = vectors_usable(populated_db)
        assert (status.usable, status.state) == (True, "match")

    def test_same_width_model_mismatch(self, populated_db):
        _embed_all(populated_db, OTHER_MODEL)
        status = vectors_usable(populated_db)
        assert (status.usable, status.state) == (False, "model")
        assert "some/other-model" in status.reason
        assert "nomic-ai/nomic-embed-text-v1.5" in status.reason

    def test_provider_mismatch(self, populated_db):
        _embed_all(
            populated_db,
            EmbeddingRecord("bedrock", "nomic-ai/nomic-embed-text-v1.5", 768),
        )
        assert vectors_usable(populated_db).state == "model"

    def test_stored_width_mismatch(self, populated_db):
        from mait_code.tools.memory.cli import _recreate_vec_table

        _recreate_vec_table(populated_db, 1024)
        _vector(populated_db, 1, [0.1] * 1024)
        populated_db.commit()
        status = vectors_usable(populated_db)
        assert (status.usable, status.state) == (False, "dimension")

    def test_absent_table(self, memory_db):
        memory_db.execute("DROP TABLE memory_vec")
        status = vectors_usable(memory_db)
        assert (status.usable, status.state) == (False, "absent")


class TestSearch:
    def test_mismatch_returns_nothing_without_embedding(self, populated_db, caplog):
        from mait_code.tools.memory.search import vector_search_entries

        _embed_all(populated_db, OTHER_MODEL)
        with (
            patch("mait_code.tools.memory.search.embed_text") as embed,
            caplog.at_level(logging.WARNING),
        ):
            assert vector_search_entries(populated_db, "dark mode") == []
            assert vector_search_entries(populated_db, "dark mode") == []
        embed.assert_not_called()
        warnings = [r for r in caplog.records if "keyword-only" in r.getMessage()]
        assert len(warnings) == 1  # once per process, not per query

    def test_hybrid_falls_back_to_keyword(self, populated_db):
        from mait_code.tools.memory.search import hybrid_search

        _embed_all(populated_db, OTHER_MODEL)
        with patch("mait_code.tools.memory.search.embed_text") as embed:
            results = hybrid_search(populated_db, "dark mode")
        embed.assert_not_called()
        assert any("dark mode" in r["content"] for r in results)
        assert all(r.get("similarity") is None for r in results)

    def test_unknown_still_searches(self, populated_db):
        from mait_code.tools.memory.search import vector_search_entries

        _embed_all(populated_db, None)
        with patch(
            "mait_code.tools.memory.search.embed_text", return_value=[0.1] * 768
        ):
            assert vector_search_entries(populated_db, "dark mode")


class TestDedup:
    def test_mismatch_yields_no_candidates(self, populated_db):
        from mait_code.tools.memory.writer import _vector_candidates

        _embed_all(populated_db, OTHER_MODEL)
        with patch("mait_code.tools.memory.writer.embed_text") as embed:
            assert _vector_candidates(populated_db, "dark mode", "preference") == []
        embed.assert_not_called()

    def test_unknown_still_finds_candidates(self, populated_db):
        from mait_code.tools.memory.writer import _vector_candidates

        _embed_all(populated_db, None)
        with patch(
            "mait_code.tools.memory.writer.embed_text", return_value=[0.1] * 768
        ):
            assert _vector_candidates(populated_db, "dark mode", "preference")


class TestWrite:
    @staticmethod
    def _new_entry(conn) -> int:
        cur = conn.execute("INSERT INTO memory_entries (content) VALUES ('fresh')")
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    @staticmethod
    def _has_vector(conn, entry_id: int) -> bool:
        row = conn.execute(
            "SELECT 1 FROM memory_vec WHERE rowid = ?", (entry_id,)
        ).fetchone()
        return row is not None

    def test_mismatch_skips_insert(self, populated_db, caplog):
        from mait_code.tools.memory.writer import _store_embedding

        _embed_all(populated_db, OTHER_MODEL)
        entry_id = self._new_entry(populated_db)
        with (
            patch("mait_code.tools.memory.writer.embed_text") as embed,
            caplog.at_level(logging.WARNING),
        ):
            _store_embedding(populated_db, entry_id, "fresh")
        embed.assert_not_called()
        assert not self._has_vector(populated_db, entry_id)
        assert "stored without a vector" in caplog.text

    def test_first_vector_into_empty_table_records(self, memory_db):
        from mait_code.tools.memory.writer import _store_embedding

        write_embedding_record(memory_db, OTHER_MODEL)  # stale, table empty
        memory_db.commit()
        entry_id = self._new_entry(memory_db)
        with patch(
            "mait_code.tools.memory.writer.embed_text", return_value=[0.1] * 768
        ):
            _store_embedding(memory_db, entry_id, "fresh")
        assert self._has_vector(memory_db, entry_id)
        assert read_embedding_record(memory_db) == configured_record()

    def test_unknown_inserts_without_recording(self, populated_db):
        from mait_code.tools.memory.writer import _store_embedding

        _embed_all(populated_db, None)
        entry_id = self._new_entry(populated_db)
        with patch(
            "mait_code.tools.memory.writer.embed_text", return_value=[0.1] * 768
        ):
            _store_embedding(populated_db, entry_id, "fresh")
        assert self._has_vector(populated_db, entry_id)
        assert read_embedding_record(populated_db) is None


class TestVerifyAndAdopt:
    @staticmethod
    def _patch_embed(fn):
        return patch(
            "mait_code.tools.memory.embeddings.embed_texts",
            side_effect=lambda texts, prefix: [fn(t) for t in texts],
        )

    def test_adopts_when_sample_reproduces(self, populated_db):
        _embed_all(populated_db, None)
        with self._patch_embed(lambda _t: [0.1] * 768):
            assert verify_and_adopt(populated_db) == "adopted"
        assert read_embedding_record(populated_db) == configured_record()

    def test_differs_writes_nothing(self, populated_db):
        _embed_all(populated_db, None)
        with self._patch_embed(lambda _t: [1.0, 0.0] * 384):
            assert verify_and_adopt(populated_db) == "differs"
        assert read_embedding_record(populated_db) is None

    def test_unavailable(self, populated_db):
        _embed_all(populated_db, None)
        with patch("mait_code.tools.memory.embeddings.embed_texts", return_value=None):
            assert verify_and_adopt(populated_db) == "unavailable"

    def test_empty_table_differs(self, memory_db):
        assert verify_and_adopt(memory_db) == "differs"

    def test_sample_catches_a_mid_life_model_switch(self, populated_db):
        """Old vectors first, new ones last: both ends are always sampled."""
        ids = [r[0] for r in populated_db.execute("SELECT id FROM memory_entries")]
        old, new = [1.0, 0.0] * 384, [0.0, 1.0] * 384
        for entry_id in ids:
            _vector(populated_db, entry_id, new if entry_id == ids[-1] else old)
        populated_db.commit()
        # The configured model reproduces the old vectors; only the newest
        # entry disagrees, and the spread sample still reaches it.
        with self._patch_embed(lambda _t: old):
            assert verify_and_adopt(populated_db, sample=2) == "differs"
