"""Regression tests for UX fixes found in the interface audit:
proactive Start-button state, account buttons disabled during a campaign,
controls disabled while a campaign is running, the message editor dialog
wiring into the preview, and the CampaignManager Qt-parent leak fix.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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


async def test_preview_substitutes_the_example_name_for_the_placeholder(qapp, tmp_path):
    # Personalization preview (v1.5): the preview must go through the same
    # expand_name_placeholder() the real send path uses per-recipient, not
    # a second, preview-only implementation -- so this proves the wiring,
    # not the substitution logic itself (already exhaustively covered by
    # tests/test_template.py).
    window = _make_window(tmp_path)
    window._message_text = "Hello, {name}!"
    window._message_entities = []
    window._preview_name_edit.setText("Alex")

    assert "Hello, Alex!" in window._message_preview._browser.toPlainText()
    assert "{name}" not in window._message_preview._browser.toPlainText()


async def test_preview_updates_live_when_the_example_name_changes(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "Hi {name}"
    window._message_entities = []
    window._update_message_preview()

    window._preview_name_edit.setText("Maria")

    assert "Hi Maria" in window._message_preview._browser.toPlainText()


@pytest.mark.parametrize(
    "example_name,expected_substring",
    [
        ("Alex", "Hi Alex"),
        ("Мария", "Hi Мария"),  # Cyrillic
        ("José 🎉", "Hi José 🎉"),  # accented + astral-plane emoji
        ("", "Hi "),  # empty example name -- placeholder resolves to nothing, not a crash
        ("A" * 80, f"Hi {'A' * 80}"),  # long name
    ],
)
async def test_preview_personalization_handles_varied_names(qapp, tmp_path, example_name, expected_substring):
    window = _make_window(tmp_path)
    window._message_text = "Hi {name}"
    window._message_entities = []

    window._preview_name_edit.setText(example_name)

    assert expected_substring in window._message_preview._browser.toPlainText()


async def test_preview_without_a_placeholder_ignores_the_example_name(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "No placeholder here"
    window._message_entities = []
    window._preview_name_edit.setText("Alex")

    assert "No placeholder here" in window._message_preview._browser.toPlainText()


async def test_preview_personalization_preserves_bold_entity_offsets(qapp, tmp_path):
    # Regression guard for the exact bug class expand_name_placeholder
    # exists to prevent: a naive text substitution would shift/corrupt
    # entity offsets for anything after the placeholder once the
    # substituted name's UTF-16 length differs from len("{name}").
    from telethon.tl.types import MessageEntityBold

    window = _make_window(tmp_path)
    window._message_text = "Hi {name}, welcome!"
    # "welcome" starts right after the (much longer) substituted name.
    bold_start = window._message_text.index("welcome")
    window._message_entities = [MessageEntityBold(offset=bold_start, length=len("welcome"))]
    window._preview_name_edit.setText("Alexandra")

    html = window._message_preview._browser.toHtml()
    assert "<b" in html or "font-weight" in html.lower()
    assert "welcome" in window._message_preview._browser.toPlainText()


async def test_preview_name_survives_language_retranslation(qapp, tmp_path):
    from app.i18n import LANGUAGE_EN, LANGUAGE_RU, set_language

    window = _make_window(tmp_path)
    try:
        window._preview_name_edit.setText("CustomName")
        english_index = window._language_combo.findData(LANGUAGE_EN)
        window._language_combo.setCurrentIndex(english_index)

        # Retranslation must not silently discard a user-edited example name.
        assert window._preview_name_edit.text() == "CustomName"
    finally:
        set_language(LANGUAGE_RU)


async def test_save_preset_writes_and_refreshes_combo(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "Hello {name}"
    window._message_entities = []
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"x")
    window._attachments_widget.add_file(photo)

    with patch("app.ui.main_window.QInputDialog") as mock_dialog, patch("app.ui.main_window.show_info"):
        mock_dialog.getText.return_value = ("My preset", True)
        window._on_save_preset_clicked()

    from app.campaign import presets

    saved = presets.list_presets(window._preset_repo)
    assert len(saved) == 1
    assert saved[0].name == "My preset"
    assert window._presets_combo.findText("My preset") != -1


async def test_save_preset_cancelled_does_not_create_a_row(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "Hello"
    window._message_entities = []

    with patch("app.ui.main_window.QInputDialog") as mock_dialog:
        mock_dialog.getText.return_value = ("", False)  # user hit Cancel
        window._on_save_preset_clicked()

    from app.campaign import presets

    assert presets.list_presets(window._preset_repo) == []


async def test_load_preset_restores_message_and_attachments(qapp, tmp_path):
    from app.campaign import presets

    window = _make_window(tmp_path)
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"x")
    saved = presets.save_preset(window._preset_repo, "Greeting", "Hi {name}", [], [photo])
    window._refresh_presets_combo()
    index = window._presets_combo.findData(saved.id)
    window._presets_combo.setCurrentIndex(index)

    window._on_load_preset_clicked()

    assert window._message_text == "Hi {name}"
    assert [a.path for a in window._attachments_widget.get_attachments()] == [photo]


async def test_load_preset_warns_about_missing_attachments_but_still_loads(qapp, tmp_path):
    from app.campaign import presets

    window = _make_window(tmp_path)
    present = tmp_path / "present.jpg"
    present.write_bytes(b"x")
    gone = tmp_path / "gone.jpg"
    gone.write_bytes(b"x")
    saved = presets.save_preset(window._preset_repo, "Mixed", "text", [], [present, gone])
    gone.unlink()
    window._refresh_presets_combo()
    window._presets_combo.setCurrentIndex(window._presets_combo.findData(saved.id))

    with patch("app.ui.main_window.show_error") as mock_show_error:
        window._on_load_preset_clicked()

    assert [a.path for a in window._attachments_widget.get_attachments()] == [present]
    assert mock_show_error.call_count == 1
    assert "gone.jpg" in mock_show_error.call_args[0][2]


async def test_load_preset_with_no_selection_shows_an_error(qapp, tmp_path):
    window = _make_window(tmp_path)

    with patch("app.ui.main_window.show_error") as mock_show_error:
        window._on_load_preset_clicked()

    mock_show_error.assert_called_once()


async def test_load_preset_restores_the_saved_interval(qapp, tmp_path):
    from app.campaign import presets

    window = _make_window(tmp_path)
    saved = presets.save_preset(
        window._preset_repo, "Timed", "text", [], [], min_delay_seconds=45, max_delay_seconds=90
    )
    window._refresh_presets_combo()
    window._presets_combo.setCurrentIndex(window._presets_combo.findData(saved.id))

    window._on_load_preset_clicked()

    reloaded = window._service.settings_repository.load_app_settings()
    assert reloaded.min_delay_seconds == 45
    assert reloaded.max_delay_seconds == 90
    assert "45" in window._campaign_controls._interval_summary_label.text()


async def test_delete_preset_removes_it(qapp, tmp_path):
    from app.campaign import presets

    window = _make_window(tmp_path)
    saved = presets.save_preset(window._preset_repo, "Doomed", "text", [], [])
    window._refresh_presets_combo()
    window._presets_combo.setCurrentIndex(window._presets_combo.findData(saved.id))

    with patch("app.ui.main_window.confirm_delete_preset", return_value=True):
        window._on_delete_preset_clicked()

    assert presets.list_presets(window._preset_repo) == []
    assert window._presets_combo.findData(saved.id) == -1


async def test_delete_preset_declined_keeps_it(qapp, tmp_path):
    from app.campaign import presets

    window = _make_window(tmp_path)
    saved = presets.save_preset(window._preset_repo, "Kept", "text", [], [])
    window._refresh_presets_combo()
    window._presets_combo.setCurrentIndex(window._presets_combo.findData(saved.id))

    with patch("app.ui.main_window.confirm_delete_preset", return_value=False):
        window._on_delete_preset_clicked()

    assert len(presets.list_presets(window._preset_repo)) == 1


async def test_save_group_writes_and_refreshes_combo(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._recipient_widget.set_text("@ivan_test\n@maria_test")

    with patch("app.ui.main_window.QInputDialog") as mock_dialog, patch("app.ui.main_window.show_info"):
        mock_dialog.getText.return_value = ("Customers", True)
        window._on_save_group_clicked()

    from app.recipients import groups

    saved = groups.list_groups(window._group_repo)
    assert len(saved) == 1
    assert saved[0].name == "Customers"
    assert window._groups_combo.findText("Customers") != -1


async def test_save_group_cancelled_does_not_create_a_row(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._recipient_widget.set_text("@ivan_test")

    with patch("app.ui.main_window.QInputDialog") as mock_dialog:
        mock_dialog.getText.return_value = ("", False)
        window._on_save_group_clicked()

    from app.recipients import groups

    assert groups.list_groups(window._group_repo) == []


async def test_load_group_restores_text_and_name_overrides(qapp, tmp_path):
    from app.recipients import groups

    window = _make_window(tmp_path)
    saved = groups.save_group(window._group_repo, "Customers", "@ivan_test", {"username:ivan_test": "Ivan"})
    window._refresh_groups_combo()
    window._groups_combo.setCurrentIndex(window._groups_combo.findData(saved.id))

    window._on_load_group_clicked()

    assert window._recipient_widget.get_text() == "@ivan_test"
    assert window._recipient_widget.name_overrides() == {"username:ivan_test": "Ivan"}


async def test_load_group_with_no_selection_shows_an_error(qapp, tmp_path):
    window = _make_window(tmp_path)

    with patch("app.ui.main_window.show_error") as mock_show_error:
        window._on_load_group_clicked()

    mock_show_error.assert_called_once()


async def test_delete_group_removes_it(qapp, tmp_path):
    from app.recipients import groups

    window = _make_window(tmp_path)
    saved = groups.save_group(window._group_repo, "Doomed", "@a", {})
    window._refresh_groups_combo()
    window._groups_combo.setCurrentIndex(window._groups_combo.findData(saved.id))

    with patch("app.ui.main_window.confirm_delete_group", return_value=True):
        window._on_delete_group_clicked()

    assert groups.list_groups(window._group_repo) == []
    assert window._groups_combo.findData(saved.id) == -1


async def test_delete_group_declined_keeps_it(qapp, tmp_path):
    from app.recipients import groups

    window = _make_window(tmp_path)
    saved = groups.save_group(window._group_repo, "Kept", "@a", {})
    window._refresh_groups_combo()
    window._groups_combo.setCurrentIndex(window._groups_combo.findData(saved.id))

    with patch("app.ui.main_window.confirm_delete_group", return_value=False):
        window._on_delete_group_clicked()

    assert len(groups.list_groups(window._group_repo)) == 1


async def test_campaign_wizard_accept_writes_state_and_reuses_start_path(qapp, tmp_path):
    # The wizard must never start a campaign itself -- it hands its
    # collected state to the exact same _on_start_requested the fast
    # (single-page) workflow's Start button calls, so both paths share one
    # validation/start implementation.
    from app.ui.campaign_wizard import WizardResult

    window = _make_window(tmp_path)
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"x")
    result = WizardResult(
        recipients_text="@testuser",
        message_text="Hello {name}",
        message_entities=[],
        attachment_paths=[photo],
    )

    with patch("app.ui.main_window.CampaignWizardDialog") as mock_wizard_cls, \
         patch.object(window, "_on_start_requested") as mock_start:
        instance = mock_wizard_cls.return_value
        instance.exec.return_value = QDialog.DialogCode.Accepted
        instance.result_state.return_value = result
        window._on_open_campaign_wizard_clicked()

    assert window._recipient_widget.get_text() == "@testuser"
    assert window._message_text == "Hello {name}"
    assert [a.path for a in window._attachments_widget.get_attachments()] == [photo]
    mock_start.assert_called_once()


async def test_campaign_wizard_cancelled_does_not_touch_state_or_start(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "unchanged"

    with patch("app.ui.main_window.CampaignWizardDialog") as mock_wizard_cls, \
         patch.object(window, "_on_start_requested") as mock_start:
        instance = mock_wizard_cls.return_value
        instance.exec.return_value = QDialog.DialogCode.Rejected
        window._on_open_campaign_wizard_clicked()

    assert window._message_text == "unchanged"
    mock_start.assert_not_called()


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


async def test_start_campaign_starts_the_elapsed_timer_and_wires_current_item(qapp, tmp_path):
    # Campaign Controls (v1.6): elapsed/remaining time and the current-
    # recipient label are driven by the widget's own timer and by
    # CampaignManager.current_item_changed -- both must actually be
    # started/connected when a real campaign starts, not just exist as
    # dead code.
    window = _make_window(tmp_path)
    fake_account_manager = MagicMock()
    fake_account = Account(
        id=1, phone="+70001112233", telegram_user_id=1, username="u", display_name="U",
        session_name="s", created_at="now", last_used_at=None,
    )
    fake_account_manager.active_account_id = 1
    window._service.account_manager = fake_account_manager
    window._service.account_repository.get_by_id = MagicMock(return_value=fake_account)
    fake_client = MagicMock()
    fake_client.is_user_authorized = AsyncMock(return_value=True)
    fake_account_manager.ensure_connected = AsyncMock(return_value=fake_client)

    window._recipient_widget._text_edit.setPlainText("@testuser")
    window._recipient_widget.flush()
    window._message_text = "hello"
    window._on_form_state_changed()
    window._update_message_preview()

    with patch("app.ui.main_window.CampaignManager") as mock_campaign_cls, \
         patch.object(window._campaign_controls, "start_elapsed_timer") as mock_start_timer:
        mock_campaign = MagicMock()
        mock_campaign_cls.return_value = mock_campaign
        window._on_start_requested()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    mock_start_timer.assert_called_once()
    mock_campaign.current_item_changed.connect.assert_called_once_with(window._campaign_controls.set_current_item)


async def test_campaign_finished_stops_the_elapsed_timer(qapp, tmp_path):
    from app.campaign.campaign_state import CampaignStatus

    window = _make_window(tmp_path)
    with patch.object(window._campaign_controls, "stop_elapsed_timer") as mock_stop_timer:
        window._on_campaign_finished(CampaignStatus.COMPLETED.value)
    mock_stop_timer.assert_called_once()


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


def _fake_report_source_with_two_failures():
    from app.campaign.send_queue import SendItem, SendItemStatus
    from app.recipients.parser import parse_recipient_line as parse

    fake_campaign = MagicMock()
    fake_campaign.items = [
        SendItem(recipient=parse("@alice_test"), status=SendItemStatus.SENT),
        SendItem(recipient=parse("@bob_test"), status=SendItemStatus.FAILED, error="Пользователь не найден"),
        SendItem(recipient=parse("@carol_test"), status=SendItemStatus.FAILED, error="Заблокирован"),
    ]
    return fake_campaign


async def test_refresh_failed_items_lists_only_failed_recipients(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._report_source = _fake_report_source_with_two_failures()

    window._refresh_failed_items()

    assert window._failed_items_list.count() == 2
    assert window._failed_items_list.isHidden() is False
    assert window._retry_all_button.isEnabled() is True
    texts = [window._failed_items_list.item(i).text() for i in range(2)]
    assert any("bob_test" in t and "Пользователь не найден" in t for t in texts)
    assert any("carol_test" in t for t in texts)


async def test_refresh_failed_items_hides_section_with_no_failures(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._refresh_failed_items()
    assert window._failed_items_list.isHidden() is True
    assert window._retry_row_widget.isHidden() is True
    assert window._retry_all_button.isEnabled() is False


async def test_retry_selected_enables_only_once_a_row_is_checked(qapp, tmp_path):
    from PySide6.QtCore import Qt

    window = _make_window(tmp_path)
    window._report_source = _fake_report_source_with_two_failures()
    window._refresh_failed_items()
    assert window._retry_selected_button.isEnabled() is False

    window._failed_items_list.item(0).setCheckState(Qt.CheckState.Checked)
    assert window._retry_selected_button.isEnabled() is True

    window._failed_items_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert window._retry_selected_button.isEnabled() is False


async def test_retry_selected_only_relaunches_checked_recipients(qapp, tmp_path):
    from PySide6.QtCore import Qt

    window = _make_window(tmp_path)
    window._report_source = _fake_report_source_with_two_failures()
    window._refresh_failed_items()
    window._last_campaign_context = (MagicMock(), "hello", [], [], {})
    window._failed_items_list.item(1).setCheckState(Qt.CheckState.Checked)  # carol_test only

    with patch.object(window, "_start_campaign", new=AsyncMock()) as mock_start:
        window._on_retry_selected_clicked()
        await asyncio.sleep(0)

    mock_start.assert_called_once()
    recipients_arg = mock_start.call_args[0][1]
    assert [r.value for r in recipients_arg] == ["carol_test"]


async def test_retry_all_failures_relaunches_every_failed_recipient(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._report_source = _fake_report_source_with_two_failures()
    window._refresh_failed_items()
    window._last_campaign_context = (MagicMock(), "hello", [], [], {})

    with patch.object(window, "_start_campaign", new=AsyncMock()) as mock_start:
        window._on_retry_all_failures_clicked()
        await asyncio.sleep(0)

    mock_start.assert_called_once()
    recipients_arg = mock_start.call_args[0][1]
    assert sorted(r.value for r in recipients_arg) == ["bob_test", "carol_test"]


async def test_retry_is_a_noop_without_a_previous_campaign_context(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._report_source = _fake_report_source_with_two_failures()
    window._refresh_failed_items()
    assert window._last_campaign_context is None

    with patch.object(window, "_start_campaign", new=AsyncMock()) as mock_start:
        window._on_retry_all_failures_clicked()
        await asyncio.sleep(0)

    mock_start.assert_not_called()


async def test_retry_blocked_while_a_campaign_is_already_running(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._report_source = _fake_report_source_with_two_failures()
    window._refresh_failed_items()
    window._last_campaign_context = (MagicMock(), "hello", [], [], {})
    running_campaign = MagicMock()
    running_campaign.is_active = True
    window._current_campaign = running_campaign

    with patch.object(window, "_start_campaign", new=AsyncMock()) as mock_start, patch(
        "app.ui.main_window.show_error"
    ) as mock_show_error:
        window._on_retry_all_failures_clicked()
        await asyncio.sleep(0)

    mock_start.assert_not_called()
    mock_show_error.assert_called_once()
