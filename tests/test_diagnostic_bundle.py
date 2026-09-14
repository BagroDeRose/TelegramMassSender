"""Tests for app.diagnostic_bundle (ROADMAP: Diagnostic Bundle). Verifies
the exported ZIP contains exactly the expected, already-sanitized
contents, and never a session file, API credentials, or message text.
"""
from __future__ import annotations

import json
import zipfile
from unittest.mock import patch

from app.config.settings import AppSettings
from app.database.database import Database
from app.diagnostic_bundle import export_diagnostic_bundle


def test_bundle_contains_diagnostics_and_settings(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        out_path = tmp_path / "bundle.zip"
        export_diagnostic_bundle(out_path, db, AppSettings(), "Connected: @alice", "Active connection")

        with zipfile.ZipFile(out_path) as bundle:
            names = bundle.namelist()
            assert "diagnostics.txt" in names
            assert "settings.json" in names

            diagnostics_text = bundle.read("diagnostics.txt").decode("utf-8")
            assert "Connected: @alice" in diagnostics_text

            settings_data = json.loads(bundle.read("settings.json").decode("utf-8"))
            assert settings_data["language"] == AppSettings().language
            assert settings_data["theme"] == AppSettings().theme
    finally:
        db.close()


def test_bundle_includes_log_files_when_present(tmp_path):
    from app.config import paths

    db = Database(db_path=tmp_path / "app.db")
    try:
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        (logs_dir / "application.log").write_text("2026-01-01 INFO test log line\n", encoding="utf-8")
        (logs_dir / "application.log.1").write_text("older log line\n", encoding="utf-8")

        out_path = tmp_path / "bundle.zip"
        with patch.object(paths, "get_logs_dir", return_value=logs_dir):
            with patch("app.diagnostic_bundle.get_logs_dir", return_value=logs_dir):
                export_diagnostic_bundle(out_path, db, AppSettings(), "x", "y")

        with zipfile.ZipFile(out_path) as bundle:
            names = bundle.namelist()
            assert "logs/application.log" in names
            assert "logs/application.log.1" in names
            assert "2026-01-01 INFO test log line" in bundle.read("logs/application.log").decode("utf-8")
    finally:
        db.close()


def test_bundle_has_no_logs_entry_when_logs_dir_is_missing(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        missing_dir = tmp_path / "does_not_exist"
        out_path = tmp_path / "bundle.zip"
        with patch("app.diagnostic_bundle.get_logs_dir", return_value=missing_dir):
            export_diagnostic_bundle(out_path, db, AppSettings(), "x", "y")

        with zipfile.ZipFile(out_path) as bundle:
            assert not any(name.startswith("logs/") for name in bundle.namelist())
    finally:
        db.close()


def test_bundle_never_contains_credential_or_session_markers(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        out_path = tmp_path / "bundle.zip"
        export_diagnostic_bundle(out_path, db, AppSettings(), "Connected: @alice", "Active connection")

        with zipfile.ZipFile(out_path) as bundle:
            for name in bundle.namelist():
                assert not name.endswith(".session")
                content = bundle.read(name).decode("utf-8", errors="replace").lower()
                for forbidden in ("api_hash", "api_id", "2fa", "password"):
                    assert forbidden not in content
    finally:
        db.close()


def test_bundle_redacts_a_custom_reports_directory_under_the_user_profile(tmp_path):
    # A custom reports folder is very often somewhere under the user's
    # own Windows profile (e.g. Documents), which embeds their Windows
    # account name -- found via a real, manually-generated bundle during
    # the release-candidate privacy audit (not a hypothetical).
    db = Database(db_path=tmp_path / "app.db")
    try:
        out_path = tmp_path / "bundle.zip"
        settings = AppSettings(reports_directory=r"C:\Users\jsmith\Documents\TelegramMassSender\reports")
        export_diagnostic_bundle(out_path, db, settings, "x", "y")

        with zipfile.ZipFile(out_path) as bundle:
            settings_data = json.loads(bundle.read("settings.json").decode("utf-8"))
        assert "jsmith" not in settings_data["reports_directory"]
        assert settings_data["reports_directory"] == r"C:\Users\<redacted>\Documents\TelegramMassSender\reports"
    finally:
        db.close()


def test_bundle_leaves_the_default_empty_reports_directory_unchanged(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        out_path = tmp_path / "bundle.zip"
        export_diagnostic_bundle(out_path, db, AppSettings(), "x", "y")

        with zipfile.ZipFile(out_path) as bundle:
            settings_data = json.loads(bundle.read("settings.json").decode("utf-8"))
        assert settings_data["reports_directory"] == ""
    finally:
        db.close()


def test_bundle_leaves_a_non_profile_reports_directory_unchanged(tmp_path):
    # Nothing to redact -- D:\ isn't under a user profile at all, so this
    # must pass through untouched rather than being mangled.
    db = Database(db_path=tmp_path / "app.db")
    try:
        out_path = tmp_path / "bundle.zip"
        settings = AppSettings(reports_directory=r"D:\Reports\TelegramMassSender")
        export_diagnostic_bundle(out_path, db, settings, "x", "y")

        with zipfile.ZipFile(out_path) as bundle:
            settings_data = json.loads(bundle.read("settings.json").decode("utf-8"))
        assert settings_data["reports_directory"] == r"D:\Reports\TelegramMassSender"
    finally:
        db.close()


def test_bundle_settings_json_round_trips_every_appsettings_field(tmp_path):
    from dataclasses import fields

    db = Database(db_path=tmp_path / "app.db")
    try:
        out_path = tmp_path / "bundle.zip"
        settings = AppSettings(min_delay_seconds=15, max_delay_seconds=45, language="en")
        export_diagnostic_bundle(out_path, db, settings, "x", "y")

        with zipfile.ZipFile(out_path) as bundle:
            settings_data = json.loads(bundle.read("settings.json").decode("utf-8"))
        for field in fields(AppSettings):
            assert field.name in settings_data
        assert settings_data["min_delay_seconds"] == 15
        assert settings_data["max_delay_seconds"] == 45
        assert settings_data["language"] == "en"
    finally:
        db.close()
