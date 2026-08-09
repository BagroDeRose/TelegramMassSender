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
from telethon.errors import PeerIdInvalidError, UsernameInvalidError, UsernameNotOccupiedError
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

STATUS_LABELS: Dict[str, str] = {
    ResolveStatus.READY: "Готов",
    ResolveStatus.INVALID_FORMAT: "Некорректный формат",
    ResolveStatus.NOT_FOUND: "Пользователь не найден",
    ResolveStatus.INVALID_ID: "Некорректный Telegram ID",
    ResolveStatus.NOT_A_USER: "Нельзя отправить сообщение",
    ResolveStatus.UNAVAILABLE: "Нельзя отправить сообщение",
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

        identifier = int(parsed.value) if parsed.kind == RecipientKind.USER_ID else parsed.value

        try:
            entity = await self._client.get_entity(identifier)
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

    def clear_cache(self) -> None:
        self._cache.clear()
