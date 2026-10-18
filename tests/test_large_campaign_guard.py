"""Guard against an accidental mass send: more recipients than the
large-campaign threshold (setting, default 50, minimum 10) always asks
before starting -- whatever "Confirm before starting a campaign" says --
on every start path (Campaign page, Campaign Wizard, Retry), through the
one MainWindow._confirm_campaign_start."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.campaign.send_queue import SendItem, SendItemStatus
from app.config.settings import (
    DEFAULT_LARGE_CAMPAIGN_THRESHOLD,
    MIN_LARGE_CAMPAIGN_THRESHOLD,
    AppSettings,
    SettingsValidationError,
)
from app.database.database import Database
from app.database.repositories import SettingsRepository
from app.i18n import tr
from app.recipients.parser import parse_recipient_line
from app.security.secure_storage import SecureStorage
from app.ui import theme
from app.ui.campaign_wizard import CampaignWizardDialog, WizardResult
from app.ui.dialogs import RecipientBreakdown, build_large_campaign_box
from app.ui.main_window import MainWindow


def _lines(count: int) -> str:
    """People by ID, a few chats and @usernames."""
    lines = []
    for index in range(count):
        if index % 10 == 0:
            lines.append(f"-100{1900000000 + index}")
        elif index % 10 == 1:
            lines.append(f"@name_{index}")
        else:
            lines.append(str(100000 + index))
    return "\n".join(lines)


async def _window(tmp_path: Path, *, confirm_before_start=False, threshold=None) -> MainWindow:
    window = MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))
    repo = window._service.settings_repository
    settings = repo.load_app_settings()
    settings.confirm_before_start = confirm_before_start
    if threshold is not None:
        settings.large_campaign_threshold = threshold
    repo.save_app_settings(settings)
    window._enter_demo_mode()
    deadline = asyncio.get_event_loop().time() + 5
    while window._active_account() is None:
        assert asyncio.get_event_loop().time() < deadline
        await asyncio.sleep(0.02)
    window._message_text = "Hello"
    return window


def _start_from_page(window: MainWindow, count: int) -> None:
    window._recipient_widget.set_text(_lines(count))
    window._on_start_requested()


def _start_from_wizard(window: MainWindow, count: int) -> None:
    result = WizardResult(recipients_text=_lines(count), message_text="Hello", message_entities=[], attachment_paths=[])
    with patch.object(CampaignWizardDialog, "exec", return_value=QDialog.DialogCode.Accepted), patch.object(
        CampaignWizardDialog, "result_state", return_value=result
    ):
        window._on_open_campaign_wizard_clicked()


def _start_from_retry(window: MainWindow, count: int) -> None:
    source = MagicMock()
    source.items = [
        SendItem(recipient=parse_recipient_line(line), status=SendItemStatus.FAILED, error="x")
        for line in _lines(count).splitlines()
    ]
    source.delivered_chat_ids = set()
    window._report_source = source
    window._last_campaign_context = (window._active_account(), "Hello", [], [], {})
    window._on_retry_all_failures_clicked()


PATHS = {"page": _start_from_page, "wizard": _start_from_wizard, "retry": _start_from_retry}


# ---- the setting -------------------------------------------------------------------


def test_threshold_setting_defaults_bounds_and_persistence(tmp_path):
    assert DEFAULT_LARGE_CAMPAIGN_THRESHOLD == 50
    assert MIN_LARGE_CAMPAIGN_THRESHOLD == 10
    assert AppSettings().large_campaign_threshold == 50
    with pytest.raises(SettingsValidationError):
        AppSettings(large_campaign_threshold=9).validate()
    AppSettings(large_campaign_threshold=10).validate()
    repo = SettingsRepository(Database(tmp_path / "app.db"))
    assert repo.load_app_settings().large_campaign_threshold == 50
    settings = repo.load_app_settings()
    settings.large_campaign_threshold = 120
    repo.save_app_settings(settings)
    assert repo.load_app_settings().large_campaign_threshold == 120


async def test_threshold_lives_on_the_sending_settings_page(qapp, tmp_path):
    window = MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))
    spin = window._large_campaign_spin
    assert spin.value() == 50
    assert spin.minimum() == 10
    spin.setValue(75)
    spin.editingFinished.emit()
    assert window._service.settings_repository.load_app_settings().large_campaign_threshold == 75
    spin.setValue(3)  # clamped by the spin box itself
    assert spin.value() == 10


# ---- every start path ---------------------------------------------------------------


@pytest.mark.parametrize("path", sorted(PATHS))
@pytest.mark.parametrize("confirm_before_start", [False, True])
async def test_more_than_threshold_always_asks_and_cancel_stops(qapp, tmp_path, path, confirm_before_start):
    window = await _window(tmp_path, confirm_before_start=confirm_before_start)
    with patch.object(window, "_start_campaign", new=AsyncMock()) as start, patch(
        "app.ui.main_window.confirm_large_campaign", return_value=False
    ) as large, patch("app.ui.main_window.confirm_start_campaign", return_value=True) as normal:
        PATHS[path](window, 51)
        await asyncio.sleep(0)
    large.assert_called_once()
    normal.assert_not_called()  # one question, not two
    breakdown, threshold = large.call_args[0][1:]
    assert threshold == 50 and breakdown.total == 51
    assert (breakdown.chats, breakdown.unknown, breakdown.people) == (6, 5, 40)
    start.assert_not_called()
    assert window._campaign_starting is False


@pytest.mark.parametrize("path", sorted(PATHS))
async def test_confirmed_large_campaign_starts(qapp, tmp_path, path):
    window = await _window(tmp_path)
    with patch.object(window, "_start_campaign", new=AsyncMock()) as start, patch(
        "app.ui.main_window.confirm_large_campaign", return_value=True
    ) as large:
        PATHS[path](window, 60)
        await asyncio.sleep(0)
    large.assert_called_once()
    start.assert_called_once()
    assert len(start.call_args[0][1]) == 60


@pytest.mark.parametrize("path", sorted(PATHS))
async def test_at_threshold_no_extra_question(qapp, tmp_path, path):
    window = await _window(tmp_path)
    with patch.object(window, "_start_campaign", new=AsyncMock()) as start, patch(
        "app.ui.main_window.confirm_large_campaign"
    ) as large, patch("app.ui.main_window.confirm_start_campaign") as normal:
        PATHS[path](window, 50)
        await asyncio.sleep(0)
    large.assert_not_called()
    normal.assert_not_called()  # the optional confirmation is off
    start.assert_called_once()


@pytest.mark.parametrize("path", sorted(PATHS))
async def test_optional_confirmation_still_applies_below_threshold(qapp, tmp_path, path):
    window = await _window(tmp_path, confirm_before_start=True)
    with patch.object(window, "_start_campaign", new=AsyncMock()) as start, patch(
        "app.ui.main_window.confirm_large_campaign"
    ) as large, patch("app.ui.main_window.confirm_start_campaign", return_value=False) as normal:
        PATHS[path](window, 12)
        await asyncio.sleep(0)
    large.assert_not_called()
    normal.assert_called_once()
    start.assert_not_called()


async def test_custom_threshold(qapp, tmp_path):
    window = await _window(tmp_path, threshold=10)
    with patch.object(window, "_start_campaign", new=AsyncMock()), patch(
        "app.ui.main_window.confirm_large_campaign", return_value=False
    ) as large:
        _start_from_page(window, 10)
        large.assert_not_called()
        window._campaign_starting = False  # the mocked start never finishes
        _start_from_page(window, 11)
    large.assert_called_once()
    assert large.call_args[0][2] == 10


# ---- the dialog itself ------------------------------------------------------------------


def test_large_campaign_box_defaults_to_cancel(qapp):
    theme.apply_theme(qapp, theme.get_active_theme())
    box, start, cancel = build_large_campaign_box(None, RecipientBreakdown(people=40, bots=3, chats=8, unknown=2), 50)
    assert start.property("variant") == "danger"
    assert box.defaultButton() is cancel
    assert box.escapeButton() is cancel
    box.show()
    QApplication.processEvents()
    assert QApplication.focusWidget() is cancel
    # Styled as danger for real, not just tagged: the box polishes its
    # buttons when they're added, before the variant is set.
    error = QColor(theme.current_tokens().error).name()
    assert start.palette().color(QPalette.ColorRole.ButtonText).name() == error
    assert cancel.palette().color(QPalette.ColorRole.ButtonText).name() != error
    text = box.informativeText()
    for line in (
        tr("dialogs.large_campaign.people_line", count=40),
        tr("dialogs.large_campaign.bots_line", count=3),
        tr("dialogs.large_campaign.chats_line", count=8),
        tr("dialogs.large_campaign.unknown_line", count=2),
    ):
        assert line in text
    assert box.text() == tr("dialogs.large_campaign.message", count=53, threshold=50)
    box.hide()


def test_large_campaign_box_always_lists_people_bots_and_chats(qapp):
    box, _start, _cancel = build_large_campaign_box(None, RecipientBreakdown(people=60), 50)
    text = box.informativeText()
    assert tr("dialogs.large_campaign.bots_line", count=0) in text
    assert tr("dialogs.large_campaign.chats_line", count=0) in text
    assert tr("dialogs.large_campaign.unknown_line", count=0) not in text
    assert box.icon() == QMessageBox.Icon.Warning
