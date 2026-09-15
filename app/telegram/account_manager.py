"""High-level Telegram account lifecycle: register, authorize-check, list,
switch active account, delete. Wraps ClientManager (session/connection
plumbing) and AccountRepository (persisted account metadata).
"""
from __future__ import annotations

import asyncio
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from app.config.paths import get_session_path
from app.database.models import Account
from app.database.repositories import AccountRepository
from app.i18n import tr
from app.logging.logger import get_logger
from app.telegram.client_manager import ClientManager
from app.telegram.exceptions import AccountDeletionError, AccountSwitchBlockedError

# Bounded, deliberately small: this covers a session file that Windows
# still reports as open for a moment after Telethon closed it, not a file
# genuinely in use by a running client (which the disconnect above already
# handled). Never an unbounded loop -- a still-locked file is reported.
_SESSION_UNLINK_ATTEMPTS = 5
_SESSION_UNLINK_RETRY_DELAY_SECONDS = 0.1

logger = get_logger()

# Mirrors app.campaign.campaign_manager._TRANSIENT_ERROR_TYPES: a network
# blip while checking status must never be reported the same way as a
# genuine "this session is no longer authorized" -- see AccountStatus
# .connection_error below and the check_status docstring for why this
# distinction exists (it's the fix for accounts appearing to "disappear").
_TRANSIENT_ERROR_TYPES = (
    ConnectionError,
    OSError,
    asyncio.TimeoutError,
    TimeoutError,
    # "database is locked" from Telethon's own SQLiteSession file. This is
    # a contention/timing problem, not an authorization one: the account's
    # session is perfectly valid and the fix is to retry, so reporting it
    # as needs_reauth (which is what the generic handler below did) made a
    # working account look like it had to be logged in again.
    sqlite3.OperationalError,
)


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

    def rename_account(self, account: Account, local_alias: Optional[str]) -> Account:
        self._repository.rename(account.id, local_alias)
        refreshed = self._repository.get_by_id(account.id)
        assert refreshed is not None
        return refreshed

    async def delete_account(self, account: Account) -> None:
        # log_out() (real server-side session invalidation) is attempted
        # first and never raises -- it must not block local removal below
        # even if the network is unreachable or the session is already
        # invalid, since "remove this account from the app" always needs
        # to succeed locally regardless of Telegram's own reachability.
        await self._client_manager.log_out(account.session_name)
        await self._client_manager.disconnect(account.session_name)
        # remove() now also closes the session's sqlite connection, which
        # is what actually releases the Windows file handle -- dropping the
        # client from the dict alone left the file open.
        self._client_manager.remove(account.session_name)
        session_base = get_session_path(account.session_name)
        for suffix in (".session", ".session-journal"):
            candidate = session_base.with_suffix(suffix)
            await self._unlink_session_file(candidate)
        self._repository.delete(account.id)
        if self._active_account_id == account.id:
            self._active_account_id = None
        logger.info("Аккаунт удалён: %s", account.phone)

    async def _unlink_session_file(self, candidate: Path) -> None:
        """Delete one session file, tolerating the brief window in which
        Windows still reports the handle as open.

        Telethon closes the session's sqlite connection synchronously, but
        on Windows the handle can still be briefly held (an antivirus or
        indexer scanning the file it just saw written is the usual
        culprit), and the delete then fails with WinError 32. A short,
        bounded retry covers that; it deliberately does NOT loop forever,
        and a file that is still locked after the last attempt raises
        AccountDeletionError instead of being silently ignored, because
        leaving a stale session file behind while telling the user the
        account is gone is exactly the kind of thing that should be
        reported.
        """
        for attempt in range(_SESSION_UNLINK_ATTEMPTS):
            if not candidate.exists():
                return
            try:
                candidate.unlink()
                return
            except PermissionError as exc:
                if attempt == _SESSION_UNLINK_ATTEMPTS - 1:
                    logger.warning("Файл сессии занят другим процессом: %s (%s)", candidate.name, exc)
                    raise AccountDeletionError(
                        tr("account_manager.error.session_file_locked", name=candidate.name)
                    ) from exc
                await asyncio.sleep(_SESSION_UNLINK_RETRY_DELAY_SECONDS)
            except OSError as exc:
                logger.warning("Не удалось удалить файл сессии %s: %s", candidate.name, exc)
                raise AccountDeletionError(
                    tr("account_manager.error.session_file_locked", name=candidate.name)
                ) from exc
