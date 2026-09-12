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
    with patch.object(QMessageBox, "exec") as mock_exec:
        dialog.reject()
    mock_exec.assert_not_called()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_cancel_with_changes_no_keeps_dialog_open(qapp):
    # _confirm_discard now builds its own custom-button QMessageBox
    # (matching every other confirmation dialog in the app -- see
    # app.ui.dialogs) rather than calling QMessageBox.question(), so the
    # actual unit under test here is reject()'s behavior given the
    # confirm/decline result, not the exact QMessageBox mechanics.
    dialog = MessageEditorDialog("original", [])
    dialog._editor.text_edit.setPlainText("changed!")
    with patch.object(dialog, "_save_geometry") as mock_save, patch.object(
        dialog, "_confirm_discard", return_value=False
    ) as mock_confirm:
        dialog.reject()
    mock_confirm.assert_called_once()
    mock_save.assert_not_called()  # reject() must return early, not close
    assert dialog.result() == QDialog.DialogCode.Rejected  # not yet actually rejected via super().reject()


def test_cancel_with_changes_yes_discards(qapp):
    dialog = MessageEditorDialog("original", [])
    dialog._editor.text_edit.setPlainText("changed!")
    with patch.object(dialog, "_save_geometry") as mock_save, patch.object(
        dialog, "_confirm_discard", return_value=True
    ) as mock_confirm:
        dialog.reject()
    mock_confirm.assert_called_once()
    mock_save.assert_called_once()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_confirm_discard_no_button_keeps_the_dialog_open(qapp):
    # A real, non-mocked exercise of _confirm_discard's own button-role
    # wiring: simulate the user clicking "No" by driving the actual
    # QMessageBox it constructs, rather than mocking around it.
    dialog = MessageEditorDialog("original", [])
    dialog._editor.text_edit.setPlainText("changed!")

    def click_no(self):
        no_button = next(b for b in self.buttons() if self.buttonRole(b) == QMessageBox.ButtonRole.NoRole)
        self.setResult(0)
        no_button.click()
        return 0

    with patch.object(QMessageBox, "exec", click_no):
        assert dialog._confirm_discard() is False


def test_confirm_discard_yes_button_allows_discard(qapp):
    dialog = MessageEditorDialog("original", [])
    dialog._editor.text_edit.setPlainText("changed!")

    def click_yes(self):
        yes_button = next(b for b in self.buttons() if self.buttonRole(b) == QMessageBox.ButtonRole.YesRole)
        self.setResult(0)
        yes_button.click()
        return 0

    with patch.object(QMessageBox, "exec", click_yes):
        assert dialog._confirm_discard() is True


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
