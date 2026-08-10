"""Regression tests for UX fixes found in the interface audit:
proactive Start-button state, account buttons disabled during a campaign,
test-send blocked during a campaign, the message editor dialog wiring
into the preview, and the CampaignManager Qt-parent leak fix.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from PySide6.QtWidgets import QDialog

from app.campaign.campaign_manager import CampaignManager
from app.campaign.rate_limiter import RateLimiter
from app.database.database import Database
from app.recipients.parser import parse_recipient_line
from app.telegram.account_manager import Account
from app.ui.main_window import MainWindow


def _make_window(tmp_path: Path) -> MainWindow:
    return MainWindow(database=Database(tmp_path / "app.db"))


async def test_start_disabled_by_default(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert window._campaign_controls._start_button.isEnabled() is False


async def test_start_enabled_once_all_preconditions_met(qapp, tmp_path):
    window = _make_window(tmp_path)

    fake_account_manager = MagicMock()
    fake_account = Account(
        id=1, phone="+70001112233", telegram_user_id=1, username="u", display_name="U",
        session_name="s", created_at="now", last_used_at=None,
    )
    fake_account_manager.active_account_id = 1
    window._service.account_manager = fake_account_manager
    window._service.account_repository.get_by_id = MagicMock(return_value=fake_account)
    window._on_form_state_changed()
    assert window._campaign_controls._start_button.isEnabled() is False

    window._recipient_widget._text_edit.setPlainText("@testuser")
    window._recipient_widget.flush()
    window._on_form_state_changed()
    assert window._campaign_controls._start_button.isEnabled() is False

    window._message_text = "hello"
    window._update_message_preview()
    assert window._campaign_controls._start_button.isEnabled() is True


async def test_open_editor_dialog_updates_preview(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert window._message_text == ""

    with patch("app.ui.main_window.MessageEditorDialog") as mock_dialog_cls:
        instance = mock_dialog_cls.return_value
        instance.exec.return_value = QDialog.DialogCode.Accepted
        instance.result_content.return_value = ("edited message", [])
        window._on_open_editor_clicked()

    assert window._message_text == "edited message"
    assert "edited message" in window._message_preview._browser.toPlainText()


async def test_test_send_blocked_during_active_campaign(qapp, tmp_path):
    window = _make_window(tmp_path)
    fake_campaign = MagicMock()
    fake_campaign.is_active = True
    window._current_campaign = fake_campaign
    window._campaign_controls.set_running_state(True, paused=False)
    assert window._campaign_controls._test_button.isEnabled() is False


async def test_account_add_delete_disabled_during_campaign(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._account_widget.set_enabled_switching(False)
    assert window._account_widget._add_button.isEnabled() is False
    assert window._account_widget._delete_button.isEnabled() is False


async def test_campaign_manager_created_without_qt_parent(qapp, tmp_path):
    fake_client = MagicMock()
    fake_client.send_message = AsyncMock()
    campaign = CampaignManager(
        client=fake_client,
        recipients=[parse_recipient_line("@x")],
        message_text="hi",
        message_entities=[],
        attachments=[],
        rate_limiter=RateLimiter(5, 5),
        max_retries=1,
        parent=None,
    )
    assert campaign.parent() is None
