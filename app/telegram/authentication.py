"""Phone-number based interactive login flow (phone -> code -> optional 2FA).

Wraps Telethon's client.send_code_request / client.sign_in, which together
implement the standard MTProto authorization handshake. An AuthenticationFlow
instance holds only the transient state needed to complete one login attempt
(the phone_code_hash Telethon returns) -- nothing here is ever persisted to
disk. The 2FA password passed to submit_password is handed straight to
Telethon and never stored or logged; once sign-in succeeds, Telethon's own
session file is the only durable auth artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from app.logging.logger import get_logger

logger = get_logger()


@dataclass
class AuthenticatedUser:
    telegram_user_id: int
    username: Optional[str]
    display_name: str


class AuthenticationFlow:
    """One instance per in-progress login attempt for a single client."""

    def __init__(self, client: TelegramClient, phone: str) -> None:
        self._client = client
        self._phone = phone
        self._phone_code_hash: Optional[str] = None

    async def request_code(self) -> None:
        if not self._client.is_connected():
            await self._client.connect()
        result = await self._client.send_code_request(self._phone)
        self._phone_code_hash = result.phone_code_hash
        logger.info("Код подтверждения запрошен для номера %s", self._phone)

    async def submit_code(self, code: str) -> Optional[AuthenticatedUser]:
        """Returns the authenticated user on success, or None if Telegram
        requires a 2FA password next (caller should then call
        submit_password)."""
        if self._phone_code_hash is None:
            raise RuntimeError("request_code() must be called before submit_code()")
        try:
            await self._client.sign_in(
                phone=self._phone, code=code, phone_code_hash=self._phone_code_hash
            )
        except SessionPasswordNeededError:
            logger.info("Требуется пароль двухфакторной аутентификации: %s", self._phone)
            return None
        return await self._finalize()

    async def submit_password(self, password: str) -> AuthenticatedUser:
        # Telethon exchanges the password for the auth key internally; we
        # discard our own reference to it as soon as this call returns and
        # never write it to disk or to the log.
        await self._client.sign_in(password=password)
        return await self._finalize()

    async def _finalize(self) -> AuthenticatedUser:
        me = await self._client.get_me()
        logger.info("Аккаунт успешно авторизован: %s", self._phone)
        display_name = " ".join(filter(None, [me.first_name, me.last_name])).strip()
        return AuthenticatedUser(
            telegram_user_id=me.id,
            username=me.username,
            display_name=display_name or (me.username or str(me.id)),
        )
