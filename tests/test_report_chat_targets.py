"""CSV report: the "Тип" column for group/supergroup/channel targets, and
saved reports carrying them through unchanged."""
from __future__ import annotations

import csv

from app.campaign.report import build_report_rows, write_csv_report
from app.campaign.send_queue import SendItem, SendItemStatus
from app.recipients.parser import parse_recipient_line


def _item(line, target_type=None, status=SendItemStatus.SENT, resolved_id=None, error=None):
    return SendItem(
        recipient=parse_recipient_line(line),
        status=status,
        target_type=target_type,
        resolved_id=resolved_id,
        error=error,
        sent_at="2026-10-17T10:00:00",
    )


def test_type_column_for_chats_and_users():
    rows = build_report_rows(
        [
            _item("@ivan_petrov", "user", resolved_id=111),
            _item("123456789", "user", resolved_id=123456789),
            _item("@daily_news", "channel", resolved_id=-1000000000100),
            _item("-1001234567890", "supergroup", resolved_id=-1001234567890),
            _item("@forum_chat", "forum", resolved_id=-1000000000012),
            _item("-987654321", "group", resolved_id=-987654321),
            _item("https://t.me/+InviteHash1", None, status=SendItemStatus.FAILED, error="аккаунт не состоит в этом чате"),
            _item("-1009999999999", None, status=SendItemStatus.FAILED),
        ]
    )
    types = [row[1] for row in rows[1:]]
    assert types == [
        "username",
        "Telegram ID",
        "канал",
        "супергруппа",
        "супергруппа",
        "группа",
        "ссылка-приглашение",
        "ID чата",
    ]
    # Marked chat ids are written as text, never as a (formula-able,
    # scientific-notation) number.
    assert rows[3][2] == "'-1000000000100"
    assert rows[1][2] == "111"


def test_chat_rows_survive_csv_roundtrip(tmp_path):
    path = tmp_path / "report.csv"
    write_csv_report([_item("-1001234567890", "supergroup", resolved_id=-1001234567890)], path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert rows[1][0] == "'-1001234567890"
    assert rows[1][1] == "супергруппа"
    assert rows[1][4] == "успешно"
