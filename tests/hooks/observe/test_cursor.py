"""Tests for cursor management."""

from pathlib import Path

from mait_code.hooks.observe.cursor import (
    get_cursor,
    load_cursors,
    record_failure,
    save_cursors,
    set_cursor,
)


def test_load_empty_cursors(data_dir: Path):
    assert load_cursors() == {}


def test_set_and_get_cursor(data_dir: Path):
    set_cursor("/tmp/test.jsonl", 1234)
    assert get_cursor("/tmp/test.jsonl") == 1234


def test_get_cursor_unknown_path(data_dir: Path):
    assert get_cursor("/nonexistent.jsonl") == 0


def test_cursor_persistence(data_dir: Path):
    set_cursor("/tmp/a.jsonl", 100)
    set_cursor("/tmp/b.jsonl", 200)

    cursors = load_cursors()
    assert cursors["/tmp/a.jsonl"]["offset"] == 100
    assert cursors["/tmp/b.jsonl"]["offset"] == 200


def test_corrupt_cursor_file(data_dir: Path):
    path = data_dir / "memory" / "observations" / "cursors.json"
    path.write_text("not valid json{{{")
    assert load_cursors() == {}


def test_record_failure_accumulates(data_dir: Path):
    assert record_failure("/tmp/t.jsonl", 0) == 1
    assert record_failure("/tmp/t.jsonl", 0) == 2
    assert record_failure("/tmp/t.jsonl", 0) == 3
    # A failure must not advance the cursor — the window is re-attempted.
    assert get_cursor("/tmp/t.jsonl") == 0


def test_record_failure_resets_on_new_offset(data_dir: Path):
    record_failure("/tmp/t.jsonl", 0)
    record_failure("/tmp/t.jsonl", 0)
    # A failure at a different offset starts the count over.
    assert record_failure("/tmp/t.jsonl", 500) == 1


def test_set_cursor_clears_failure_state(data_dir: Path):
    record_failure("/tmp/t.jsonl", 0)
    record_failure("/tmp/t.jsonl", 0)
    set_cursor("/tmp/t.jsonl", 500)
    assert load_cursors()["/tmp/t.jsonl"].get("fail_count") is None
    # The next failure starts fresh.
    assert record_failure("/tmp/t.jsonl", 500) == 1


def test_save_cursors_prunes_old_entries(data_dir: Path):
    cursors = {
        "/old.jsonl": {"offset": 10, "updated": "2020-01-01T00:00:00+00:00"},
        "/new.jsonl": {"offset": 20, "updated": "2099-01-01T00:00:00+00:00"},
    }
    save_cursors(cursors)
    loaded = load_cursors()
    assert "/old.jsonl" not in loaded
    assert "/new.jsonl" in loaded
