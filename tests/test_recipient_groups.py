"""Tests for named local recipient groups (app.recipients.groups +
app.database.repositories.RecipientGroupRepository). Mirrors
tests/test_presets.py's structure for the analogous message-preset
feature.
"""
from __future__ import annotations

import pytest

from app.database.database import Database
from app.database.repositories import RecipientGroupRepository
from app.recipients import groups
from app.recipients.groups import RecipientGroupError


def test_save_and_load_round_trips_text_and_names(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = RecipientGroupRepository(db)
        saved = groups.save_group(repo, "Customers", "@ivan_test\n@maria_test", {"username:ivan_test": "Ivan"})

        assert saved.id is not None
        assert saved.name == "Customers"

        loaded = groups.load_group(saved)
        assert loaded.recipients_text == "@ivan_test\n@maria_test"
        assert loaded.name_overrides == {"username:ivan_test": "Ivan"}
    finally:
        db.close()


def test_save_without_names_round_trips_empty_dict(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = RecipientGroupRepository(db)
        saved = groups.save_group(repo, "Test accounts", "@ivan_test", {})
        loaded = groups.load_group(saved)
        assert loaded.name_overrides == {}
    finally:
        db.close()


def test_blank_name_falls_back_to_untitled(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = RecipientGroupRepository(db)
        saved = groups.save_group(repo, "   ", "@ivan_test", {})
        assert saved.name == "Без названия"
    finally:
        db.close()


def test_list_groups_returns_every_saved_group(tmp_path):
    # Same SQLite datetime('now') second-resolution limitation as
    # test_presets.py::test_list_presets_returns_every_saved_preset --
    # set-equality of ids only, not order.
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = RecipientGroupRepository(db)
        first = groups.save_group(repo, "First", "@a", {})
        second = groups.save_group(repo, "Second", "@b", {})

        ids = {g.id for g in groups.list_groups(repo)}
        assert ids == {first.id, second.id}
    finally:
        db.close()


def test_rename_group(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = RecipientGroupRepository(db)
        saved = groups.save_group(repo, "Old name", "@a", {})

        groups.rename_group(repo, saved.id, "New name")

        reloaded = repo.get_by_id(saved.id)
        assert reloaded.name == "New name"
    finally:
        db.close()


def test_rename_to_blank_falls_back_to_untitled(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = RecipientGroupRepository(db)
        saved = groups.save_group(repo, "Old name", "@a", {})

        groups.rename_group(repo, saved.id, "   ")

        reloaded = repo.get_by_id(saved.id)
        assert reloaded.name == "Без названия"
    finally:
        db.close()


def test_delete_group(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = RecipientGroupRepository(db)
        saved = groups.save_group(repo, "Doomed", "@a", {})

        groups.delete_group(repo, saved.id)

        assert repo.get_by_id(saved.id) is None
    finally:
        db.close()


def test_load_raises_group_error_for_corrupted_name_overrides_json(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = RecipientGroupRepository(db)
        saved = repo.create("Corrupted", "@a", "not valid json{{{")

        with pytest.raises(RecipientGroupError):
            groups.load_group(saved)
    finally:
        db.close()


def test_groups_persist_across_a_restart(tmp_path):
    db_path = tmp_path / "app.db"
    db1 = Database(db_path=db_path)
    try:
        repo1 = RecipientGroupRepository(db1)
        groups.save_group(repo1, "Persisted", "@a", {})
    finally:
        db1.close()

    db2 = Database(db_path=db_path)
    try:
        repo2 = RecipientGroupRepository(db2)
        names = [g.name for g in groups.list_groups(repo2)]
        assert "Persisted" in names
    finally:
        db2.close()
