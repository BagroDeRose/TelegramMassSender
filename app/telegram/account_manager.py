"""High-level Telegram account lifecycle: register, authorize-check, list,
switch active account, delete. Wraps ClientManager (session/connection
plumbing) and AccountRepository (persisted account metadata).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional

from app.config.paths import get_session_path
from app.database.models import Account
from app.database.repositories import AccountRepository
from app.logging.logger import get_logger
from app.telegram.client_manager import ClientManager
from app.telegram.exceptions import AccountSwitchBlockedError

logger = get_logger()


@dataclass
class AccountStatus:
    account: Account
    is_authorized: bool
    needs_reauth: bool


class AccountManager:
    def __init__(self, repository: AccountRepository, client_manager: ClientManager) -> None:
        self._repository = repository
        self._client_manager = client_manager
        self._active_account_id: Optional[int] = None
        self._switch_guard: Optional[Callable[[], bool]] = None

    def set_switch_guard(self, guard: Optional[Callable[[], bool]]) -> None:
        """Guard predicate: return True if switching the active account is
        currently allowed. Wired up by the campaign layer so an account
        cannot be switched away from mid-campaign (spec item 51)."""
        self._switch_guard = guard

    @property
    def active_account_id(self) -> Optional[int]:
        return self._active_account_id

    @staticmethod
    def new_session_name() -> str:
        return f"account_{uuid.uuid4().hex[:12]}"

    def register_account(self, phone: str) -> Account:
        existing = self._repository.get_by_phone(phone)
        if existing is not None:
            return existing
        session_name = self.new_session_name()
        account = self._repository.create(phone, session_name)
        logger.info("Добавлен новый аккаунт: %s", phone)
        return account

    def get_client(self, account: Account):
        return self._client_manager.get_or_create(account.session_name)

    async def ensure_connected(self, account: Account):
        await self._client_manager.connect(account.session_name)
        return self._client_manager.get_or_create(account.session_name)

    def update_profile(
        self,
        account: Account,
        telegram_user_id: int,
        username: Optional[str],
        display_name: Optional[str],
    ) -> Account:
        self._repository.update_profile(account.id, telegram_user_id, username, display_name)
        refreshed = self._repository.get_by_id(account.id)
        assert refreshed is not None
        return refreshed

    async def check_status(self, account: Account) -> AccountStatus:
        try:
            authorized = await self._client_manager.is_authorized(account.session_name)
        except Exception as exc:
            logger.warning("Не удалось проверить статус аккаунта %s: %s", account.phone, exc)
            return AccountStatus(account=account, is_authorized=False, needs_reauth=True)
        return AccountStatus(account=account, is_authorized=authorized, needs_reauth=not authorized)

    async def list_accounts_with_status(self) -> List[AccountStatus]:
        statuses = []
        for account in self._repository.list_all():
            statuses.append(await self.check_status(account))
        return statuses

    def switch_active_account(self, account_id: int) -> None:
        if self._switch_guard is not None and not self._switch_guard():
            raise AccountSwitchBlockedError(
                "Переключение аккаунта недоступно во время рассылки."
            )
        self._active_account_id = account_id
        logger.info("Активный аккаунт переключён: %s", account_id)

    async def delete_account(self, account: Account) -> None:
        await self._client_manager.disconnect(account.session_name)
        self._client_manager.remove(account.session_name)
        session_base = get_session_path(account.session_name)
        for suffix in (".session", ".session-journal"):
            candidate = session_base.with_suffix(suffix)
            if candidate.exists():
                candidate.unlink()
        self._repository.delete(account.id)
        if self._active_account_id == account.id:
            self._active_account_id = None
        logger.info("Аккаунт удалён: %s", account.phone)
