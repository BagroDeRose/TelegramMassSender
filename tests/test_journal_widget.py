"""Tests for the collapsible journal panel (app.ui.journal_widget)."""
from __future__ import annotations

from app.ui.journal_widget import JournalWidget, _classify


def test_classify_success_marker():
    icon_name, variant = _classify("✓ @alice — отправлено")
    assert icon_name == "check_circle"
    assert variant == "success"


def test_classify_failure_marker():
    icon_name, variant = _classify("✗ @bobby — ошибка")
    assert icon_name == "error_circle"
    assert variant == "error"


def test_classify_waiting_marker():
    icon_name, variant = _classify("… повтор 1/3 для @alice через 4 сек.")
    assert icon_name == "clock"
    assert variant == "warning"


def test_classify_unmarked_message_returns_none():
    assert _classify("Следующая отправка через 30 сек.") is None


def test_append_adds_row_with_timestamp(qapp):
    journal = JournalWidget()
    journal.append("✓ @alice — отправлено")
    assert journal._list.count() == 1
    text = journal._list.item(0).text()
    assert "✓ @alice — отправлено" in text
    assert not journal._list.item(0).icon().isNull()


def test_append_unmarked_message_has_no_icon(qapp):
    journal = JournalWidget()
    journal.append("Следующая отправка через 30 сек.")
    assert journal._list.item(0).icon().isNull()


def test_clear_removes_all_entries(qapp):
    journal = JournalWidget()
    journal.append("✓ sent")
    journal.append("✗ failed")
    journal.clear()
    assert journal._list.count() == 0


def test_apply_theme_does_not_raise(qapp):
    journal = JournalWidget()
    journal.append("✓ sent")
    journal.append("✗ failed")
    journal.apply_theme()  # must not raise, and must not lose entries
    assert journal._list.count() == 2


def test_toggle_requested_signal_emits_on_button_click(qapp):
    journal = JournalWidget()
    signals = []
    journal.toggle_requested.connect(lambda: signals.append(True))
    journal._collapse_button.click()
    assert signals == [True]


def test_old_lines_are_trimmed(qapp):
    journal = JournalWidget()
    from app.ui.journal_widget import _MAX_VISIBLE_LINES

    for i in range(_MAX_VISIBLE_LINES + 20):
        journal.append(f"message {i}")
    assert journal._list.count() == _MAX_VISIBLE_LINES
    assert "message" in journal._list.item(0).text()  # oldest trimmed, not newest
