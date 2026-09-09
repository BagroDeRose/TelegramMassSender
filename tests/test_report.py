"""Tests for the CSV campaign report (app.campaign.report)."""
from __future__ import annotations

import csv

from app.campaign.report import build_report_rows, suggest_report_filename, write_csv_report
from app.campaign.send_queue import SendItem, SendItemStatus
from app.recipients.parser import parse_recipient_line


def test_empty_item_list_has_only_header():
    rows = build_report_rows([])
    assert len(rows) == 1
    assert rows[0][0] == "Получатель"


def test_mixed_statuses_in_rows():
    items = [
        SendItem(recipient=parse_recipient_line("@alice"), status=SendItemStatus.SENT, sent_at="2026-01-01T10:00:00"),
        SendItem(
            recipient=parse_recipient_line("@bob"),
            status=SendItemStatus.FAILED,
            error="пользователь заблокировал аккаунт",
            sent_at="2026-01-01T10:00:05",
        ),
        SendItem(recipient=parse_recipient_line("@carol"), status=SendItemStatus.SKIPPED, sent_at="2026-01-01T10:00:10"),
        SendItem(recipient=parse_recipient_line("@dave"), status=SendItemStatus.PENDING),
    ]
    rows = build_report_rows(items)
    assert len(rows) == 5
    statuses = [row[4] for row in rows[1:]]
    assert statuses == ["успешно", "ошибка", "пропущено", "не обработано"]
    assert rows[2][5] == "пользователь заблокировал аккаунт"


def test_write_csv_report_unicode_roundtrip(tmp_path):
    item = SendItem(
        recipient=parse_recipient_line("@юзер"),
        status=SendItemStatus.FAILED,
        error="Ошибка: получатель недоступен — «приватность»",
        sent_at="2026-01-01T10:00:00",
    )
    path = tmp_path / "report.csv"
    write_csv_report([item], path)

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))

    assert rows[0][0] == "Получатель"
    # Leading "'" is the CSV-formula-injection guard (see test below) --
    # @-prefixed recipients are this app's normal case, not an edge case.
    assert rows[1][0] == "'@юзер"
    assert rows[1][5] == "Ошибка: получатель недоступен — «приватность»"


def test_write_csv_report_escapes_delimiter_quotes_and_newlines(tmp_path):
    item = SendItem(
        recipient=parse_recipient_line("@alice"),
        status=SendItemStatus.FAILED,
        error='Ошибка; содержит "кавычки"\nи перенос строки',
        sent_at="2026-01-01T10:00:00",
    )
    path = tmp_path / "report.csv"
    write_csv_report([item], path)

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))

    assert rows[1][5] == 'Ошибка; содержит "кавычки"\nи перенос строки'
    # The raw file must actually contain the delimiter/quote escaping --
    # not just happen to parse back correctly by accident.
    raw = path.read_text(encoding="utf-8-sig")
    assert '"Ошибка; содержит ""кавычки""' in raw


def test_suggest_report_filename_format():
    name = suggest_report_filename()
    assert name.startswith("TelegramMassSender_report_")
    assert name.endswith(".csv")


def test_csv_formula_injection_prevented_for_dangerous_prefixes():
    # Regression test: a cell whose first character is one of =+-@ can be
    # executed as a formula by Excel/Sheets. @username and +<phone> are
    # this app's two normal recipient formats, so this isn't a hypothetical
    # edge case -- most real reports would otherwise contain it on the
    # "Получатель" column. build_report_rows must prefix such cells with a
    # single quote (the standard mitigation) rather than writing them raw.
    items = [
        SendItem(recipient=parse_recipient_line("@alice"), status=SendItemStatus.SENT),
        SendItem(recipient=parse_recipient_line("+4917612345678"), status=SendItemStatus.SENT),
    ]
    rows = build_report_rows(items)
    assert rows[1][0] == "'@alice"
    assert rows[2][0] == "'+4917612345678"

    # resolved_username and error are also written from data that could in
    # principle start with a dangerous character -- same guard applies.
    item = SendItem(
        recipient=parse_recipient_line("123456789"),
        status=SendItemStatus.FAILED,
        resolved_username="=cmd|' /C calc'!A1",
        error="=SUM(1+1)",
    )
    row = build_report_rows([item])[1]
    assert row[3] == "'=cmd|' /C calc'!A1"
    assert row[5] == "'=SUM(1+1)"

    # A recipient that does not start with a dangerous character is left
    # untouched -- the guard must not alter ordinary values.
    plain = build_report_rows([SendItem(recipient=parse_recipient_line("123456789"), status=SendItemStatus.SENT)])
    assert plain[1][0] == "123456789"


def test_resolved_identity_columns():
    item = SendItem(
        recipient=parse_recipient_line("123456789"),
        status=SendItemStatus.SENT,
        resolved_id=123456789,
        resolved_username="realuser",
        sent_at="2026-01-01T10:00:00",
    )
    rows = build_report_rows([item])
    assert rows[1][2] == "123456789"
    assert rows[1][3] == "realuser"
