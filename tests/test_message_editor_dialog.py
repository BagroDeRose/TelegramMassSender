"""Floating message editor dialog tests: seeded content, apply/cancel,
unsaved-changes confirmation, session geometry persistence, and full
formatting round-trip through open->apply.
"""
from __future__ import annotations

from unittest.mock import patch

from PySide6.QtGui import QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QDialog, QMessageBox, QTextEdit
from telethon.tl.types import MessageEntityBold

from app.ui import message_editor_dialog as med_module
from app.ui.message_editor import extract_message_content
from app.ui.message_editor_dialog import MessageEditorDialog


def test_seeded_content_and_char_count(qapp):
    dialog = MessageEditorDialog("Hello world", [])
    assert dialog._editor.get_plain_text() == "Hello world"
    assert dialog._char_count_label.text() == "Символов: 11"


def test_apply_returns_edited_content(qapp):
    dialog = MessageEditorDialog("initial text", [])
    dialog._editor.text_edit.setPlainText("edited text, longer now")
    dialog._on_apply()
    assert dialog.result() == QDialog.DialogCode.Accepted
    text, _entities = dialog.result_content()
    assert text == "edited text, longer now"


def test_cancel_without_changes_skips_prompt(qapp):
    dialog = MessageEditorDialog("same text", [])
    with patch("app.ui.message_editor_dialog.QMessageBox.question") as mock_q:
        dialog.reject()
    mock_q.assert_not_called()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_cancel_with_changes_no_keeps_dialog_open(qapp):
    dialog = MessageEditorDialog("original", [])
    dialog._editor.text_edit.setPlainText("changed!")
    with patch.object(dialog, "_save_geometry") as mock_save, patch(
        "app.ui.message_editor_dialog.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ) as mock_q:
        dialog.reject()
    mock_q.assert_called_once()
    mock_save.assert_not_called()  # reject() must return early, not close


def test_cancel_with_changes_yes_discards(qapp):
    dialog = MessageEditorDialog("original", [])
    dialog._editor.text_edit.setPlainText("changed!")
    with patch.object(dialog, "_save_geometry") as mock_save, patch(
        "app.ui.message_editor_dialog.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ) as mock_q:
        dialog.reject()
    mock_q.assert_called_once()
    mock_save.assert_called_once()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_geometry_persists_within_session(qapp):
    med_module._last_geometry = None
    dialog1 = MessageEditorDialog("x", [])
    dialog1.setGeometry(100, 100, 900, 700)
    dialog1._on_apply()

    dialog2 = MessageEditorDialog("y", [])
    geo = dialog2.geometry()
    assert geo.width() == 900 and geo.height() == 700


def test_formatting_survives_open_apply_roundtrip(qapp):
    source = QTextEdit()
    source.setPlainText("bold word here")
    cursor = source.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
    fmt = QTextCharFormat()
    fmt.setFontWeight(QFont.Weight.Bold.value)
    cursor.mergeCharFormat(fmt)
    text, entities = extract_message_content(source.document())

    dialog = MessageEditorDialog(text, entities)
    dialog._on_apply()
    result_text, result_entities = dialog.result_content()
    assert result_text == text
    assert len(result_entities) == 1
    assert isinstance(result_entities[0], MessageEntityBold)
