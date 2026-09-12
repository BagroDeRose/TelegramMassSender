"""Tests for app.ui.recipient_widget's CSV import wiring, the invalid-rows
review dialog, and per-recipient name overrides (Smart Recipient Import).
Plain paste-box parsing itself is covered by tests/test_parser.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.ui.recipient_widget import RecipientWidget


def _write_csv(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "recipients.csv"
    path.write_text(content, encoding="utf-8-sig")
    return path


def test_csv_import_adds_lines_and_name_overrides(qapp, tmp_path):
    widget = RecipientWidget()
    csv_path = _write_csv(tmp_path, "Ivan,@ivan_test\nMaria,@maria_test\n")

    with patch("app.ui.recipient_widget.QFileDialog.getOpenFileName", return_value=(str(csv_path), "")), \
         patch("app.ui.recipient_widget.QMessageBox.information"):
        widget._on_import_csv_clicked()

    assert len(widget.valid_recipients()) == 2
    assert widget.name_overrides() == {"username:ivan_test": "Ivan", "username:maria_test": "Maria"}


def test_csv_import_failure_shows_a_warning_and_changes_nothing(qapp, tmp_path):
    widget = RecipientWidget()
    missing = tmp_path / "does_not_exist.csv"

    with patch("app.ui.recipient_widget.QFileDialog.getOpenFileName", return_value=(str(missing), "")), \
         patch("app.ui.recipient_widget.QMessageBox.warning") as mock_warning:
        widget._on_import_csv_clicked()

    mock_warning.assert_called_once()
    assert widget.valid_recipients() == []


def test_csv_import_cancelled_dialog_does_nothing(qapp, tmp_path):
    widget = RecipientWidget()
    with patch("app.ui.recipient_widget.QFileDialog.getOpenFileName", return_value=("", "")):
        widget._on_import_csv_clicked()
    assert widget.valid_recipients() == []


def test_name_override_is_pruned_when_its_recipient_is_removed(qapp, tmp_path):
    widget = RecipientWidget()
    csv_path = _write_csv(tmp_path, "Ivan,@ivan_test\n")
    with patch("app.ui.recipient_widget.QFileDialog.getOpenFileName", return_value=(str(csv_path), "")), \
         patch("app.ui.recipient_widget.QMessageBox.information"):
        widget._on_import_csv_clicked()
    assert widget.name_overrides() == {"username:ivan_test": "Ivan"}

    widget.set_text("@someone_else")
    assert widget.name_overrides() == {}


def test_clear_button_also_clears_name_overrides(qapp, tmp_path):
    widget = RecipientWidget()
    csv_path = _write_csv(tmp_path, "Ivan,@ivan_test\n")
    with patch("app.ui.recipient_widget.QFileDialog.getOpenFileName", return_value=(str(csv_path), "")), \
         patch("app.ui.recipient_widget.QMessageBox.information"):
        widget._on_import_csv_clicked()

    widget._on_clear_clicked()
    assert widget.name_overrides() == {}
    assert widget.get_text() == ""


def test_review_invalid_button_visible_only_with_invalid_entries(qapp):
    # isHidden() rather than isVisible(): with no top-level window shown
    # on screen, isVisible() would be False regardless of state -- see
    # tests/test_attachments_widget.py for the same established pattern.
    widget = RecipientWidget()
    assert widget._review_invalid_button.isHidden() is True

    widget.set_text("not-a-valid-recipient")
    assert widget._review_invalid_button.isHidden() is False

    widget.set_text("@valid_user")
    assert widget._review_invalid_button.isHidden() is True


def test_review_invalid_opens_dialog_with_raw_text_and_reason(qapp):
    widget = RecipientWidget()
    widget.set_text("not-a-valid-recipient")

    with patch("app.ui.recipient_widget.show_invalid_rows") as mock_show:
        widget._on_review_invalid_clicked()

    mock_show.assert_called_once()
    _parent, _title, rows = mock_show.call_args[0]
    assert rows == [("not-a-valid-recipient", rows[0][1])]
    assert rows[0][1]  # a non-empty reason string
