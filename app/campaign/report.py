"""CSV export of the current in-memory campaign's results.

The app deliberately keeps no campaign history between launches (see
app.database.database) -- this module only ever reads the in-memory
SendItem list of the campaign that produced it (app.campaign.campaign_manager
.items). Kept out of app/ui so the UI layer stays a thin dialog wrapper
around this service/model-layer logic.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import List

from app.campaign.send_queue import SendItem, SendItemStatus
from app.recipients.parser import RecipientKind

_STATUS_LABELS = {
    SendItemStatus.SENT: "успешно",
    SendItemStatus.FAILED: "ошибка",
    SendItemStatus.SKIPPED: "пропущено",
    SendItemStatus.PENDING: "не обработано",
    SendItemStatus.SENDING: "не обработано",
}

_KIND_LABELS = {
    RecipientKind.USERNAME: "username",
    RecipientKind.USER_ID: "Telegram ID",
    RecipientKind.PHONE: "телефон",
}

_HEADER = [
    "Получатель",
    "Тип",
    "Resolved ID",
    "Resolved username",
    "Статус",
    "Ошибка",
    "Попыток",
    "Шагов доставлено",
    "Время",
]


def _kind_label(kind) -> str:
    if kind is None:
        return "неизвестно"
    return _KIND_LABELS.get(kind, str(getattr(kind, "value", kind)))


_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_cell(value: str) -> str:
    """Neutralize CSV/formula injection: a cell whose first character is
    one of =+-@ can be executed as a formula when the file is opened in
    Excel/Sheets. This app's two recipient formats are `@username` and
    `+<phone>`, so the "Получатель" column would trigger this on most
    rows of a normal report. Prefixing with a single quote is the
    standard mitigation (OWASP) -- spreadsheet apps treat a leading `'`
    as a "force text" marker and don't display it, so the value a person
    reads is unchanged."""
    if value and value[0] in _FORMULA_TRIGGER_CHARS:
        return "'" + value
    return value


def build_report_rows(items: List[SendItem]) -> List[List[str]]:
    rows: List[List[str]] = [list(_HEADER)]
    for item in items:
        rows.append(
            [
                _sanitize_csv_cell(item.recipient.raw.strip()),
                _kind_label(item.recipient.kind),
                str(item.resolved_id) if item.resolved_id is not None else "",
                _sanitize_csv_cell(item.resolved_username or ""),
                _STATUS_LABELS.get(item.status, str(item.status)),
                _sanitize_csv_cell(item.error or ""),
                str(item.attempts),
                str(item.next_step),
                item.sent_at or "",
            ]
        )
    return rows


def write_csv_report(items: List[SendItem], path: Path) -> None:
    rows = build_report_rows(items)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerows(rows)


def suggest_report_filename() -> str:
    return f"TelegramMassSender_report_{datetime.now():%Y-%m-%d_%H-%M}.csv"
