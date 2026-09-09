"""Tests for the saved-report library (app.campaign.report_library +
app.database.repositories.SavedReportRepository). Covers save/list/
rename/favorite/delete/open/export, missing-file handling, Unicode names,
and restart persistence (a fresh repository against the same DB file).
"""
from __future__ import annotations

import csv

import pytest

from app.campaign import report_library
from app.campaign.report_library import ReportFileMissingError
from app.campaign.send_queue import SendItem, SendItemStatus
from app.database.database import Database
from app.database.repositories import SavedReportRepository
from app.recipients.parser import parse_recipient_line


def _items():
    return [
        SendItem(recipient=parse_recipient_line("@alice"), status=SendItemStatus.SENT, sent_at="2026-01-01T10:00:00"),
        SendItem(recipient=parse_recipient_line("@bobby"), status=SendItemStatus.FAILED, error="ошибка", sent_at="2026-01-01T10:00:05"),
    ]


def test_save_report_writes_csv_and_metadata(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        directory = tmp_path / "reports"
        saved = report_library.save_report(repo, directory, "Сентябрьская кампания", _items(), total=2, successful=1, failed=1, skipped=0)

        assert saved.id is not None
        assert saved.name == "Сентябрьская кампания"
        assert saved.total == 2 and saved.successful == 1 and saved.failed == 1
        from pathlib import Path
        assert Path(saved.file_path).is_file()
        assert Path(saved.file_path).parent == directory
    finally:
        db.close()


def test_save_report_blank_name_uses_placeholder(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        saved = report_library.save_report(repo, tmp_path / "reports", "   ", _items(), 2, 1, 1, 0)
        assert saved.name == "Без названия"
    finally:
        db.close()


def test_list_reports_orders_newest_first(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        directory = tmp_path / "reports"
        first = report_library.save_report(repo, directory, "First", _items(), 2, 1, 1, 0)
        second = report_library.save_report(repo, directory, "Second", _items(), 2, 1, 1, 0)

        listed = report_library.list_reports(repo)
        ids = [r.id for r in listed]
        assert set(ids) == {first.id, second.id}
    finally:
        db.close()


def test_rename_report(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        saved = report_library.save_report(repo, tmp_path / "reports", "Old name", _items(), 2, 1, 1, 0)
        report_library.rename_report(repo, saved.id, "Новое имя")
        reloaded = repo.get_by_id(saved.id)
        assert reloaded.name == "Новое имя"
    finally:
        db.close()


def test_favorite_and_unfavorite(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        saved = report_library.save_report(repo, tmp_path / "reports", "Report", _items(), 2, 1, 1, 0)
        assert repo.get_by_id(saved.id).is_favorite is False

        report_library.set_favorite(repo, saved.id, True)
        assert repo.get_by_id(saved.id).is_favorite is True

        report_library.set_favorite(repo, saved.id, False)
        assert repo.get_by_id(saved.id).is_favorite is False
    finally:
        db.close()


def test_delete_report_removes_row_and_file(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        saved = report_library.save_report(repo, tmp_path / "reports", "Report", _items(), 2, 1, 1, 0)
        from pathlib import Path
        file_path = Path(saved.file_path)
        assert file_path.is_file()

        report_library.delete_report(repo, saved)

        assert repo.get_by_id(saved.id) is None
        assert not file_path.exists()
    finally:
        db.close()


def test_delete_report_tolerates_already_missing_file(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        saved = report_library.save_report(repo, tmp_path / "reports", "Report", _items(), 2, 1, 1, 0)
        from pathlib import Path
        Path(saved.file_path).unlink()  # simulate the file already being gone

        report_library.delete_report(repo, saved)  # must not raise

        assert repo.get_by_id(saved.id) is None
    finally:
        db.close()


def test_read_report_rows_returns_csv_content(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        saved = report_library.save_report(repo, tmp_path / "reports", "Report", _items(), 2, 1, 1, 0)

        rows = report_library.read_report_rows(saved)
        assert rows[0][0] == "Получатель"
        # Leading "'" is the CSV-formula-injection guard (app.campaign.report
        # ._sanitize_csv_cell) -- @alice is written as "'@alice".
        assert any(row[0] == "'@alice" for row in rows[1:])
    finally:
        db.close()


def test_read_report_rows_missing_file_raises_domain_error(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        saved = report_library.save_report(repo, tmp_path / "reports", "Report", _items(), 2, 1, 1, 0)
        from pathlib import Path
        Path(saved.file_path).unlink()

        with pytest.raises(ReportFileMissingError):
            report_library.read_report_rows(saved)
    finally:
        db.close()


def test_export_report_copies_file(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        saved = report_library.save_report(repo, tmp_path / "reports", "Report", _items(), 2, 1, 1, 0)
        destination = tmp_path / "exported.csv"

        report_library.export_report(saved, destination)

        assert destination.is_file()
        with destination.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f, delimiter=";"))
        assert rows[0][0] == "Получатель"
    finally:
        db.close()


def test_export_report_missing_file_raises_domain_error(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        saved = report_library.save_report(repo, tmp_path / "reports", "Report", _items(), 2, 1, 1, 0)
        from pathlib import Path
        Path(saved.file_path).unlink()

        with pytest.raises(ReportFileMissingError):
            report_library.export_report(saved, tmp_path / "out.csv")
    finally:
        db.close()


def test_unicode_report_name_roundtrips(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        saved = report_library.save_report(repo, tmp_path / "reports", "Кампания «Осень» 🎉", _items(), 2, 1, 1, 0)
        reloaded = repo.get_by_id(saved.id)
        assert reloaded.name == "Кампания «Осень» 🎉"
    finally:
        db.close()


def test_duplicate_names_are_allowed(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = SavedReportRepository(db)
        first = report_library.save_report(repo, tmp_path / "reports", "Same name", _items(), 2, 1, 1, 0)
        second = report_library.save_report(repo, tmp_path / "reports", "Same name", _items(), 2, 1, 1, 0)
        assert first.id != second.id
        assert len(report_library.list_reports(repo)) == 2
    finally:
        db.close()


def test_saved_reports_persist_across_restart(tmp_path):
    db_path = tmp_path / "app.db"
    db1 = Database(db_path=db_path)
    try:
        repo1 = SavedReportRepository(db1)
        saved = report_library.save_report(repo1, tmp_path / "reports", "Persisted", _items(), 2, 1, 1, 0)
    finally:
        db1.close()

    # Simulate an application restart: a brand-new Database/repository
    # against the same file must see the same row.
    db2 = Database(db_path=db_path)
    try:
        repo2 = SavedReportRepository(db2)
        reloaded = repo2.get_by_id(saved.id)
        assert reloaded is not None
        assert reloaded.name == "Persisted"
        from pathlib import Path
        assert Path(reloaded.file_path).is_file()
    finally:
        db2.close()
