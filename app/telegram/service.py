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
        self._restore_from_storage()

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
        """Activates a fully local, simulated Telegram backend (ROADMAP
        v2.0 Demo Mode): a DemoClientManager that never opens a real
        connection, wired the same way a real ClientManager is via
        _activate() -- no real API ID/Hash needed or touched, and
        nothing here reads from or writes to SecureStorage. Registers one
        pre-seeded demo account (in whatever database this service's
        account_repository already points at -- callers that want full
        isolation from real accounts should construct MainWindow with an
        in-memory Database in the first place, the same mechanism the
        test suite already uses) and switches to it. Safe to call more
        than once; each call re-seeds a fresh demo account rather than
        reusing a stale one.
        """
        self._client_manager = DemoClientManager()
        self.account_manager = AccountManager(self.account_repository, self._client_manager)
        self.is_demo_mode = True

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
        """Restores whatever real configuration existed before
        enter_demo_mode() was called -- a real ClientManager if real API
        credentials were already stored, or the original unconfigured
        state otherwise. Safe to call even if demo mode was never
        entered."""
        self._client_manager = None
        self.account_manager = None
        self.is_demo_mode = False
        self._restore_from_storage()

    async def shutdown(self) -> None:
        if self._client_manager is not None:
            await self._client_manager.disconnect_all()
