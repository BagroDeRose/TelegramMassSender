"""Regression tests for the account-switching UI-sync bug: clicking
"Использовать" successfully changed AccountManager.active_account_id (the
backend log confirmed it), but AccountWidget's rendered cards were never
told to resync -- app.ui.main_window._on_account_selected only called
AccountWidget.select_account() on the *failure* path, never on success.
Fixed by app.ui.main_window._switch_account, which always resyncs via
AccountWidget.refresh_active_state() on both outcomes.

Uses a real AccountManager (backed by the window's actual AccountRepository,
so persistence assertions are meaningful) with a FakeClientManager standing
in for Telethon -- no real Telegram network involved.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from app.database.database import Database
from app.telegram.account_manager import AccountManager
from app.ui.main_window import MainWindow
from tests.mocks.fake_client_manager import FakeClientManager


async def _make_window(tmp_path: Path) -> MainWindow:
    window = MainWindow(database=Database(tmp_path / "app.db"))
    # MainWindow.__init__ fire-and-forgets asyncio.ensure_future(self.
    # _refresh_accounts()) (account_manager is None at construction time,
    # before any test installs a fake one). That task hasn't run yet --
    # merely scheduled -- so without draining it here, it can wake up at
    # *any* later `await` in a test (once account_manager has since been
    # replaced) and race with the test's own explicit calls. One yield is
    # enough: with account_manager still None, _refresh_accounts returns
    # immediately with no further await points, so this fully drains it.
    await asyncio.sleep(0)
    return window


def _install_account_manager(window: MainWindow, client_manager=None):
    client_manager = client_manager or FakeClientManager()
    manager = AccountManager(window._service.account_repository, client_manager)
    window._service.account_manager = manager
    return manager, client_manager


async def _register_two_authorized_accounts(window):
    manager, client_manager = _install_account_manager(window)
    account_a = manager.register_account("+70001112233")
    account_b = manager.register_account("+70004445566")
    client_manager.authorized_sessions.update([account_a.session_name, account_b.session_name])
    await window._refresh_accounts()
    return manager, client_manager, account_a, account_b


# ---- 1-4: the core reported bug ---------------------------------------------


async def test_use_button_changes_active_account(qapp, tmp_path):
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)
    assert manager.active_account_id == account_a.id

    await window._switch_account(account_b.id)

    assert manager.active_account_id == account_b.id


async def test_account_cards_resync_after_successful_switch(qapp, tmp_path):
    # The actual regression: AccountWidget must be told to rebuild its
    # cards on the SUCCESS path too, not just on failure.
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)

    await window._switch_account(account_b.id)

    assert window._account_widget.current_account_id() == account_b.id
    use_button_b = next(
        b for b in window._account_widget._use_buttons if b.property("accountId") == account_b.id
    )
    use_button_a = next(
        b for b in window._account_widget._use_buttons if b.property("accountId") == account_a.id
    )
    assert use_button_b.text() == "Активен"
    assert use_button_b.isEnabled() is False
    assert use_button_a.text() == "Использовать"
    assert use_button_a.isEnabled() is True


async def test_exactly_one_account_marked_active(qapp, tmp_path):
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)

    await window._switch_account(account_b.id)

    active_cards = [card for card in window._account_widget._cards if card.property("active") == "true"]
    assert len(active_cards) == 1


async def test_status_bar_updates_to_new_account(qapp, tmp_path):
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)
    assert "70001112233" in window._connection_status_label.text() or account_a.phone in window._connection_status_label.text()

    await window._switch_account(account_b.id)

    assert account_b.phone in window._connection_status_label.text()
    assert account_a.phone not in window._connection_status_label.text()


# ---- 5: A -> B -> A -----------------------------------------------------------


async def test_switch_a_to_b_to_a(qapp, tmp_path):
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)

    await window._switch_account(account_b.id)
    assert manager.active_account_id == account_b.id
    assert window._account_widget.current_account_id() == account_b.id

    await window._switch_account(account_a.id)
    assert manager.active_account_id == account_a.id
    assert window._account_widget.current_account_id() == account_a.id
    assert account_a.phone in window._connection_status_label.text()


# ---- 6: failed switch restores previous state --------------------------------


async def test_failed_switch_restores_previous_active_state(qapp, tmp_path):
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)
    manager.set_switch_guard(lambda: False)  # simulate "campaign is running"

    with patch("app.ui.main_window.show_error") as mock_show_error:
        await window._switch_account(account_b.id)
        mock_show_error.assert_called_once()

    assert manager.active_account_id == account_a.id
    assert window._account_widget.current_account_id() == account_a.id
    use_button_a = next(
        b for b in window._account_widget._use_buttons if b.property("accountId") == account_a.id
    )
    assert use_button_a.text() == "Активен"


async def test_unexpected_exception_during_switch_shows_friendly_error_and_restores_state(qapp, tmp_path):
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)

    def _boom(_account_id):
        raise RuntimeError("technical detail that must not reach the dialog")

    manager.switch_active_account = _boom  # type: ignore[method-assign]

    with patch("app.ui.main_window.show_error") as mock_show_error:
        await window._switch_account(account_b.id)
        mock_show_error.assert_called_once()
        _parent, title, message = mock_show_error.call_args[0]
        assert "technical detail" not in message
        assert "Не удалось переключить аккаунт" in message

    assert window._account_widget.current_account_id() == account_a.id


# ---- 7: duplicate switching prevented ----------------------------------------


async def test_duplicate_switch_clicks_are_ignored_while_in_flight(qapp, tmp_path):
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)

    # Two rapid clicks before the event loop ever runs _switch_account --
    # both must be seen by the guard, not just the second one to start.
    window._on_account_selected(account_b.id)
    window._on_account_selected(account_a.id)  # must be ignored: a switch is already in flight
    assert window._account_switch_in_progress is True

    await asyncio.sleep(0.05)  # let the scheduled coroutine(s) run to completion

    assert manager.active_account_id == account_b.id  # the first click won, second was a no-op
    assert window._account_switch_in_progress is False


async def test_switch_in_progress_flag_cleared_after_completion(qapp, tmp_path):
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)

    await window._switch_account(account_b.id)

    assert window._account_switch_in_progress is False
    # A subsequent switch must work normally -- the guard isn't stuck "on".
    await window._switch_account(account_a.id)
    assert manager.active_account_id == account_a.id


# ---- 8: persists across restart -----------------------------------------------


async def test_active_account_persists_across_restart(qapp, tmp_path):
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)

    await window._switch_account(account_b.id)
    settings = window._service.settings_repository.load_app_settings()
    assert settings.active_account_id == account_b.id

    # Simulate a full restart: a brand-new MainWindow against the same DB,
    # with a freshly (re)installed AccountManager (mirroring how a real
    # restart always creates a brand-new AccountManager with no memory of
    # its own -- app.telegram.service.TelegramService is reconstructed on
    # every launch, so the *only* thing that can restore the previous
    # choice is the persisted setting asserted above).
    reopened = await _make_window(tmp_path)
    manager2, client_manager2 = _install_account_manager(reopened)
    client_manager2.authorized_sessions.update([account_a.session_name, account_b.session_name])
    await reopened._refresh_accounts()

    assert manager2.active_account_id == account_b.id
    assert reopened._account_widget.current_account_id() == account_b.id


# ---- 9: campaign uses the newly selected account -----------------------------


async def test_active_account_resolution_reflects_switch(qapp, tmp_path):
    # This is exactly what app.ui.main_window._on_start_requested /
    # _start_campaign read at Start-click time -- proving it resolves to
    # the newly switched account is what guarantees the campaign uses it.
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)
    assert window._active_account().id == account_a.id

    await window._switch_account(account_b.id)

    assert window._active_account().id == account_b.id
    assert window._active_account().phone == account_b.phone


# ---- 10: does not block the event loop ----------------------------------------


async def test_switch_does_not_block_other_scheduled_work(qapp, tmp_path):
    window = await _make_window(tmp_path)
    manager, _client, account_a, account_b = await _register_two_authorized_accounts(window)

    other_ran = []

    async def other_task():
        other_ran.append(True)

    switch_future = asyncio.ensure_future(window._switch_account(account_b.id))
    other_future = asyncio.ensure_future(other_task())
    await asyncio.wait_for(asyncio.gather(switch_future, other_future), timeout=2)

    assert other_ran == [True]
    assert manager.active_account_id == account_b.id
