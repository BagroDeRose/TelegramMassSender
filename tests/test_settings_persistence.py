"""Round-trip tests for the expanded AppSettings schema (window state,
journal visibility, confirm-before-start, reports directory/auto-save,
debug logging) via app.database.repositories.SettingsRepository -- the
single source of truth these settings persist through.
"""
from __future__ import annotations

from app.config.settings import AppSettings
from app.database.database import Database
from app.database.repositories import SettingsRepository


def _repo(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    return SettingsRepository(db), db


def test_defaults_match_appsettings_dataclass_defaults(tmp_path):
    repo, db = _repo(tmp_path)
    try:
        loaded = repo.load_app_settings()
        defaults = AppSettings()
        assert loaded == defaults
    finally:
        db.close()


def test_all_new_fields_roundtrip(tmp_path):
    repo, db = _repo(tmp_path)
    try:
        settings = repo.load_app_settings()
        settings.confirm_before_start = True
        settings.remember_window_size = False
        settings.window_width = 1366
        settings.window_height = 768
        settings.window_maximized = True
        settings.remember_last_page = False
        settings.last_page_index = 2
        settings.journal_visible = True
        settings.reports_directory = "D:/reports"
        settings.auto_save_reports = True
        settings.debug_logging = True
        repo.save_app_settings(settings)

        reloaded = repo.load_app_settings()
        assert reloaded.confirm_before_start is True
        assert reloaded.remember_window_size is False
        assert reloaded.window_width == 1366
        assert reloaded.window_height == 768
        assert reloaded.window_maximized is True
        assert reloaded.remember_last_page is False
        assert reloaded.last_page_index == 2
        assert reloaded.journal_visible is True
        assert reloaded.reports_directory == "D:/reports"
        assert reloaded.auto_save_reports is True
        assert reloaded.debug_logging is True
    finally:
        db.close()


def test_boolean_false_survives_roundtrip_not_just_true(tmp_path):
    # A naive `value or default` implementation would treat "0" the same
    # as missing and silently fall back to the (True) default -- this
    # guards specifically against that class of bug.
    repo, db = _repo(tmp_path)
    try:
        settings = repo.load_app_settings()
        settings.remember_window_size = True
        repo.save_app_settings(settings)
        settings.remember_window_size = False
        repo.save_app_settings(settings)

        reloaded = repo.load_app_settings()
        assert reloaded.remember_window_size is False
    finally:
        db.close()


def test_existing_sending_settings_unaffected(tmp_path):
    repo, db = _repo(tmp_path)
    try:
        settings = repo.load_app_settings()
        settings.min_delay_seconds = 15
        settings.max_delay_seconds = 45
        settings.retry_count = 2
        repo.save_app_settings(settings)

        reloaded = repo.load_app_settings()
        assert reloaded.min_delay_seconds == 15
        assert reloaded.max_delay_seconds == 45
        assert reloaded.retry_count == 2
    finally:
        db.close()
