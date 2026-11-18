"""Interactive login flows: phone -> code -> optional 2FA, or a QR code
scanned with Telegram on the phone -> optional 2FA.

Wraps Telethon's client.send_code_request / client.sign_in /
client.qr_login, which implement the standard MTProto authorization
handshakes. An AuthenticationFlow instance holds only the transient state
needed to complete one login attempt (the phone_code_hash Telethon
returns) -- nothing here is ever persisted to disk. The 2FA password
passed to submit_password is handed straight to Telethon and never stored
or logged, and neither is a QR login URL (it carries a login token);
once sign-in succeeds, Telethon's own session file is the only durable
auth artifact.

Where the code went: Telegram answers a code request with a SentCode
whose ``type`` says how it delivered the code (the Telegram app on
another device, SMS, a call, email, Fragment, ...). The app used to throw
that away and always say "enter the code from Telegram", so a code sent by
SMS or email looked like a code that never arrived. ``describe_sent_code``
turns it into a CodeDelivery the dialog shows.

Why QR login: since January 2026 Telegram has been silently not
delivering login codes to third-party clients for some accounts (the
request succeeds, ``type`` says the app, nothing ever arrives -- reported
across Telethon, Pyrogram and TDLib alike). QR login needs no code at all:
the phone's Telegram app, already signed in, approves the new session.
"""
from __future__ import annotations

import asyncio
import datetime
import enum
import re
from dataclasses import dataclass
from typing import Callable, Optional

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import auth as auth_types

from app.logging.logger import get_logger

logger = get_logger()

# A QR login token lives ~30 s. Wait at most that long per token (the
# token's own expiry, measured against the PC clock, can be off by a lot
# on a machine with a wrong clock), and give up after a few minutes so a
# forgotten dialog doesn't keep requesting tokens forever.
QR_MIN_WAIT_SECONDS = 5.0
QR_MAX_WAIT_SECONDS = 30.0
QR_MAX_TOKENS = 10


class QrLoginExpiredError(Exception):
    """No device scanned any of the QR codes shown; ask to refresh."""


class CodeChannel(str, enum.Enum):
    APP = "app"
    SMS = "sms"
    CALL = "call"
    FLASH_CALL = "flash_call"
    MISSED_CALL = "missed_call"
    EMAIL = "email"
    EMAIL_SETUP_REQUIRED = "email_setup_required"
    FRAGMENT = "fragment"
    FIREBASE_SMS = "firebase_sms"
    UNKNOWN = "unknown"


_SENT_TYPE_CHANNELS = (
    (auth_types.SentCodeTypeApp, CodeChannel.APP),
    (auth_types.SentCodeTypeSms, CodeChannel.SMS),
    (auth_types.SentCodeTypeSmsWord, CodeChannel.SMS),
    (auth_types.SentCodeTypeSmsPhrase, CodeChannel.SMS),
    (auth_types.SentCodeTypeCall, CodeChannel.CALL),
    (auth_types.SentCodeTypeFlashCall, CodeChannel.FLASH_CALL),
    (auth_types.SentCodeTypeMissedCall, CodeChannel.MISSED_CALL),
    (auth_types.SentCodeTypeEmailCode, CodeChannel.EMAIL),
    (auth_types.SentCodeTypeSetUpEmailRequired, CodeChannel.EMAIL_SETUP_REQUIRED),
    (auth_types.SentCodeTypeFragmentSms, CodeChannel.FRAGMENT),
    (auth_types.SentCodeTypeFirebaseSms, CodeChannel.FIREBASE_SMS),
)

_NEXT_TYPE_CHANNELS = (
    (auth_types.CodeTypeSms, CodeChannel.SMS),
    (auth_types.CodeTypeCall, CodeChannel.CALL),
    (auth_types.CodeTypeFlashCall, CodeChannel.FLASH_CALL),
    (auth_types.CodeTypeMissedCall, CodeChannel.MISSED_CALL),
    (auth_types.CodeTypeFragmentSms, CodeChannel.FRAGMENT),
)

# Channels this app cannot complete a sign-in through: the dialog points
# straight at QR login instead of asking for a code that can't come.
UNUSABLE_CHANNELS = frozenset({CodeChannel.EMAIL_SETUP_REQUIRED, CodeChannel.FIREBASE_SMS})


@dataclass(frozen=True)
class CodeDelivery:
    channel: CodeChannel
    # How a resend would deliver the code; None: Telegram offers no resend.
    next_channel: Optional[CodeChannel] = None
    # Seconds Telegram asks to wait before a resend.
    timeout: Optional[int] = None
    length: Optional[int] = None
    email_pattern: Optional[str] = None
    fragment_url: Optional[str] = None


def describe_sent_code(sent) -> CodeDelivery:
    sent_type = getattr(sent, "type", None)
    channel = CodeChannel.UNKNOWN
    for cls, mapped in _SENT_TYPE_CHANNELS:
        if isinstance(sent_type, cls):
            channel = mapped
            break
    next_type = getattr(sent, "next_type", None)
    next_channel = None
    if next_type is not None:
        next_channel = CodeChannel.UNKNOWN
        for cls, mapped in _NEXT_TYPE_CHANNELS:
            if isinstance(next_type, cls):
                next_channel = mapped
                break
    length = getattr(sent_type, "length", None)
    return CodeDelivery(
        channel=channel,
        next_channel=next_channel,
        timeout=getattr(sent, "timeout", None),
        length=length if isinstance(length, int) else None,
        email_pattern=getattr(sent_type, "email_pattern", None),
        fragment_url=getattr(sent_type, "url", None),
    )


def mask_phone(phone: Optional[str]) -> str:
    """A phone number for the log: country prefix and last two digits only.
    The rotating log goes into the Diagnostic Bundle a user may send to
    someone, which otherwise never contains the phone."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) <= 4:
        return "+" + "*" * len(digits)
    return "+" + digits[:2] + "*" * (len(digits) - 4) + digits[-2:]


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", phone or "")
    return "+" + digits if digits else None


def _qr_wait_seconds(expires: Optional[datetime.datetime]) -> float:
    if expires is None:
        return QR_MAX_WAIT_SECONDS
    remaining = (expires - datetime.datetime.now(tz=datetime.timezone.utc)).total_seconds()
    return min(QR_MAX_WAIT_SECONDS, max(QR_MIN_WAIT_SECONDS, remaining))


@dataclass
class AuthenticatedUser:
    telegram_user_id: int
    username: Optional[str]
    display_name: str
    # The account's own phone as Telegram knows it ("+" and digits), or
    # None if Telegram didn't include it.
    phone: Optional[str] = None


class AuthenticationFlow:
    """One instance per in-progress login attempt for a single client."""

    def __init__(self, client: TelegramClient, phone: str) -> None:
        self._client = client
        self._phone = phone
        self._phone_code_hash: Optional[str] = None

    async def _ensure_connected(self) -> None:
        if not self._client.is_connected():
            await self._client.connect()

    async def request_code(self) -> CodeDelivery:
        await self._ensure_connected()
        result = await self._client.send_code_request(self._phone)
        self._phone_code_hash = result.phone_code_hash
        delivery = describe_sent_code(result)
        logger.info(
            "Код подтверждения запрошен для номера %s: способ %s, следующий %s",
            mask_phone(self._phone),
            delivery.channel.value,
            delivery.next_channel.value if delivery.next_channel else "-",
        )
        return delivery

    async def resend_code(self) -> CodeDelivery:
        """Telegram's own resend (auth.resendCode, the next delivery way):
        Telethon sends it instead of a new request because it keeps the
        hash of the code it already requested for this phone."""
        if self._phone_code_hash is None:
            raise RuntimeError("request_code() must be called before resend_code()")
        await self._ensure_connected()
        result = await self._client.send_code_request(self._phone)
        self._phone_code_hash = result.phone_code_hash
        delivery = describe_sent_code(result)
        logger.info("Код подтверждения отправлен повторно: способ %s", delivery.channel.value)
        return delivery

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
            logger.info("Требуется пароль двухфакторной аутентификации: %s", mask_phone(self._phone))
            return None
        return await self._finalize()

    async def qr_login(self, show_url: Callable[[str], None]) -> Optional[AuthenticatedUser]:
        """Shows QR login URLs through ``show_url`` (a fresh one whenever a
        token expires) until a device scans one. Returns the user, or None
        when Telegram asks for the 2FA password next (then call
        submit_password, exactly as after a code). Raises
        QrLoginExpiredError after QR_MAX_TOKENS unscanned codes."""
        await self._ensure_connected()
        qr = await self._client.qr_login()
        for attempt in range(QR_MAX_TOKENS):
            if attempt:
                await qr.recreate()
            show_url(qr.url)
            try:
                await qr.wait(timeout=_qr_wait_seconds(getattr(qr, "expires", None)))
            except asyncio.TimeoutError:
                continue
            except SessionPasswordNeededError:
                logger.info("Вход по QR-коду: требуется пароль двухфакторной аутентификации")
                return None
            logger.info("Вход по QR-коду подтверждён")
            return await self._finalize()
        raise QrLoginExpiredError()

    async def submit_password(self, password: str) -> AuthenticatedUser:
        # Telethon exchanges the password for the auth key internally; we
        # discard our own reference to it as soon as this call returns and
        # never write it to disk or to the log.
        await self._client.sign_in(password=password)
        return await self._finalize()

    async def discard(self) -> None:
        """Best effort: end a session this attempt authorized but the app
        won't keep (it signed in a different account that is already
        added), so it doesn't linger in that account's device list."""
        try:
            await self._client.log_out()
        except Exception as exc:  # noqa: BLE001 - best effort, the dialog reports the real problem
            logger.warning("Не удалось завершить лишнюю сессию: %s", type(exc).__name__)

    async def _finalize(self) -> AuthenticatedUser:
        me = await self._client.get_me()
        raw_phone = getattr(me, "phone", None)
        phone = normalize_phone(raw_phone) if isinstance(raw_phone, str) else None
        logger.info("Аккаунт успешно авторизован: %s", mask_phone(phone or self._phone))
        display_name = " ".join(filter(None, [me.first_name, me.last_name])).strip()
        return AuthenticatedUser(
            telegram_user_id=me.id,
            username=me.username,
            display_name=display_name or (me.username or str(me.id)),
            phone=phone,
        )
