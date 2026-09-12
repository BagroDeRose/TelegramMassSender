"""Regression tests for UX fixes found in the interface audit:
proactive Start-button state, account buttons disabled during a campaign,
controls disabled while a campaign is running, the message editor dialog
wiring into the preview, and the CampaignManager Qt-parent leak fix.
"""
from __future__ import annotations

import asyncio
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


async def test_start_button_disabled_while_campaign_running(qapp, tmp_path):
    # Test Send was removed (redundant with adding a test recipient and
    # starting a real campaign, per the second UX pass) -- this replaces
    # the old test-send-blocked assertion with the equivalent check for
    # the controls that remain: Start must stay disabled and Stop/Pause
    # must become enabled while a campaign is actively running.
    window = _make_window(tmp_path)
    window._campaign_controls.set_start_ready(True)
    assert window._campaign_controls._start_button.isEnabled() is True

    window._campaign_controls.set_running_state(True, paused=False)
    assert window._campaign_controls._start_button.isEnabled() is False
    assert window._campaign_controls._pause_button.isEnabled() is True
    assert window._campaign_controls._stop_button.isEnabled() is True


async def test_double_click_start_does_not_launch_two_campaigns(qapp, tmp_path):
    # Regression test for a confirmed bug: _on_start_requested's only guard
    # is `self._current_campaign is not None and .is_active`, but
    # _current_campaign is not assigned until *after* `await
    # account_manager.ensure_connected(account)` inside _start_campaign --
    # a real network round-trip -- and the Start button itself isn't
    # disabled until that same await resolves (set_running_state(True) is
    # called after it too). A second click landing in that window re-enters
    # _on_start_requested, passes the same guard, and schedules a second,
    # fully independent CampaignManager over the identical recipient list --
    # i.e. every recipient would receive the message twice.
    window = _make_window(tmp_path)
    fake_account_manager = MagicMock()
    fake_account = Account(
        id=1, phone="+70001112233", telegram_user_id=1, username="u", display_name="U",
        session_name="s", created_at="now", last_used_at=None,
    )
    fake_account_manager.active_account_id = 1
    window._service.account_manager = fake_account_manager
    window._service.account_repository.get_by_id = MagicMock(return_value=fake_account)

    gate = asyncio.Event()
    fake_client = MagicMock()
    fake_client.is_user_authorized = AsyncMock(return_value=True)

    async def slow_ensure_connected(account):
        # Stands in for the real network round-trip -- resolves only once
        # the test releases `gate`, giving both simulated clicks a chance
        # to land first.
        await gate.wait()
        return fake_client

    fake_account_manager.ensure_connected = slow_ensure_connected

    window._recipient_widget._text_edit.setPlainText("@testuser")
    window._recipient_widget.flush()
    window._message_text = "hello"
    window._on_form_state_changed()
    window._update_message_preview()
    assert window._campaign_controls._start_button.isEnabled() is True

    with patch("app.ui.main_window.CampaignManager") as mock_campaign_cls:
        mock_campaign_cls.return_value = MagicMock()

        window._on_start_requested()
        window._on_start_requested()  # simulated rapid second click

        await asyncio.sleep(0)
        gate.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert mock_campaign_cls.call_count == 1


async def test_start_blocked_by_an_unreadable_attachment(qapp, tmp_path):
    # Stage 4: a file that exists but can't be opened for reading (locked,
    # permission-denied) must block campaign start with a clear error,
    # exactly like the existing missing-file check just above it in
    # _on_start_requested -- distinct failure mode, same guard shape.
    window = _make_window(tmp_path)
    fake_account_manager = MagicMock()
    fake_account = Account(
        id=1, phone="+70001112233", telegram_user_id=1, username="u", display_name="U",
        session_name="s", created_at="now", last_used_at=None,
    )
    fake_account_manager.active_account_id = 1
    window._service.account_manager = fake_account_manager
    window._service.account_repository.get_by_id = MagicMock(return_value=fake_account)

    window._recipient_widget._text_edit.setPlainText("@testuser")
    window._recipient_widget.flush()
    window._message_text = "hello"

    locked_file = tmp_path / "locked.pdf"
    locked_file.write_bytes(b"x")
    window._attachments_widget.add_file(locked_file)
    window._on_form_state_changed()
    window._update_message_preview()
    assert window._campaign_controls._start_button.isEnabled() is True

    with patch("app.ui.main_window.show_error") as mock_show_error, patch.object(
        Path, "open", side_effect=PermissionError("Access is denied")
    ):
        window._on_start_requested()

    assert window._campaign_starting is False  # never got past the validation guard
    assert mock_show_error.call_count == 1
    assert "locked.pdf" in mock_show_error.call_args[0][2]


async def test_account_add_delete_disabled_during_campaign(qapp, tmp_path):
    from app.telegram.account_manager import AccountStatus

    window = _make_window(tmp_path)
    fake_account = Account(
        id=1, phone="+70001112233", telegram_user_id=1, username="u", display_name="U",
        session_name="s", created_at="now", last_used_at=None,
    )
    window._account_widget.set_accounts([AccountStatus(account=fake_account, is_authorized=True, needs_reauth=False)], 1)

    window._account_widget.set_enabled_switching(False)

    assert window._account_widget._add_button.isEnabled() is False
    assert len(window._account_widget._delete_buttons) == 1
    assert window._account_widget._delete_buttons[0].isEnabled() is False


async def test_export_report_button_disabled_until_campaign_started(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert window._campaign_controls._export_report_button.isEnabled() is False

    fake_campaign = MagicMock()
    fake_campaign.items = [MagicMock()]
    window._report_source = fake_campaign
    window._campaign_controls.set_report_available(True)
    assert window._campaign_controls._export_report_button.isEnabled() is True


async def test_export_report_noop_without_data(qapp, tmp_path):
    window = _make_window(tmp_path)
    with patch("app.ui.main_window.QFileDialog") as mock_dialog:
        window._on_export_report_requested()
        mock_dialog.getSaveFileName.assert_not_called()


async def test_theme_combo_switches_active_theme(qapp, tmp_path):
    from app.ui import theme

    window = _make_window(tmp_path)
    light_index = window._theme_combo.findData(theme.THEME_LIGHT)
    window._theme_combo.setCurrentIndex(light_index)
    assert theme.get_active_theme() == theme.THEME_LIGHT
    reloaded = window._service.settings_repository.load_app_settings()
    assert reloaded.theme == theme.THEME_LIGHT
    theme.set_active_theme(theme.THEME_DARK)  # restore module-global state for other tests


async def test_language_combo_switches_active_language_and_retranslates(qapp, tmp_path):
    from app.i18n import LANGUAGE_EN, LANGUAGE_RU, get_language, set_language

    window = _make_window(tmp_path)
    try:
        english_index = window._language_combo.findData(LANGUAGE_EN)
        window._language_combo.setCurrentIndex(english_index)

        assert get_language() == LANGUAGE_EN
        reloaded = window._service.settings_repository.load_app_settings()
        assert reloaded.language == LANGUAGE_EN
        # Immediate switch, not "restart required" -- an already-built,
        # persistent widget's text actually changes.
        assert window._campaign_controls._start_button.text() == "▶  Start campaign"
        assert window._sidebar._buttons[0].text() == "  Campaign"
    finally:
        set_language(LANGUAGE_RU)  # restore module-global state for other tests


async def test_reset_settings_does_not_change_the_active_language(qapp, tmp_path):
    from app.i18n import LANGUAGE_EN, LANGUAGE_RU, get_language, set_language

    window = _make_window(tmp_path)
    try:
        english_index = window._language_combo.findData(LANGUAGE_EN)
        window._language_combo.setCurrentIndex(english_index)
        assert get_language() == LANGUAGE_EN

        with patch("app.ui.main_window.confirm_reset_settings", return_value=True), patch(
            "app.ui.main_window.show_info"
        ):
            window._on_reset_settings_clicked()

        # Matches the existing theme-reset behavior -- a setting with its
        # own dedicated control isn't silently flipped by a general reset.
        assert get_language() == LANGUAGE_EN
        reloaded = window._service.settings_repository.load_app_settings()
        assert reloaded.language == LANGUAGE_EN
    finally:
        set_language(LANGUAGE_RU)


async def test_sidebar_click_switches_stack_page(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert window._stack.currentIndex() == 0

    window._sidebar._buttons[2].click()

    assert window._stack.currentIndex() == 2


async def test_recipient_count_badge_updates(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert window._recipient_count_label.text() == "0"

    window._recipient_widget._text_edit.setPlainText("@alice\n@bobby")
    window._recipient_widget.flush()

    assert window._recipient_count_label.text() == "2"


async def test_results_page_starts_in_empty_state(qapp, tmp_path):
    window = _make_window(tmp_path)
    # isHidden() checks the widget's own setVisible() call, unaffected by
    # the top-level window never having been .show()'d in this test.
    assert window._results_empty_label.isHidden() is False
    assert window._results_stats_widget.isHidden() is True
    assert window._results_export_button.isEnabled() is False


async def test_update_results_stats_populates_stat_cards(qapp, tmp_path):
    from app.campaign.campaign_manager import ProgressSnapshot

    window = _make_window(tmp_path)
    window._update_results_stats(ProgressSnapshot(total=126, sent=121, failed=5, skipped=0, pending=0))

    assert window._results_empty_label.isHidden() is True
    assert window._results_stats_widget.isHidden() is False
    assert window._stat_total._value_label.text() == "126"
    assert window._stat_success._value_label.text() == "121"
    assert window._stat_failed._value_label.text() == "5"
    assert window._stat_skipped._value_label.text() == "0"


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


# ---- second UX pass: settings-driven interval, journal, window state ------


async def test_interval_lives_only_in_settings_page(qapp, tmp_path):
    # Single source of truth: CampaignControlsWidget no longer owns spin
    # boxes at all -- changing the value on the Settings page must update
    # its read-only summary label and persist through SettingsRepository.
    window = _make_window(tmp_path)
    assert not hasattr(window._campaign_controls, "_min_spin")

    window._settings_min_spin.setValue(12)
    window._settings_max_spin.setValue(34)
    window._on_interval_settings_changed()

    assert "12" in window._campaign_controls._interval_summary_label.text()
    assert "34" in window._campaign_controls._interval_summary_label.text()
    reloaded = window._service.settings_repository.load_app_settings()
    assert reloaded.min_delay_seconds == 12
    assert reloaded.max_delay_seconds == 34


async def test_open_settings_from_campaign_controls_navigates_there(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._navigate_to_page(0)
    assert window._stack.currentIndex() == 0

    window._campaign_controls.open_settings_requested.emit()

    assert window._stack.currentIndex() == 3
    assert window._sidebar._buttons[3].isChecked() is True


async def test_journal_hidden_by_default(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert window._journal.isHidden() is True


async def test_journal_toggle_persists_across_restart(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._on_toggle_journal()
    assert window._journal.isHidden() is False

    reopened = _make_window(tmp_path)
    assert reopened._journal.isHidden() is False


async def test_window_state_persists_across_restart(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.resize(1366, 800)
    window._navigate_to_page(2)
    window._save_window_state()

    reopened = _make_window(tmp_path)
    settings = reopened._service.settings_repository.load_app_settings()
    assert settings.window_width == 1366
    assert settings.window_height == 800
    assert settings.last_page_index == 2
    assert reopened._stack.currentIndex() == 2


async def test_window_state_not_saved_when_remember_disabled(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._remember_window_checkbox.setChecked(False)
    window.resize(1500, 900)
    window._save_window_state()

    settings = window._service.settings_repository.load_app_settings()
    assert settings.window_width != 1500


async def test_confirm_before_start_setting_persists(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._confirm_before_start_checkbox.setChecked(True)
    reloaded = window._service.settings_repository.load_app_settings()
    assert reloaded.confirm_before_start is True


async def test_reports_directory_setting_persists(qapp, tmp_path):
    window = _make_window(tmp_path)
    custom_dir = str(tmp_path / "my_reports")
    window._reports_dir_edit.setText(custom_dir)
    window._save_setting_field("reports_directory", custom_dir)

    reloaded = window._service.settings_repository.load_app_settings()
    assert reloaded.reports_directory == custom_dir
    assert window._reports_directory() == Path(custom_dir)


async def test_save_report_button_disabled_until_campaign_started(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert window._save_report_button.isEnabled() is False


async def test_save_report_writes_to_library_and_refreshes_list(qapp, tmp_path):
    from app.campaign.send_queue import SendItem, SendItemStatus
    from app.recipients.parser import parse_recipient_line as parse
    from app.campaign.campaign_manager import ProgressSnapshot

    window = _make_window(tmp_path)
    fake_campaign = MagicMock()
    fake_campaign.items = [SendItem(recipient=parse("@alice"), status=SendItemStatus.SENT)]
    fake_campaign.snapshot.return_value = ProgressSnapshot(total=1, sent=1, failed=0, skipped=0, pending=0)
    window._report_source = fake_campaign

    with patch("app.ui.main_window.QInputDialog") as mock_dialog, patch("app.ui.main_window.show_info"):
        mock_dialog.getText.return_value = ("My saved report", True)
        window._on_save_report_clicked()

    reports = window._saved_report_repo.list_all()
    assert len(reports) == 1
    assert reports[0].name == "My saved report"
    assert len(window._saved_report_cards) == 1
