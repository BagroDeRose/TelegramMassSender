"""Composition root for the Telegram integration layer.

api_id/api_hash identify the application with Telegram (set once, shared
by every account added to this app) -- so ClientManager and AccountManager
are each constructed exactly once, lazily, the first time valid API
credentials become available (either restored from SecureStorage on
startup, or entered by the user in the login dialog on first run).
"""
from __future__ import annotations

from typing import Optional

from app.database.database import Database
from app.database.models import Account
from app.database.repositories import AccountRepository, SettingsRepository
from app.security.secure_storage import SecureStorage
from app.telegram.account_manager import AccountManager
from app.telegram.client_manager import ClientManager
from app.telegram.demo_client import (
    DEMO_ACCOUNT_DISPLAY_NAME,
    DEMO_ACCOUNT_PHONE,
    DEMO_ACCOUNT_USERNAME,
    DemoClientManager,
)


class TelegramService:
    def __init__(self, database: Database, secure_storage: Optional[SecureStorage] = None) -> None:
        # Defaults to the real, machine-wide DPAPI-backed store (the
        # production path) -- but is injectable so tests/tools can supply
        # an isolated SecureStorage(tmp_path) instead. Without this, any
        # code that constructs a TelegramService picks up whatever real
        # API credentials happen to already be stored on the machine
        # (confirmed directly: this repo's own dev machine has real,
        # actual stored credentials from genuine prior use of the app,
        # and a test asserting on is_configured/load_api_credentials()
        # failed against them before this parameter existed).
        self.secure_storage = secure_storage or SecureStorage()
        self.account_repository = AccountRepository(database)
        self.settings_repository = SettingsRepository(database)
        self._client_manager: Optional[ClientManager] = None
        self.account_manager: Optional[AccountManager] = None
        self.is_demo_mode = False
        # Set aside while demo mode is active so exiting restores the very
        # same objects (and therefore the same live clients) rather than
        # rebuilding them -- see enter_demo_mode.
        self._real_client_manager: Optional[ClientManager] = None
        self._real_account_manager: Optional[AccountManager] = None
        self._restore_from_storage()
        # A demo account row left behind by v2.0.0, or by a crash while
        # demo mode was active, must never be treated as a real account.
        self.purge_demo_accounts()

    def _restore_from_storage(self) -> None:
        creds = self.secure_storage.load_api_credentials()
        if creds is not None:
            self._activate(creds.api_id, creds.api_hash)

    def _activate(self, api_id: int, api_hash: str) -> ClientManager:
        if self._client_manager is None:
            self._client_manager = ClientManager(api_id, api_hash)
            self.account_manager = AccountManager(self.account_repository, self._client_manager)
        return self._client_manager

    @property
    def is_configured(self) -> bool:
        return self._client_manager is not None

    def configure_api_credentials(self, api_id: int, api_hash: str) -> ClientManager:
        self.secure_storage.save_api_credentials(api_id, api_hash)
        return self._activate(api_id, api_hash)

    def enter_demo_mode(self) -> Account:
        """Activates a fully local, simulated Telegram backend (Demo
        Mode, v2.0): a DemoClientManager that never opens a real
        connection -- no real API ID/Hash is needed or touched, and
        nothing here reads from or writes to SecureStorage.

        The real ClientManager/AccountManager are *set aside*, not thrown
        away, so exit_demo_mode() can put back the very same objects. The
        previous version replaced them and rebuilt fresh ones on exit,
        which orphaned every live TelegramClient: their Telethon
        SQLiteSession files stayed open while the new manager opened a
        second connection to the same file, which is where the
        "database is locked" status-check failures came from.
        """
        if self.is_demo_mode:
            return self._demo_account()

        self._real_client_manager = self._client_manager
        self._real_account_manager = self.account_manager
        self._client_manager = DemoClientManager()
        self.account_manager = AccountManager(self.account_repository, self._client_manager)
        self.is_demo_mode = True
        return self._demo_account()

    def _demo_account(self) -> Account:
        assert self.account_manager is not None
        account = self.account_manager.register_account(DEMO_ACCOUNT_PHONE)
        account = self.account_manager.update_profile(
            account,
            telegram_user_id=1,
            username=DEMO_ACCOUNT_USERNAME,
            display_name=DEMO_ACCOUNT_DISPLAY_NAME,
        )
        self.account_manager.switch_active_account(account.id)
        return account

    def exit_demo_mode(self) -> None:
        """Puts back exactly the real ClientManager/AccountManager that
        were in use before demo mode, and removes the demo account row so
        it never shows up in -- or is connected as part of -- the user's
        real account list. Safe to call even if demo mode was never
        entered."""
        if not self.is_demo_mode:
            return
        self.purge_demo_accounts()
        self._client_manager = self._real_client_manager
        self.account_manager = self._real_account_manager
        self._real_client_manager = None
        self._real_account_manager = None
        self.is_demo_mode = False
        if self._client_manager is None:
            # Credentials may have been configured while demo mode was
            # active; pick them up rather than staying unconfigured.
            self._restore_from_storage()

    def purge_demo_accounts(self) -> int:
        """Remove the demo account row from the real account list.

        Called when leaving demo mode and again at startup: demo mode used
        to persist "+10000000000" into the real accounts table and never
        remove it, so a leftover row survives from v2.0.0 (and from any
        crash while demo mode was active). Left in place, the next refresh
        in real mode builds a genuine Telethon client for that fake
        account and tries to connect it, which is both a real session file
        on disk and a stream of connection errors in the log.

        Only the session *row* is dropped here; a demo account never has a
        real session file, because DemoClientManager never opens one.
        """
        removed = 0
        for account in self.account_repository.list_all():
            if account.phone == DEMO_ACCOUNT_PHONE:
                self.account_repository.delete(account.id)
                removed += 1
        return removed

    async def shutdown(self) -> None:
        if self._client_manager is not None:
            await self._client_manager.disconnect_all()
