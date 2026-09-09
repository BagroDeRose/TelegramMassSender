"""Regression tests for app.telegram.account_manager.AccountManager.

No prior coverage existed for this module (confirmed before writing these).
The specific regression this guards: AccountManager.check_status() used to
catch every exception identically and report "needs re-authorization" --
which made a perfectly valid, still-persisted account look broken/gone
after a transient network blip. See check_status's docstring for the fix.
"""
from __future__ import annotations

import asyncio

import pytest

from app.database.database import Database
from app.database.repositories import AccountRepository
from app.telegram.account_manager import AccountManager, AccountStatus
from app.telegram.exceptions import AccountSwitchBlockedError
from tests.mocks.fake_client_manager import FakeClientManager


@pytest.fixture
def repo(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    yield AccountRepository(db)
    db.close()


def make_manager(repo, client_manager=None):
    return AccountManager(repo, client_manager or FakeClientManager())


def test_register_account_creates_row(repo):
    manager = make_manager(repo)
    account = manager.register_account("+70001112233")
    assert account.id is not None
    assert account.phone == "+70001112233"
    assert repo.get_by_id(account.id) is not None


def test_register_account_is_idempotent_by_phone(repo):
    manager = make_manager(repo)
    first = manager.register_account("+70001112233")
    second = manager.register_account("+70001112233")
    assert first.id == second.id
    assert len(repo.list_all()) == 1


async def test_check_status_authorized(repo):
    client_manager = FakeClientManager()
    manager = make_manager(repo, client_manager)
    account = manager.register_account("+70001112233")
    client_manager.authorized_sessions.add(account.session_name)

    status = await manager.check_status(account)
    assert status.is_authorized is True
    assert status.needs_reauth is False
    assert status.connection_error is False


async def test_check_status_genuinely_unauthorized_is_needs_reauth(repo):
    client_manager = FakeClientManager()
    manager = make_manager(repo, client_manager)
    account = manager.register_account("+70001112233")
    # Not added to authorized_sessions -> is_user_authorized() returns False cleanly.

    status = await manager.check_status(account)
    assert status.is_authorized is False
    assert status.needs_reauth is True
    assert status.connection_error is False


async def test_check_status_transient_network_error_is_connection_error_not_reauth(repo):
    """The regression test: a ConnectionError/OSError/TimeoutError while
    checking status must be reported as connection_error, never as
    needs_reauth -- this is exactly the bug that made a valid account look
    like it had disappeared after a flaky connection."""
    client_manager = FakeClientManager()
    manager = make_manager(repo, client_manager)
    account = manager.register_account("+70001112233")
    client_manager.raise_on_check[account.session_name] = ConnectionError("network down")

    status = await manager.check_status(account)
    assert status.connection_error is True
    assert status.needs_reauth is False
    assert status.is_authorized is False


async def test_check_status_timeout_error_is_connection_error(repo):
    client_manager = FakeClientManager()
    manager = make_manager(repo, client_manager)
    account = manager.register_account("+70001112233")
    client_manager.raise_on_check[account.session_name] = asyncio.TimeoutError()

    status = await manager.check_status(account)
    assert status.connection_error is True
    assert status.needs_reauth is False


async def test_check_status_unexpected_error_still_falls_back_to_needs_reauth(repo):
    # Anything that ISN'T a recognized transient-connectivity error keeps
    # the old, more conservative behavior -- surfaced as needs_reauth
    # rather than silently treated as "just a blip."
    client_manager = FakeClientManager()
    manager = make_manager(repo, client_manager)
    account = manager.register_account("+70001112233")
    client_manager.raise_on_check[account.session_name] = RuntimeError("something else broke")

    status = await manager.check_status(account)
    assert status.needs_reauth is True
    assert status.connection_error is False


async def test_list_accounts_with_status_never_drops_a_row(repo):
    """A connection-error or needs-reauth account must still appear in the
    list -- it must never look "deleted" just because its last check
    failed."""
    client_manager = FakeClientManager()
    manager = make_manager(repo, client_manager)
    good = manager.register_account("+70001112233")
    flaky = manager.register_account("+70004445566")
    client_manager.authorized_sessions.add(good.session_name)
    client_manager.raise_on_check[flaky.session_name] = ConnectionError("down")

    statuses = await manager.list_accounts_with_status()
    assert len(statuses) == 2
    ids = {s.account.id for s in statuses}
    assert ids == {good.id, flaky.id}
    flaky_status = next(s for s in statuses if s.account.id == flaky.id)
    assert flaky_status.connection_error is True


async def test_check_status_failure_does_not_touch_database(repo):
    """A failed status check -- of any kind -- must never delete or modify
    the account's DB row (the actual regression the user reported)."""
    client_manager = FakeClientManager()
    manager = make_manager(repo, client_manager)
    account = manager.register_account("+70001112233")
    client_manager.raise_on_check[account.session_name] = ConnectionError("down")

    await manager.check_status(account)

    reloaded = repo.get_by_id(account.id)
    assert reloaded is not None
    assert reloaded.phone == account.phone


async def test_delete_account_removes_only_that_account(repo):
    client_manager = FakeClientManager()
    manager = make_manager(repo, client_manager)
    keep = manager.register_account("+70001112233")
    remove = manager.register_account("+70004445566")

    await manager.delete_account(remove)

    assert repo.get_by_id(remove.id) is None
    assert repo.get_by_id(keep.id) is not None
    assert remove.session_name in client_manager.removed


async def test_delete_account_clears_active_account_id_if_it_was_active(repo):
    client_manager = FakeClientManager()
    manager = make_manager(repo, client_manager)
    account = manager.register_account("+70001112233")
    manager.switch_active_account(account.id)
    assert manager.active_account_id == account.id

    await manager.delete_account(account)

    assert manager.active_account_id is None


def test_switch_active_account_blocked_by_guard_does_not_change_state(repo):
    manager = make_manager(repo)
    account = manager.register_account("+70001112233")
    manager.switch_active_account(account.id)

    other = manager.register_account("+70004445566")
    manager.set_switch_guard(lambda: False)
    with pytest.raises(AccountSwitchBlockedError):
        manager.switch_active_account(other.id)

    assert manager.active_account_id == account.id
