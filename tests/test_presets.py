"""Tests for named message presets (app.campaign.presets +
app.database.repositories.PresetRepository). Covers the entity/attachment
serialization round-trip, missing-attachment handling on load, corrupted
data, rename/delete, and restart persistence.
"""
from __future__ import annotations

import pytest
from telethon.tl.types import MessageEntityBold, MessageEntityPre, MessageEntitySpoiler, MessageEntityTextUrl

from app.campaign import presets
from app.campaign.presets import PresetError
from app.database.database import Database
from app.database.repositories import PresetRepository


def test_save_and_load_round_trips_text_and_entities(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        entities = [
            MessageEntityBold(offset=0, length=5),
            MessageEntityTextUrl(offset=6, length=4, url="https://example.com"),
        ]
        saved = presets.save_preset(repo, "Welcome message", "Hello link here", entities, [])

        assert saved.id is not None
        assert saved.name == "Welcome message"

        loaded = presets.load_preset(saved)
        assert loaded.message_text == "Hello link here"
        assert len(loaded.message_entities) == 2
        assert isinstance(loaded.message_entities[0], MessageEntityBold)
        assert loaded.message_entities[0].offset == 0
        assert loaded.message_entities[0].length == 5
        assert isinstance(loaded.message_entities[1], MessageEntityTextUrl)
        assert loaded.message_entities[1].url == "https://example.com"
    finally:
        db.close()


def test_round_trips_every_entity_type_the_editor_can_produce(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        entities = [
            MessageEntityPre(offset=0, length=4, language=""),
            MessageEntitySpoiler(offset=5, length=6),
        ]
        saved = presets.save_preset(repo, "Formatted", "code secret", entities, [])
        loaded = presets.load_preset(saved)

        assert isinstance(loaded.message_entities[0], MessageEntityPre)
        assert loaded.message_entities[0].language == ""
        assert isinstance(loaded.message_entities[1], MessageEntitySpoiler)
    finally:
        db.close()


def test_save_and_load_round_trips_existing_attachments(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        attachment = tmp_path / "photo.jpg"
        attachment.write_bytes(b"x")

        saved = presets.save_preset(repo, "With photo", "See attached", [], [attachment])
        loaded = presets.load_preset(saved)

        assert loaded.attachment_paths == [attachment]
        assert loaded.missing_attachment_names == []
    finally:
        db.close()


def test_load_reports_missing_attachments_without_including_them(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        present = tmp_path / "present.jpg"
        present.write_bytes(b"x")
        gone = tmp_path / "gone.jpg"
        gone.write_bytes(b"x")

        saved = presets.save_preset(repo, "Mixed", "text", [], [present, gone])
        gone.unlink()  # moved/deleted after saving, before loading

        loaded = presets.load_preset(saved)

        assert loaded.attachment_paths == [present]
        assert loaded.missing_attachment_names == ["gone.jpg"]
    finally:
        db.close()


def test_save_persists_the_interval_when_given(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        saved = presets.save_preset(repo, "Timed", "text", [], [], min_delay_seconds=45, max_delay_seconds=90)
        loaded = presets.load_preset(saved)

        assert loaded.min_delay_seconds == 45
        assert loaded.max_delay_seconds == 90
    finally:
        db.close()


def test_save_without_an_interval_leaves_it_none(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        saved = presets.save_preset(repo, "No interval", "text", [], [])
        loaded = presets.load_preset(saved)

        assert loaded.min_delay_seconds is None
        assert loaded.max_delay_seconds is None
    finally:
        db.close()


def test_blank_name_falls_back_to_untitled(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        saved = presets.save_preset(repo, "   ", "text", [], [])
        assert saved.name == "Без названия"
    finally:
        db.close()


def test_list_presets_returns_every_saved_preset(tmp_path):
    # created_at has only second-level resolution (SQLite datetime('now')),
    # so two saves within the same second can't be reliably distinguished
    # by insertion order -- same limitation as
    # test_report_library.py::test_list_reports_orders_newest_first, same
    # pragmatic set-equality check rather than asserting exact order.
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        first = presets.save_preset(repo, "First", "a", [], [])
        second = presets.save_preset(repo, "Second", "b", [], [])

        ids = {p.id for p in presets.list_presets(repo)}
        assert ids == {first.id, second.id}
    finally:
        db.close()


def test_rename_preset(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        saved = presets.save_preset(repo, "Old name", "text", [], [])

        presets.rename_preset(repo, saved.id, "New name")

        reloaded = repo.get_by_id(saved.id)
        assert reloaded.name == "New name"
    finally:
        db.close()


def test_rename_to_blank_falls_back_to_untitled(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        saved = presets.save_preset(repo, "Old name", "text", [], [])

        presets.rename_preset(repo, saved.id, "   ")

        reloaded = repo.get_by_id(saved.id)
        assert reloaded.name == "Без названия"
    finally:
        db.close()


def test_delete_preset(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        saved = presets.save_preset(repo, "Doomed", "text", [], [])

        presets.delete_preset(repo, saved.id)

        assert repo.get_by_id(saved.id) is None
    finally:
        db.close()


def test_load_raises_preset_error_for_corrupted_entities_json(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        saved = repo.create("Corrupted", "text", "not valid json{{{", "[]", None, None)

        with pytest.raises(PresetError):
            presets.load_preset(saved)
    finally:
        db.close()


def test_unknown_entity_type_is_skipped_not_crashed(tmp_path):
    # Forward-compat: a preset saved by a future version with an entity
    # type this version doesn't know must degrade gracefully, not crash.
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = PresetRepository(db)
        saved = repo.create("Future", "text", '[{"_": "MessageEntityFutureThing", "offset": 0, "length": 1}]', "[]", None, None)

        loaded = presets.load_preset(saved)

        assert loaded.message_entities == []
    finally:
        db.close()


def test_presets_persist_across_a_restart(tmp_path):
    db_path = tmp_path / "app.db"
    db1 = Database(db_path=db_path)
    try:
        repo1 = PresetRepository(db1)
        presets.save_preset(repo1, "Persisted", "hello", [], [])
    finally:
        db1.close()

    db2 = Database(db_path=db_path)
    try:
        repo2 = PresetRepository(db2)
        names = [p.name for p in presets.list_presets(repo2)]
        assert "Persisted" in names
    finally:
        db2.close()
