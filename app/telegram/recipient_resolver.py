"""Resolve parsed recipient identifiers into Telegram user entities.

Only private users may be targeted (spec items 1, 14): groups, channels
and any other non-user entity are rejected here and never sent to.
Results are cached per resolver instance (bounded to one campaign's
recipient list) to avoid redundant get_entity calls against the same
identifier (spec item 47) -- the cache is not persisted or shared beyond
that.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PeerIdInvalidError,
    PhoneNotOccupiedError,
    PhoneNumberInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.functions.contacts import ResolvePhoneRequest
from telethon.tl.types import User

from app.logging.logger import get_logger
from app.recipients.parser import ParsedRecipient, RecipientKind

logger = get_logger()


class ResolveStatus:
    READY = "ready"
    INVALID_FORMAT = "invalid_format"
    NOT_FOUND = "not_found"
    INVALID_ID = "invalid_id"
    NOT_A_USER = "not_a_user"
    UNAVAILABLE = "unavailable"
    PHONE_NOT_FOUND = "phone_not_found"

STATUS_LABELS: Dict[str, str] = {
    ResolveStatus.READY: "Готов",
    ResolveStatus.INVALID_FORMAT: "Некорректный формат",
    ResolveStatus.NOT_FOUND: "Пользователь не найден",
    ResolveStatus.INVALID_ID: "Некорректный Telegram ID",
    ResolveStatus.NOT_A_USER: "Нельзя отправить сообщение",
    ResolveStatus.UNAVAILABLE: "Нельзя отправить сообщение",
    ResolveStatus.PHONE_NOT_FOUND: (
        "Telegram не смог разрешить этот номер телефона. Пользователь может быть "
        "недоступен по номеру из-за настроек приватности Telegram."
    ),
}


@dataclass
class ResolvedRecipient:
    parsed: ParsedRecipient
    status: str
    entity: Optional[User] = None
    error: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        return self.status == ResolveStatus.READY


class RecipientResolver:
    def __init__(self, client: TelegramClient) -> None:
        self._client = client
        self._cache: Dict[str, ResolvedRecipient] = {}

    async def resolve(self, parsed: ParsedRecipient) -> ResolvedRecipient:
        if not parsed.is_valid:
            return ResolvedRecipient(
                parsed=parsed, status=ResolveStatus.INVALID_FORMAT, error=parsed.error
            )

        cache_key = parsed.normalized_key
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        if parsed.kind == RecipientKind.PHONE:
            result = await self._resolve_phone(parsed)
            self._cache[cache_key] = result
            return result

        identifier = int(parsed.value) if parsed.kind == RecipientKind.USER_ID else parsed.value

        try:
            entity = await self._client.get_entity(identifier)
        except FloodWaitError:
            # Never swallow this into a per-item failure -- the caller
            # (app.campaign.campaign_manager) must pause the whole campaign
            # and honor Telegram's required wait, exactly like a FloodWait
            # from the send call itself.
            raise
        except (UsernameNotOccupiedError, UsernameInvalidError):
            result = ResolvedRecipient(
                parsed=parsed, status=ResolveStatus.NOT_FOUND, error=STATUS_LABELS[ResolveStatus.NOT_FOUND]
            )
        except PeerIdInvalidError:
            result = ResolvedRecipient(
                parsed=parsed, status=ResolveStatus.INVALID_ID, error=STATUS_LABELS[ResolveStatus.INVALID_ID]
            )
        except ValueError:
            result = ResolvedRecipient(
                parsed=parsed, status=ResolveStatus.NOT_FOUND, error=STATUS_LABELS[ResolveStatus.NOT_FOUND]
            )
        except Exception as exc:  # noqa: BLE001 - network/unexpected, surfaced per-recipient
            logger.warning("Ошибка resolve получателя %s: %s", parsed.raw, exc)
            result = ResolvedRecipient(parsed=parsed, status=ResolveStatus.UNAVAILABLE, error=str(exc))
        else:
            if isinstance(entity, User):
                result = ResolvedRecipient(parsed=parsed, status=ResolveStatus.READY, entity=entity)
            else:
                result = ResolvedRecipient(
                    parsed=parsed,
                    status=ResolveStatus.NOT_A_USER,
                    error="Получатель должен быть пользователем, а не группой/каналом",
                )

        self._cache[cache_key] = result
        return result

    async def _resolve_phone(self, parsed: ParsedRecipient) -> ResolvedRecipient:
        """Resolve a phone recipient via contacts.resolvePhone -- this looks
        up the peer directly, subject to the target's privacy settings, and
        does NOT add them as a contact (unlike ImportContactsRequest)."""
        try:
            response = await self._client(ResolvePhoneRequest(phone=f"+{parsed.value}"))
        except FloodWaitError:
            raise
        except (PhoneNotOccupiedError, PhoneNumberInvalidError):
            return ResolvedRecipient(
                parsed=parsed,
                status=ResolveStatus.PHONE_NOT_FOUND,
                error=STATUS_LABELS[ResolveStatus.PHONE_NOT_FOUND],
            )
        except Exception as exc:  # noqa: BLE001 - network/unexpected, surfaced per-recipient
            logger.warning("Ошибка resolve номера телефона: %s", exc)
            return ResolvedRecipient(parsed=parsed, status=ResolveStatus.UNAVAILABLE, error=str(exc))

        users = getattr(response, "users", None) or []
        if not users:
            return ResolvedRecipient(
                parsed=parsed,
                status=ResolveStatus.PHONE_NOT_FOUND,
                error=STATUS_LABELS[ResolveStatus.PHONE_NOT_FOUND],
            )
        entity = users[0]
        if not isinstance(entity, User):
            return ResolvedRecipient(
                parsed=parsed,
                status=ResolveStatus.NOT_A_USER,
                error="Получатель должен быть пользователем, а не группой/каналом",
            )
        return ResolvedRecipient(parsed=parsed, status=ResolveStatus.READY, entity=entity)

    def clear_cache(self) -> None:
        self._cache.clear()
