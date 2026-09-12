"""High-level Telegram account lifecycle: register, authorize-check, list,
switch active account, delete. Wraps ClientManager (session/connection
plumbing) and AccountRepository (persisted account metadata).
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional

from app.config.paths import get_session_path
from app.database.models import Account
from app.database.repositories import AccountRepository
from app.i18n import tr
from app.logging.logger import get_logger
from app.telegram.client_manager import ClientManager
from app.telegram.exceptions import AccountSwitchBlockedError

logger = get_logger()

# Mirrors app.campaign.campaign_manager._TRANSIENT_ERROR_TYPES: a network
# blip while checking status must never be reported the same way as a
# genuine "this session is no longer authorized" -- see AccountStatus
# .connection_error below and the check_status docstring for why this
# distinction exists (it's the fix for accounts appearing to "disappear").
_TRANSIENT_ERROR_TYPES = (ConnectionError, OSError, asyncio.TimeoutError, TimeoutError)


@dataclass
class AccountStatus:
    account: Account
    is_authorized: bool
    needs_reauth: bool
    # True when the last status check failed for a transient/network
    # reason (no internet, Telegram unreachable, timeout) rather than
    # because the account's session is actually no longer authorized.
    # The UI must show this as "connection issue / Reconnect", never as
    # "needs re-authorization" -- conflating the two is what previously
    # made a perfectly valid, still-persisted account look like it had
    # silently broken or vanished after a flaky connection.
    connection_error: bool = False


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

    def get_active_client(self, account_session_name: str):
        """Read-only lookup for Diagnostics (ROADMAP) -- unlike get_client,
        never creates a client as a side effect; returns None if this
        session has no client instance yet."""
        return self._client_manager.get_active_client(account_session_name)

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
        """Never treat a transient connectivity failure as "needs
        re-authorization" -- those are different problems with different
        fixes (wait and retry vs. log in again), and the account's DB row
        and session file are untouched by either outcome."""
        try:
            authorized = await self._client_manager.is_authorized(account.session_name)
        except _TRANSIENT_ERROR_TYPES as exc:
            logger.warning("Проблема с подключением для аккаунта %s: %s", account.phone, exc)
            return AccountStatus(account=account, is_authorized=False, needs_reauth=False, connection_error=True)
        except Exception as exc:  # noqa: BLE001 - genuine auth/session failure, surfaced as needs_reauth
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
            raise AccountSwitchBlockedError(tr("account_manager.error.switch_blocked"))
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
