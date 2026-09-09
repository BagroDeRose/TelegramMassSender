"""Local library of explicitly saved campaign reports (Results page).

Deliberately NOT automatic campaign history -- a row only exists here
because the user clicked "Save report" (or enabled auto-save in
Settings). Each saved report is a real CSV file, written with the same
app.campaign.report.write_csv_report the existing "Export CSV" button
already uses (no duplicated CSV-writing logic), plus a small metadata row
in SQLite (app.database.repositories.SavedReportRepository).
"""
from __future__ import annotations

import csv
import shutil
import uuid
from pathlib import Path
from typing import List

from app.campaign.report import write_csv_report
from app.campaign.send_queue import SendItem
from app.database.models import SavedReport
from app.database.repositories import SavedReportRepository
from app.logging.logger import get_logger

logger = get_logger()

_UNTITLED_NAME = "Без названия"


class ReportFileMissingError(Exception):
    """Raised when a saved report's DB row exists but its CSV file does
    not (moved/deleted outside the app, external drive unplugged, etc.).
    Callers must catch this and show a friendly error -- never let a raw
    OSError/FileNotFoundError reach the UI."""


def save_report(
    repo: SavedReportRepository,
    directory: Path,
    name: str,
    items: List[SendItem],
    total: int,
    successful: int,
    failed: int,
    skipped: int,
) -> SavedReport:
    """Write `items` to a new CSV file under `directory` and record it in
    the saved-report library. `total`/`successful`/`failed`/`skipped` are
    passed in rather than recomputed here so this never re-implements the
    status-counting logic app.campaign.campaign_manager.CampaignManager
    .snapshot() already owns."""
    directory.mkdir(parents=True, exist_ok=True)
    # Filename is a generated id, never the user's display name -- sidesteps
    # the entire "sanitize arbitrary text into a valid Windows filename"
    # problem, and duplicate display names are then never a filesystem issue.
    file_path = directory / f"report_{uuid.uuid4().hex[:12]}.csv"
    write_csv_report(items, file_path)

    display_name = name.strip() or _UNTITLED_NAME
    return repo.create(display_name, total, successful, failed, skipped, str(file_path))


def list_reports(repo: SavedReportRepository) -> List[SavedReport]:
    return repo.list_all()


def rename_report(repo: SavedReportRepository, report_id: int, new_name: str) -> None:
    repo.rename(report_id, new_name.strip() or _UNTITLED_NAME)


def set_favorite(repo: SavedReportRepository, report_id: int, is_favorite: bool) -> None:
    repo.set_favorite(report_id, is_favorite)


def delete_report(repo: SavedReportRepository, report: SavedReport) -> None:
    """Removes the DB row and best-effort removes the CSV file. A file
    that's already missing is not an error here -- the DB row leaving the
    library is the part that must succeed."""
    repo.delete(report.id)
    try:
        Path(report.file_path).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Не удалось удалить файл отчёта %s: %s", report.file_path, exc)


def read_report_rows(report: SavedReport) -> List[List[str]]:
    """Read a saved report's CSV content back for the "Open/View" action."""
    path = Path(report.file_path)
    if not path.is_file():
        raise ReportFileMissingError(f"Файл отчёта не найден: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f, delimiter=";"))
    except (OSError, csv.Error) as exc:
        raise ReportFileMissingError(f"Не удалось прочитать файл отчёта: {exc}") from exc


def export_report(report: SavedReport, destination: Path) -> None:
    """Copy a saved report's CSV to a user-chosen location -- the "Export"
    action on a *saved* report, distinct from the current-campaign "Export
    CSV" button which writes straight from in-memory SendItems."""
    path = Path(report.file_path)
    if not path.is_file():
        raise ReportFileMissingError(f"Файл отчёта не найден: {path}")
    shutil.copyfile(path, destination)
