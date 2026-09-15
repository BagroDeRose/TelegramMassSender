"""Post-v2.0.0 regression tests for the account/session/demo-mode
lifecycle bugs found by real manual use of the shipped v2.0.0 build:

  - Demo Mode persisted a fake account into the real account list and
    never removed it
  - leaving Demo Mode rebuilt the client manager, orphaning every live
    Telethon client (open session files -> "database is locked") and
    losing the ability to switch accounts
  - deleting an account raced a concurrent status refresh that reopened
    the session file, failing with WinError 32
  - that failure reached the terminal only as an unobserved
    "Task exception was never retrieved"

Everything here is isolated: a temp Database and a temp SecureStorage, so
no test reads or writes the machine's real DPAPI credential store, real
app.db, or real session directory.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from app.database.database import Database
from app.database.repositories import AccountRepository
from app.security.secure_storage import SecureStorage
from app.telegram.account_manager import AccountManager, AccountStatus
from app.telegram.client_manager import ClientManager
from app.telegram.demo_client import DEMO_ACCOUNT_PHONE
from app.telegram.exceptions import AccountDeletionError
from app.telegram.service import TelegramService

SYNTHETIC_API_ID = 1111111
SYNTHETIC_API_HASH = "0" * 32


def _service(tmp_path: Path, *, with_credentials: bool) -> TelegramService:
    database = Database(db_path=tmp_path / "app.db")
    database.connect()
    storage = SecureStorage(tmp_path / "secrets.dat")
    if with_credentials:
        storage.save_api_credentials(SYNTHETIC_API_ID, SYNTHETIC_API_HASH)
    return TelegramService(database, secure_storage=storage)


# ---- Demo Mode must not contaminate the real account list -------------------


def test_demo_account_is_removed_from_the_real_account_list_on_exit(tmp_path):
    # v2.0.0 registered "+10000000000" into the real accounts table and
    # never deleted it. The leftover row was then treated as a real
    # account: the next refresh built a genuine Telethon client for it and
    # tried to connect, creating a real session file and a stream of
    # connection errors.
    service = _service(tmp_path, with_credentials=True)
    assert service.account_repository.list_all() == []

    service.enter_demo_mode()
    phones_in_demo = [a.phone for a in service.account_repository.list_all()]
    assert DEMO_ACCOUNT_PHONE in phones_in_demo

    service.exit_demo_mode()
    assert [a.phone for a in service.account_repository.list_all()] == []


def test_a_demo_account_left_over_from_a_previous_run_is_purged_at_startup(tmp_path):
    # Upgrade path: a v2.0.0 install (or a crash during demo mode) leaves
    # the row behind, and the user never asked for it.
    database = Database(db_path=tmp_path / "app.db")
    database.connect()
    AccountRepository(database).create(DEMO_ACCOUNT_PHONE, "account_stale_demo")
    storage = SecureStorage(tmp_path / "secrets.dat")

    service = TelegramService(database, secure_storage=storage)

    assert [a.phone for a in service.account_repository.list_all()] == []
    assert service.is_demo_mode is False


def test_demo_mode_never_touches_stored_api_credentials(tmp_path):
    service = _service(tmp_path, with_credentials=True)
    before = service.secure_storage.load_api_credentials()

    service.enter_demo_mode()
    during = service.secure_storage.load_api_credentials()
    service.exit_demo_mode()
    after = service.secure_storage.load_api_credentials()

    assert before is not None
    assert (during.api_id, during.api_hash) == (before.api_id, before.api_hash)
    assert (after.api_id, after.api_hash) == (before.api_id, before.api_hash)


def test_real_accounts_survive_a_demo_mode_round_trip(tmp_path):
    service = _service(tmp_path, with_credentials=True)
    real = service.account_repository.create("+70000000001", "account_real_one")

    service.enter_demo_mode()
    service.exit_demo_mode()

    remaining = service.account_repository.list_all()
    assert [a.phone for a in remaining] == [real.phone]
    assert remaining[0].session_name == "account_real_one"


# ---- leaving Demo Mode must restore a usable account manager ----------------


def test_leaving_demo_mode_restores_the_same_client_manager_instance(tmp_path):
    # Rebuilding it orphaned every live TelegramClient: their session files
    # stayed open while the new manager opened a second sqlite connection
    # to the same file, which is what produced "database is locked".
    service = _service(tmp_path, with_credentials=True)
    real_manager = service._client_manager
    real_account_manager = service.account_manager
    assert real_manager is not None

    service.enter_demo_mode()
    assert service._client_manager is not real_manager

    service.exit_demo_mode()
    assert service._client_manager is real_manager
    assert service.account_manager is real_account_manager


def test_account_manager_is_usable_again_after_leaving_demo_mode(tmp_path):
    service = _service(tmp_path, with_credentials=True)
    account = service.account_repository.create("+70000000002", "account_real_two")

    service.enter_demo_mode()
    service.exit_demo_mode()

    assert service.account_manager is not None
    service.account_manager.switch_active_account(account.id)
    assert service.account_manager.active_account_id == account.id


def test_live_clients_are_not_orphaned_by_a_demo_round_trip(tmp_path):
    # A real client is expensive to build here, so a sentinel stands in for
    # one: what matters is whether the manager that owns it is still the
    # one the service uses afterwards. If the service rebuilt the manager,
    # this client would be unreachable and its session file would stay open
    # with nothing able to close it -- the "database is locked" path.
    service = _service(tmp_path, with_credentials=True)
    manager = service._client_manager
    live_client = object()
    manager._clients["account_live"] = live_client

    service.enter_demo_mode()
    assert service._client_manager is not manager  # demo manager is in use

    service.exit_demo_mode()

    assert service._client_manager is manager
    assert service._client_manager._clients["account_live"] is live_client


@pytest.mark.parametrize("repetitions", [1, 3])
def test_repeated_demo_transitions_are_stable(tmp_path, repetitions):
    service = _service(tmp_path, with_credentials=True)
    real = service.account_repository.create("+70000000003", "account_real_three")
    real_manager = service._client_manager

    for _ in range(repetitions):
        service.enter_demo_mode()
        assert service.is_demo_mode is True
        service.exit_demo_mode()
        assert service.is_demo_mode is False

    assert service._client_manager is real_manager
    assert [a.phone for a in service.account_repository.list_all()] == [real.phone]
    service.account_manager.switch_active_account(real.id)
    assert service.account_manager.active_account_id == real.id


def test_entering_demo_mode_twice_does_not_stack_saved_managers(tmp_path):
    # Re-entering must not overwrite the saved real manager with the demo
    # one, which would make the next exit restore a DemoClientManager as
    # if it were the real one.
    service = _service(tmp_path, with_credentials=True)
    real_manager = service._client_manager

    service.enter_demo_mode()
    service.enter_demo_mode()
    service.exit_demo_mode()

    assert service._client_manager is real_manager
    assert service.is_demo_mode is False


def test_exit_demo_mode_is_a_no_op_when_demo_mode_was_never_entered(tmp_path):
    service = _service(tmp_path, with_credentials=True)
    real_manager = service._client_manager
    real = service.account_repository.create("+70000000004", "account_real_four")

    service.exit_demo_mode()

    assert service._client_manager is real_manager
    assert [a.phone for a in service.account_repository.list_all()] == [real.phone]


# ---- account deletion / session file lifecycle ------------------------------


class _StubClientManager:
    """Only the surface AccountManager.delete_account actually uses."""

    def __init__(self) -> None:
        self.calls = []
        self.clients = {}

    async def log_out(self, session_name):
        self.calls.append(("log_out", session_name))

    async def disconnect(self, session_name):
        self.calls.append(("disconnect", session_name))

    def remove(self, session_name):
        self.calls.append(("remove", session_name))
        self.clients.pop(session_name, None)


def _account_manager(tmp_path, sessions_dir):
    database = Database(db_path=tmp_path / "app.db")
    database.connect()
    repo = AccountRepository(database)
    client_manager = _StubClientManager()
    manager = AccountManager(repo, client_manager)
    return manager, repo, client_manager


@pytest.mark.asyncio
async def test_delete_account_logs_out_disconnects_and_removes_before_unlinking(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    manager, repo, client_manager = _account_manager(tmp_path, sessions)
    account = repo.create("+70000000010", "account_del")
    session_file = sessions / "account_del.session"
    session_file.write_bytes(b"fake session")

    with patch("app.telegram.account_manager.get_session_path", lambda name: sessions / name):
        await manager.delete_account(account)

    assert [c[0] for c in client_manager.calls] == ["log_out", "disconnect", "remove"]
    assert session_file.exists() is False
    assert repo.get_by_id(account.id) is None


@pytest.mark.asyncio
async def test_delete_account_retries_a_transient_windows_file_lock(tmp_path):
    # Windows can still report the handle open for a moment after Telethon
    # closed it. A short bounded retry must ride that out rather than
    # failing the delete outright.
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    manager, repo, _ = _account_manager(tmp_path, sessions)
    account = repo.create("+70000000011", "account_retry")
    session_file = sessions / "account_retry.session"
    session_file.write_bytes(b"fake session")

    attempts = {"n": 0}
    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "account_retry.session":
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise PermissionError(32, "The process cannot access the file")
        return real_unlink(self, *args, **kwargs)

    with patch("app.telegram.account_manager.get_session_path", lambda name: sessions / name):
        with patch.object(Path, "unlink", flaky_unlink):
            await manager.delete_account(account)

    assert attempts["n"] == 3
    assert session_file.exists() is False
    assert repo.get_by_id(account.id) is None


@pytest.mark.asyncio
async def test_delete_account_raises_a_clear_error_when_the_lock_never_clears(tmp_path):
    # Bounded, not infinite: a permanently locked file must surface as a
    # real error the UI can show, never a silent failure and never a hang.
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    manager, repo, _ = _account_manager(tmp_path, sessions)
    account = repo.create("+70000000012", "account_locked")
    session_file = sessions / "account_locked.session"
    session_file.write_bytes(b"fake session")

    def always_locked(self, *args, **kwargs):
        raise PermissionError(32, "The process cannot access the file")

    with patch("app.telegram.account_manager.get_session_path", lambda name: sessions / name):
        with patch.object(Path, "unlink", always_locked):
            with pytest.raises(AccountDeletionError):
                await manager.delete_account(account)


@pytest.mark.asyncio
async def test_delete_account_with_no_session_file_on_disk_still_succeeds(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    manager, repo, _ = _account_manager(tmp_path, sessions)
    account = repo.create("+70000000013", "account_nofile")

    with patch("app.telegram.account_manager.get_session_path", lambda name: sessions / name):
        await manager.delete_account(account)

    assert repo.get_by_id(account.id) is None


@pytest.mark.asyncio
async def test_deleting_the_active_account_clears_the_active_id(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    manager, repo, _ = _account_manager(tmp_path, sessions)
    account = repo.create("+70000000014", "account_active")
    manager.switch_active_account(account.id)

    with patch("app.telegram.account_manager.get_session_path", lambda name: sessions / name):
        await manager.delete_account(account)

    assert manager.active_account_id is None


# ---- ClientManager.remove must release the session file ---------------------


def test_remove_closes_the_session_so_the_file_can_be_deleted(tmp_path):
    # Dropping the client from the dict is not enough on Windows: the
    # Telethon SQLiteSession holds an open sqlite connection from the
    # moment the client is constructed, and that handle is what makes
    # unlink() fail with WinError 32.
    session_base = tmp_path / "account_close_me"
    manager = ClientManager(SYNTHETIC_API_ID, SYNTHETIC_API_HASH)
    with patch("app.telegram.client_manager.get_session_path", lambda name: tmp_path / name):
        client = manager.get_or_create("account_close_me")
    session_file = Path(str(session_base) + ".session")
    assert session_file.exists()

    closed = {"n": 0}
    real_close = client.session.close

    def counting_close():
        closed["n"] += 1
        return real_close()

    client.session.close = counting_close
    manager.remove("account_close_me")

    assert closed["n"] == 1
    assert "account_close_me" not in manager._clients
    session_file.unlink()  # must now be possible


def test_remove_is_safe_for_an_unknown_session(tmp_path):
    manager = ClientManager(SYNTHETIC_API_ID, SYNTHETIC_API_HASH)
    manager.remove("never_created")  # must not raise


def test_remove_survives_a_session_that_fails_to_close(tmp_path):
    manager = ClientManager(SYNTHETIC_API_ID, SYNTHETIC_API_HASH)

    class _Boom:
        def close(self):
            raise RuntimeError("cannot close")

    class _Client:
        session = _Boom()

    manager._clients["account_boom"] = _Client()
    manager.remove("account_boom")  # logged, never raised
    assert "account_boom" not in manager._clients


# ---- a locked session database must not look like a logged-out account ------


@pytest.mark.asyncio
async def test_a_locked_session_database_is_reported_as_a_connection_problem(tmp_path):
    # "database is locked" comes from Telethon's own session file under
    # contention. It is a timing problem, not an authorization one -- the
    # account is fine and the fix is to retry. Reporting it as
    # needs_reauth made a perfectly valid account look broken.
    database = Database(db_path=tmp_path / "app.db")
    database.connect()
    repo = AccountRepository(database)
    account = repo.create("+70000000020", "account_locked_db")

    class _LockedClientManager:
        async def is_authorized(self, session_name):
            raise sqlite3.OperationalError("database is locked")

    manager = AccountManager(repo, _LockedClientManager())
    status = await manager.check_status(account)

    assert isinstance(status, AccountStatus)
    assert status.connection_error is True
    assert status.needs_reauth is False


@pytest.mark.asyncio
async def test_a_genuine_authorization_failure_is_still_reported_as_needs_reauth(tmp_path):
    # The counterpart to the test above: widening the transient bucket must
    # not swallow a real "this session is no longer authorized".
    database = Database(db_path=tmp_path / "app.db")
    database.connect()
    repo = AccountRepository(database)
    account = repo.create("+70000000021", "account_unauth")

    class _UnauthorizedClientManager:
        async def is_authorized(self, session_name):
            raise ValueError("session revoked")

    manager = AccountManager(repo, _UnauthorizedClientManager())
    status = await manager.check_status(account)

    assert status.needs_reauth is True
    assert status.connection_error is False


# ---- application database contention ----------------------------------------


def test_the_application_database_waits_for_a_competing_writer(tmp_path):
    # Nothing stops a user launching a second copy of the app, and both
    # would write this same file from separate connections. Without a
    # busy timeout the second one fails immediately with
    # "database is locked" instead of waiting out a brief overlap.
    from app.database.database import BUSY_TIMEOUT_MS

    database = Database(db_path=tmp_path / "app.db")
    connection = database.connect()
    configured = connection.execute("PRAGMA busy_timeout").fetchone()[0]
    assert configured == BUSY_TIMEOUT_MS
    assert BUSY_TIMEOUT_MS > 0
    database.close()
