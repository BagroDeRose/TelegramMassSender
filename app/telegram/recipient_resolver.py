"""Resolve parsed recipient identifiers into Telegram entities.

A target is either a user, or a group/supergroup/channel the account is
already a member of (app.telegram.chat_targets). @username / t.me/username
can name either -- the resolved entity decides. Marked chat ids
(-100.../-...) carry no access_hash, so the account's own dialogs are
fetched once per resolver (lazily, the first time such an id comes up) to
find them; a chat id that isn't among them means the account isn't in that
chat. Invite links are only *checked* (CheckChatInviteRequest), never
joined: unless Telegram answers ChatInviteAlready, the target fails with
"not a member". Any other entity type is still rejected (NOT_A_USER).

Results are cached per resolver instance (bounded to one campaign's
recipient list) to avoid redundant get_entity calls against the same
identifier (spec item 47) -- the cache is not persisted or shared beyond
that.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    InviteHashEmptyError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    PeerIdInvalidError,
    PhoneNotOccupiedError,
    PhoneNumberInvalidError,
    RPCError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.functions.contacts import ResolvePhoneRequest
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.types import ChatInviteAlready, User

from app.i18n import tr
from app.logging.logger import get_logger
from app.recipients.parser import ParsedRecipient, RecipientKind
from app.telegram.chat_targets import (
    DialogSnapshot,
    TargetType,
    chat_error_reason_key,
    chat_peer_id,
    target_type_of,
)

logger = get_logger()


class ResolveStatus:
    READY = "ready"
    INVALID_FORMAT = "invalid_format"
    NOT_FOUND = "not_found"
    INVALID_ID = "invalid_id"
    NOT_A_USER = "not_a_user"
    UNAVAILABLE = "unavailable"
    PHONE_NOT_FOUND = "phone_not_found"
    # Group/channel targets.
    NOT_MEMBER = "not_member"
    NO_ACCESS = "no_access"
    INVITE_INVALID = "invite_invalid"


_STATUS_LABEL_KEYS: Dict[str, str] = {
    ResolveStatus.READY: "recipient_resolver.status.ready",
    ResolveStatus.INVALID_FORMAT: "recipient_resolver.status.invalid_format",
    ResolveStatus.NOT_FOUND: "recipient_resolver.status.user_not_found",
    ResolveStatus.INVALID_ID: "recipient_resolver.status.invalid_id",
    ResolveStatus.NOT_A_USER: "recipient_resolver.status.cannot_message",
    ResolveStatus.UNAVAILABLE: "recipient_resolver.status.cannot_message",
    ResolveStatus.PHONE_NOT_FOUND: "recipient_resolver.status.phone_not_found",
    ResolveStatus.NOT_MEMBER: "chat_targets.reason.not_member",
    ResolveStatus.NO_ACCESS: "chat_targets.reason.no_access",
    ResolveStatus.INVITE_INVALID: "chat_targets.reason.invite_invalid",
}


def status_label(status: str) -> str:
    """Looked up fresh on every call (not a module-level dict of already-
    resolved strings) so a language switch is reflected immediately,
    rather than freezing every label in whatever language was active the
    moment this module was first imported."""
    return tr(_STATUS_LABEL_KEYS[status])


class _StatusLabels:
    """Preserves the STATUS_LABELS[status] subscript call sites below
    without a module-level dict that would bake in the import-time
    language permanently."""

    def __getitem__(self, status: str) -> str:
        return status_label(status)


STATUS_LABELS = _StatusLabels()


@dataclass
class ResolvedRecipient:
    parsed: ParsedRecipient
    status: str
    entity: Optional[Any] = None  # User, or Chat/Channel for a chat target
    error: Optional[str] = None
    target_type: Optional[TargetType] = None

    @property
    def is_ready(self) -> bool:
        return self.status == ResolveStatus.READY

    @property
    def is_chat(self) -> bool:
        return self.target_type is not None and self.target_type.is_chat


class RecipientResolver:
    def __init__(self, client: TelegramClient, dialogs: Optional[DialogSnapshot] = None) -> None:
        """`dialogs`: the session's cached DialogSnapshot for this account
        (the "From my chats…" picker's last read), if any. IDs found there
        need no dialogs read of their own; one that isn't there makes the
        resolver read the dialogs from Telegram once, as without a cache."""
        self._client = client
        self._cache: Dict[str, ResolvedRecipient] = {}
        # Marked id -> chat entity and user id -> User, from the account's
        # own dialogs; None until known (see ensure_dialogs_loaded).
        self._dialog_chats: Optional[Dict[int, Any]] = dict(dialogs.chats) if dialogs is not None else None
        self._dialog_users: Dict[int, Any] = dict(dialogs.users) if dialogs is not None else {}
        # True once this resolver read the dialogs from Telegram itself.
        self._dialogs_fetched = False

    @property
    def dialogs_loaded(self) -> bool:
        return self._dialog_chats is not None

    async def ensure_dialogs_loaded(self) -> None:
        """Fetch the account's dialogs once, which is also what gives
        Telethon the access_hash it needs for a bare marked chat id -- or
        for a bare user id the session hasn't seen (e.g. a person picked
        by ID in "From my chats…" on another day). FloodWaitError
        propagates (the campaign pauses on it exactly like on a send);
        nothing is cached on failure, so the next call retries the fetch
        from scratch."""
        if self._dialog_chats is not None:
            return
        await self._fetch_dialogs()

    async def _refetch_dialogs_once(self) -> bool:
        """An ID wasn't in the dialogs known so far (possibly a cached
        snapshot): read them from Telegram, at most once per resolver.
        False if they were already read fresh, so there's nothing new."""
        if self._dialogs_fetched:
            return False
        await self._fetch_dialogs()
        return True

    async def _fetch_dialogs(self) -> None:
        chats: Dict[int, Any] = {}
        users: Dict[int, Any] = {}
        async for dialog in self._client.iter_dialogs():
            entity = dialog.entity
            target_type = target_type_of(entity)
            if target_type is TargetType.USER:
                users[entity.id] = entity
            elif target_type is not None:
                chats[chat_peer_id(entity)] = entity
        self._dialog_chats = chats
        self._dialog_users = users
        self._dialogs_fetched = True
        logger.info("Загружены диалоги аккаунта: чатов %d, личных %d", len(chats), len(users))

    def _from_entity(self, parsed: ParsedRecipient, entity: Any) -> ResolvedRecipient:
        target_type = target_type_of(entity)
        if target_type is TargetType.USER:
            return ResolvedRecipient(parsed=parsed, status=ResolveStatus.READY, entity=entity, target_type=target_type)
        if target_type is not None:
            return ResolvedRecipient(parsed=parsed, status=ResolveStatus.READY, entity=entity, target_type=target_type)
        return ResolvedRecipient(
            parsed=parsed,
            status=ResolveStatus.NOT_A_USER,
            error=tr("recipient_resolver.error.not_a_user"),
        )

    @staticmethod
    def _failed(parsed: ParsedRecipient, status: str, error_key: Optional[str] = None) -> ResolvedRecipient:
        return ResolvedRecipient(parsed=parsed, status=status, error=tr(error_key) if error_key else STATUS_LABELS[status])

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

        if parsed.kind == RecipientKind.INVITE_LINK:
            result = await self._resolve_invite(parsed)
            self._cache[cache_key] = result
            return result

        if parsed.kind == RecipientKind.CHAT_ID:
            await self.ensure_dialogs_loaded()  # FloodWaitError propagates
            entity = self._dialog_chats.get(int(parsed.value))
            if entity is None and await self._refetch_dialogs_once():
                entity = self._dialog_chats.get(int(parsed.value))
            if entity is not None:
                result = self._from_entity(parsed, entity)
                self._cache[cache_key] = result
                return result

        identifier = int(parsed.value) if parsed.kind in (RecipientKind.USER_ID, RecipientKind.CHAT_ID) else parsed.value

        if parsed.kind == RecipientKind.USER_ID and identifier in self._dialog_users:
            result = self._from_entity(parsed, self._dialog_users[identifier])
            self._cache[cache_key] = result
            return result

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
            if parsed.kind == RecipientKind.CHAT_ID:
                result = self._failed(parsed, ResolveStatus.NOT_MEMBER)
            else:
                result = ResolvedRecipient(
                    parsed=parsed, status=ResolveStatus.INVALID_ID, error=STATUS_LABELS[ResolveStatus.INVALID_ID]
                )
        except ValueError:
            if parsed.kind == RecipientKind.CHAT_ID:
                # Not among the account's dialogs and unknown to the
                # session: the account isn't in this chat.
                result = self._failed(parsed, ResolveStatus.NOT_MEMBER)
            elif parsed.kind == RecipientKind.USER_ID and not self._dialogs_fetched:
                # A bare user id the session has no access_hash for, and not
                # in the dialogs known so far: read the dialogs from
                # Telegram once (FloodWaitError propagates) and take the
                # user from there -- never a guessed access_hash.
                await self._refetch_dialogs_once()
                user = self._dialog_users.get(identifier)
                if user is not None:
                    result = self._from_entity(parsed, user)
                else:
                    result = ResolvedRecipient(
                        parsed=parsed, status=ResolveStatus.NOT_FOUND, error=STATUS_LABELS[ResolveStatus.NOT_FOUND]
                    )
            else:
                result = ResolvedRecipient(
                    parsed=parsed, status=ResolveStatus.NOT_FOUND, error=STATUS_LABELS[ResolveStatus.NOT_FOUND]
                )
        except RPCError as exc:
            reason_key = chat_error_reason_key(exc)
            if reason_key is not None:
                result = self._failed(parsed, ResolveStatus.NO_ACCESS, reason_key)
            else:
                logger.warning("Ошибка resolve получателя %s: %s", parsed.raw, exc)
                result = ResolvedRecipient(parsed=parsed, status=ResolveStatus.UNAVAILABLE, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - network/unexpected, surfaced per-recipient
            logger.warning("Ошибка resolve получателя %s: %s", parsed.raw, exc)
            result = ResolvedRecipient(parsed=parsed, status=ResolveStatus.UNAVAILABLE, error=str(exc))
        else:
            if parsed.kind == RecipientKind.USER_ID and not isinstance(entity, User):
                # A positive id always meant a user; keep it that way.
                result = ResolvedRecipient(
                    parsed=parsed,
                    status=ResolveStatus.NOT_A_USER,
                    error=tr("recipient_resolver.error.not_a_user"),
                )
            else:
                result = self._from_entity(parsed, entity)

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
                error=tr("recipient_resolver.error.not_a_user"),
            )
        return ResolvedRecipient(parsed=parsed, status=ResolveStatus.READY, entity=entity, target_type=TargetType.USER)

    async def _resolve_invite(self, parsed: ParsedRecipient) -> ResolvedRecipient:
        """Check an invite link without ever joining: only ChatInviteAlready
        (the account is already in that chat) yields a usable target."""
        try:
            response = await self._client(CheckChatInviteRequest(hash=parsed.value))
        except FloodWaitError:
            raise
        except (InviteHashExpiredError, InviteHashInvalidError, InviteHashEmptyError):
            return self._failed(parsed, ResolveStatus.INVITE_INVALID)
        except RPCError as exc:
            reason_key = chat_error_reason_key(exc)
            if reason_key is not None:
                return self._failed(parsed, ResolveStatus.NO_ACCESS, reason_key)
            logger.warning("Ошибка проверки ссылки-приглашения: %s", exc)
            return ResolvedRecipient(parsed=parsed, status=ResolveStatus.UNAVAILABLE, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - network/unexpected, surfaced per-recipient
            logger.warning("Ошибка проверки ссылки-приглашения: %s", exc)
            return ResolvedRecipient(parsed=parsed, status=ResolveStatus.UNAVAILABLE, error=str(exc))

        if isinstance(response, ChatInviteAlready):
            return self._from_entity(parsed, response.chat)
        # ChatInvite / ChatInvitePeek: the account is not a participant.
        return self._failed(parsed, ResolveStatus.NOT_MEMBER)

    def clear_cache(self) -> None:
        self._cache.clear()
