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
from app.database.repositories import AccountRepository, SettingsRepository
from app.security.secure_storage import SecureStorage
from app.telegram.account_manager import AccountManager
from app.telegram.client_manager import ClientManager


class TelegramService:
    def __init__(self, database: Database) -> None:
        self.secure_storage = SecureStorage()
        self.account_repository = AccountRepository(database)
        self.settings_repository = SettingsRepository(database)
        self._client_manager: Optional[ClientManager] = None
        self.account_manager: Optional[AccountManager] = None
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

    async def shutdown(self) -> None:
        if self._client_manager is not None:
            await self._client_manager.disconnect_all()
