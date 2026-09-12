"""Tests for app.diagnostics (ROADMAP: Diagnostics). Verifies the report
contains the expected fields, that a real DB failure is reported (not
silently swallowed), and that nothing here ever touches session file
contents -- only whether a file exists.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from app.database.database import Database
from app.database.repositories import AccountRepository
from app.diagnostics import collect_diagnostics, format_diagnostics_text
from app.i18n import tr
from app.version import APP_VERSION


def test_collect_diagnostics_includes_expected_fields(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        report = collect_diagnostics(db, "Connected: @alice", "Active connection")
        labels = [label for label, _ in report.fields]
        assert len(report.fields) == 7
        assert len(set(labels)) == 7  # each field label appears once
        values = dict(report.fields)
        assert APP_VERSION in values.values()
        assert "Connected: @alice" in values.values()
        assert "Active connection" in values.values()
    finally:
        db.close()


def test_database_status_reports_ok_for_a_healthy_database(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        report = collect_diagnostics(db, "x", "y")
        values = dict(report.fields)
        assert values[tr("diagnostics.field.database_status")] == tr("diagnostics.status.ok")
    finally:
        db.close()


def test_database_status_reports_an_error_when_the_database_is_unreachable(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        with patch.object(db, "cursor", side_effect=sqlite3.OperationalError("disk I/O error")):
            report = collect_diagnostics(db, "x", "y")
        values = dict(report.fields)
        assert "disk I/O error" in values[tr("diagnostics.field.database_status")]
    finally:
        db.close()


def test_session_storage_reports_no_accounts_when_none_exist(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        report = collect_diagnostics(db, "x", "y")
        values = dict(report.fields)
        assert values[tr("diagnostics.field.session_storage")] == tr("diagnostics.session_storage.no_accounts")
    finally:
        db.close()


def test_session_storage_counts_present_session_files(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = AccountRepository(db)
        repo.create("+70001112233", "session_present")
        repo.create("+70004445566", "session_missing")

        present_file = tmp_path / "session_present.session"
        present_file.write_bytes(b"fake")
        missing_file = tmp_path / "session_missing.session"  # deliberately never created

        def fake_get_session_path(session_name: str) -> Path:
            return present_file if session_name == "session_present" else missing_file

        with patch("app.diagnostics.get_session_path", side_effect=fake_get_session_path):
            report = collect_diagnostics(db, "x", "y")

        values = dict(report.fields)
        expected = tr("diagnostics.session_storage.summary", present=1, total=2)
        assert values[tr("diagnostics.field.session_storage")] == expected
    finally:
        db.close()


def test_session_storage_degrades_gracefully_when_the_database_is_unreachable(tmp_path):
    # A broken DB must not crash diagnostics collection entirely -- every
    # field should still report something (an error), not raise.
    db = Database(db_path=tmp_path / "app.db")
    try:
        with patch.object(db, "cursor", side_effect=sqlite3.OperationalError("disk I/O error")):
            report = collect_diagnostics(db, "x", "y")
        values = dict(report.fields)
        assert "disk I/O error" in values[tr("diagnostics.field.session_storage")]
    finally:
        db.close()


def test_format_diagnostics_text_is_one_line_per_field(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        report = collect_diagnostics(db, "x", "y")
        text = format_diagnostics_text(report)
        lines = text.splitlines()
        assert len(lines) == len(report.fields)
        for (label, value), line in zip(report.fields, lines):
            assert line == f"{label}: {value}"
    finally:
        db.close()


def test_diagnostics_never_includes_credential_or_session_content_fields(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        report = collect_diagnostics(db, "Connected: @alice", "Active connection")
        text = format_diagnostics_text(report).lower()
        for forbidden in ("api_hash", "api hash", "2fa", "password"):
            assert forbidden not in text
    finally:
        db.close()
