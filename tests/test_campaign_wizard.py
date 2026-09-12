"""Tests for the optional step-by-step Campaign Wizard
(app.ui.campaign_wizard). Covers step navigation/gating, the sending-
options validation path, the confirmation summary, and the final
result_state() handed back to MainWindow -- MainWindow's own handling of
that result (writing it into the live Campaign-page widgets and calling
_on_start_requested) is covered in tests/test_main_window_ux.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QDialog

from app.database.database import Database
from app.database.repositories import SettingsRepository
from app.ui.campaign_wizard import (
    CampaignWizardDialog,
    _STEP_ATTACHMENTS,
    _STEP_CONFIRMATION,
    _STEP_MESSAGE,
    _STEP_PREVIEW,
    _STEP_RECIPIENTS,
    _STEP_SENDING_OPTIONS,
)


def _make_dialog(tmp_path: Path) -> CampaignWizardDialog:
    db = Database(tmp_path / "app.db")
    repo = SettingsRepository(db)
    return CampaignWizardDialog(repo)


def test_starts_on_recipients_step_with_next_disabled(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    assert dialog._stack.currentIndex() == _STEP_RECIPIENTS
    assert dialog._back_button.isEnabled() is False
    assert dialog._next_button.isEnabled() is False


def test_adding_a_valid_recipient_enables_next(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    dialog._recipient_widget.set_text("@testuser")
    assert dialog._next_button.isEnabled() is True


def test_next_advances_through_every_step_in_order(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    dialog._recipient_widget.set_text("@testuser")

    expected = [_STEP_MESSAGE, _STEP_ATTACHMENTS, _STEP_SENDING_OPTIONS, _STEP_PREVIEW, _STEP_CONFIRMATION]
    for step in expected:
        dialog._on_next_clicked()
        assert dialog._stack.currentIndex() == step
    assert dialog._next_button.text() == "Начать рассылку"


def test_back_button_returns_to_the_previous_step(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    dialog._recipient_widget.set_text("@testuser")
    dialog._on_next_clicked()  # -> message
    dialog._on_next_clicked()  # -> attachments
    dialog._on_back_clicked()
    assert dialog._stack.currentIndex() == _STEP_MESSAGE


def test_message_step_reuses_message_editor_dialog(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    with patch("app.ui.campaign_wizard.MessageEditorDialog") as mock_editor_cls:
        mock_editor = mock_editor_cls.return_value
        mock_editor.exec.return_value = QDialog.DialogCode.Accepted
        mock_editor.result_content.return_value = ("Hello {name}", [])
        dialog._on_open_editor_clicked()
    assert dialog._message_text == "Hello {name}"
    assert dialog._message_summary_label.text() == "Hello {name}"


def test_attachments_step_uses_the_shared_attachments_widget(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"x")
    dialog._attachments_widget.add_file(photo)
    assert [a.path for a in dialog._attachments_widget.get_attachments()] == [photo]


def test_sending_options_rejects_min_greater_than_max(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    dialog._recipient_widget.set_text("@testuser")
    dialog._on_next_clicked()  # -> message
    dialog._on_next_clicked()  # -> attachments
    dialog._on_next_clicked()  # -> sending options
    assert dialog._stack.currentIndex() == _STEP_SENDING_OPTIONS
    dialog._min_spin.setValue(100)
    dialog._max_spin.setValue(50)
    with patch("app.ui.campaign_wizard.show_error") as mock_show_error:
        dialog._on_next_clicked()
    mock_show_error.assert_called_once()
    assert dialog._stack.currentIndex() == _STEP_SENDING_OPTIONS  # navigation was blocked


def test_sending_options_persists_a_valid_interval(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    dialog._recipient_widget.set_text("@testuser")
    dialog._on_next_clicked()  # -> message
    dialog._on_next_clicked()  # -> attachments
    dialog._on_next_clicked()  # -> sending options
    dialog._min_spin.setValue(20)
    dialog._max_spin.setValue(40)
    dialog._on_next_clicked()  # -> preview (saves the interval on the way out)
    assert dialog._stack.currentIndex() == _STEP_PREVIEW
    reloaded = dialog._settings_repository.load_app_settings()
    assert reloaded.min_delay_seconds == 20
    assert reloaded.max_delay_seconds == 40


def test_confirmation_summary_reflects_recipients_and_attachments(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    dialog._recipient_widget.set_text("@alice_test\n@bob_test")
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"x")
    dialog._attachments_widget.add_file(photo)

    for _ in range(5):  # recipients -> ... -> confirmation
        dialog._on_next_clicked()

    assert dialog._stack.currentIndex() == _STEP_CONFIRMATION
    text = dialog._confirmation_label.text()
    assert "2" in text  # recipient count
    assert "1" in text  # attachment count


def test_start_on_confirmation_accepts_the_dialog(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    dialog._recipient_widget.set_text("@testuser")
    for _ in range(5):
        dialog._on_next_clicked()
    assert dialog._stack.currentIndex() == _STEP_CONFIRMATION

    dialog._on_next_clicked()  # Start
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_result_state_reflects_everything_collected(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    dialog._recipient_widget.set_text("@testuser")
    dialog._message_text = "Hi {name}"
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"x")
    dialog._attachments_widget.add_file(photo)

    result = dialog.result_state()
    assert result.recipients_text == "@testuser"
    assert result.message_text == "Hi {name}"
    assert result.attachment_paths == [photo]


def test_cancel_rejects_the_dialog(qapp, tmp_path):
    dialog = _make_dialog(tmp_path)
    dialog.reject()
    assert dialog.result() == QDialog.DialogCode.Rejected
