"""UI-level tests for the first-run OnboardingDialog and Demo Mode wiring
in MainWindow (ROADMAP v2.0). Covers what tests/test_demo_mode.py does
not: the dialog itself, and MainWindow's reaction to each of its outcomes
(the underlying TelegramService.enter_demo_mode/exit_demo_mode and
DemoTelegramClient/DemoClientManager are covered there).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QDialog

from app.database.database import Database
from app.security.secure_storage import SecureStorage
from app.ui.main_window import MainWindow
from app.ui.onboarding_dialog import ACTION_GET_STARTED, ACTION_SKIP, ACTION_TRY_DEMO, OnboardingDialog


def _make_window(tmp_path: Path) -> MainWindow:
    # Isolated SecureStorage: this suite's own dev machine has real,
    # actual stored Telegram API credentials from genuine prior app use
    # (see TelegramService.secure_storage's docstring) -- without this,
    # onboarding-skip tests below would run against whatever real
    # configuration state happens to exist on whatever machine runs them.
    storage = SecureStorage(tmp_path / "secrets.dat")
    return MainWindow(database=Database(tmp_path / "app.db"), secure_storage=storage)


# ---- OnboardingDialog itself -------------------------------------------------


def test_onboarding_dialog_defaults_to_skip_if_closed_without_a_button(qapp):
    dialog = OnboardingDialog()
    assert dialog.action == ACTION_SKIP


def test_get_started_button_sets_the_action_and_accepts(qapp):
    dialog = OnboardingDialog()
    dialog._get_started_button.click()
    assert dialog.action == ACTION_GET_STARTED
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_try_demo_button_sets_the_action_and_accepts(qapp):
    dialog = OnboardingDialog()
    dialog._demo_button.click()
    assert dialog.action == ACTION_TRY_DEMO


def test_skip_button_sets_the_action_and_accepts(qapp):
    dialog = OnboardingDialog()
    dialog._get_started_button.click()  # change it away from the default first
    dialog._skip_button.click()
    assert dialog.action == ACTION_SKIP


# ---- MainWindow.maybe_show_onboarding ----------------------------------------


async def test_onboarding_shown_on_first_run_with_a_fresh_database(qapp, tmp_path):
    window = _make_window(tmp_path)
    with patch("app.ui.main_window.OnboardingDialog") as mock_dialog_cls:
        instance = mock_dialog_cls.return_value
        instance.action = ACTION_SKIP
        window.maybe_show_onboarding()
    instance.exec.assert_called_once()


async def test_onboarding_not_shown_again_once_completed(qapp, tmp_path):
    window = _make_window(tmp_path)
    settings = window._service.settings_repository.load_app_settings()
    settings.onboarding_completed = True
    window._service.settings_repository.save_app_settings(settings)

    with patch("app.ui.main_window.OnboardingDialog") as mock_dialog_cls:
        window.maybe_show_onboarding()
    mock_dialog_cls.assert_not_called()


async def test_onboarding_persists_completed_regardless_of_which_action_was_chosen(qapp, tmp_path):
    window = _make_window(tmp_path)
    with patch("app.ui.main_window.OnboardingDialog") as mock_dialog_cls:
        instance = mock_dialog_cls.return_value
        instance.action = ACTION_SKIP
        window.maybe_show_onboarding()

    reloaded = window._service.settings_repository.load_app_settings()
    assert reloaded.onboarding_completed is True


async def test_onboarding_get_started_opens_the_login_dialog(qapp, tmp_path):
    window = _make_window(tmp_path)
    with patch("app.ui.main_window.OnboardingDialog") as mock_onboarding_cls:
        instance = mock_onboarding_cls.return_value
        instance.action = ACTION_GET_STARTED
        with patch.object(window, "_on_add_account_requested") as mock_add_account:
            window.maybe_show_onboarding()
    mock_add_account.assert_called_once()


async def test_onboarding_try_demo_activates_demo_mode(qapp, tmp_path):
    window = _make_window(tmp_path)
    with patch("app.ui.main_window.OnboardingDialog") as mock_onboarding_cls:
        instance = mock_onboarding_cls.return_value
        instance.action = ACTION_TRY_DEMO
        window.maybe_show_onboarding()

    assert window._service.is_demo_mode is True
    assert window._demo_banner.isHidden() is False


async def test_onboarding_skip_does_not_activate_demo_mode_or_open_login(qapp, tmp_path):
    window = _make_window(tmp_path)
    with patch("app.ui.main_window.OnboardingDialog") as mock_onboarding_cls:
        instance = mock_onboarding_cls.return_value
        instance.action = ACTION_SKIP
        with patch.object(window, "_on_add_account_requested") as mock_add_account:
            window.maybe_show_onboarding()
    mock_add_account.assert_not_called()
    assert window._service.is_demo_mode is False


# ---- Demo Mode entry points and banner ---------------------------------------


async def test_try_demo_mode_button_on_accounts_page_activates_demo_mode(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert window._demo_banner.isHidden() is True

    window._account_widget.try_demo_mode_requested.emit()

    assert window._service.is_demo_mode is True
    assert window._demo_banner.isHidden() is False


async def test_demo_mode_seeds_and_selects_a_demo_account(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._enter_demo_mode()

    account = window._service.account_repository.get_by_id(window._service.account_manager.active_account_id)
    assert account is not None
    assert account.display_name == "Demo Account"


async def test_exit_demo_mode_hides_the_banner_and_clears_the_flag(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._enter_demo_mode()
    assert window._demo_banner.isHidden() is False

    window._on_exit_demo_mode_clicked()

    assert window._service.is_demo_mode is False
    assert window._demo_banner.isHidden() is True


async def test_try_demo_mode_blocked_while_a_campaign_is_active(qapp, tmp_path):
    from unittest.mock import MagicMock

    window = _make_window(tmp_path)
    fake_campaign = MagicMock()
    fake_campaign.is_active = True
    window._current_campaign = fake_campaign

    with patch("app.ui.main_window.show_error") as mock_show_error:
        window._on_try_demo_mode_requested()

    assert window._service.is_demo_mode is False
    mock_show_error.assert_called_once()


async def test_exit_demo_mode_blocked_while_a_campaign_is_active(qapp, tmp_path):
    from unittest.mock import MagicMock

    window = _make_window(tmp_path)
    window._enter_demo_mode()
    fake_campaign = MagicMock()
    fake_campaign.is_active = True
    window._current_campaign = fake_campaign

    with patch("app.ui.main_window.show_error") as mock_show_error:
        window._on_exit_demo_mode_clicked()

    # Still in demo mode -- the exit was blocked, not silently ignored.
    assert window._service.is_demo_mode is True
    mock_show_error.assert_called_once()
