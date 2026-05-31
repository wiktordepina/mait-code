"""Unit tests for the inbox service layer.

These exercise :mod:`mait_code.tools.inbox.service` directly on a temp
connection — the function-level analogue of the end-to-end CLI tests in
``test_inbox.py``.
"""

import sqlite3

import pytest

from mait_code.tools.inbox import service

from tests.tools.inbox.conftest import TEST_PROJECT


def test_add_and_list_oldest_first(inbox_db: sqlite3.Connection):
    service.add_item(inbox_db, body="first", project=TEST_PROJECT)
    service.add_item(inbox_db, body="second", project=TEST_PROJECT)
    bodies = [i["body"] for i in service.list_items(inbox_db)]
    assert bodies == ["first", "second"]


def test_list_is_global_but_project_filterable(inbox_db: sqlite3.Connection):
    service.add_item(inbox_db, body="a", project="proj-a")
    service.add_item(inbox_db, body="b", project="proj-b")
    assert len(service.list_items(inbox_db)) == 2
    filtered = [i["body"] for i in service.list_items(inbox_db, project="proj-a")]
    assert filtered == ["a"]


def test_add_item_without_project(inbox_db: sqlite3.Connection):
    item_id = service.add_item(inbox_db, body="no project")
    item = service.get_item(inbox_db, item_id)
    assert item is not None
    assert item["project"] is None


def test_count_items(inbox_db: sqlite3.Connection):
    assert service.count_items(inbox_db) == 0
    service.add_item(inbox_db, body="x")
    service.add_item(inbox_db, body="y")
    assert service.count_items(inbox_db) == 2


def test_get_item_missing_returns_none(inbox_db: sqlite3.Connection):
    assert service.get_item(inbox_db, 999) is None


def test_remove_item(inbox_db: sqlite3.Connection):
    item_id = service.add_item(inbox_db, body="gone")
    service.remove_item(inbox_db, item_id)
    assert service.count_items(inbox_db) == 0


def test_remove_missing_raises(inbox_db: sqlite3.Connection):
    with pytest.raises(service.ItemNotFound):
        service.remove_item(inbox_db, 999)
