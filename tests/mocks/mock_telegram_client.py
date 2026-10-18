"""Mock Telegram client for unit tests (spec item 59).

No test in this suite talks to the real Telegram network. Configure
per-recipient behaviour via `entity_behavior` (what get_entity should do)
and `send_behavior` (what send_message/send_file should do), keyed by the
exact identifier used to look the recipient up (username string or
numeric id).

Groups/supergroups/channels are modelled with *real* Telethon Chat/Channel
objects (make_fake_channel / make_fake_group), so isinstance checks,
utils.get_peer_id and every rights field behave exactly as they do against
Telegram. Register them via `chats` (keyed by username and/or marked id)
and list them in `dialogs`. Like real Telethon, a marked chat id only
resolves after the dialogs have been fetched once (no access_hash
otherwise) -- see `get_entity`. Per-chat send outcomes go in
`chat_send_behavior`, keyed by marked id (Telethon TL objects are
unhashable, so they can't key `send_behavior` directly).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    PeerIdInvalidError,
    PhoneNotOccupiedError,
    UserIsBlockedError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)
from telethon import utils as telethon_utils
from telethon.errors import InviteHashExpiredError, InviteHashInvalidError
from telethon.tl.functions.contacts import ResolvePhoneRequest
from telethon.tl.functions.messages import (
    CheckChatInviteRequest,
    GetDialogFiltersRequest,
    SendMultiMediaRequest,
    UploadMediaRequest,
)
from telethon.tl.types import (
    Channel,
    Chat,
    ChatAdminRights,
    ChatBannedRights,
    ChatInvite,
    ChatInviteAlready,
    ChatInvitePeek,
    InputMediaPhoto,
    Photo,
    User,
)
from telethon.tl.types.messages import DialogFilters

PERMANENT_ERROR_FACTORIES = {
    "not_found": lambda: UsernameNotOccupiedError(request=None),
    "blocked": lambda: UserIsBlockedError(request=None),
    "invalid_id": lambda: PeerIdInvalidError(request=None),
    "write_forbidden": lambda: ChatWriteForbiddenError(request=None),
    "privacy_restricted": lambda: UserPrivacyRestrictedError(request=None),
}

# Behaviors for phone_behavior, keyed by phone string (with leading '+').
PHONE_ERROR_FACTORIES = {
    "not_found": lambda: PhoneNotOccupiedError(request=None),
}


def make_flood_wait(seconds: int) -> FloodWaitError:
    return FloodWaitError(request=None, capture=seconds)


def make_fake_user(identifier: Any, first_name: Optional[str] = None, last_name: Optional[str] = None) -> User:
    user = MagicMock(spec=User)
    user.id = identifier if isinstance(identifier, int) else abs(hash(identifier)) % (10**8)
    user.username = identifier if isinstance(identifier, str) else None
    user.first_name = first_name
    user.last_name = last_name
    return user


def make_user(
    user_id: int,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    *,
    username: Optional[str] = None,
    bot: bool = False,
    deleted: bool = False,
    is_self: bool = False,
    contact: bool = False,
) -> User:
    """A real telethon User (unlike make_fake_user's MagicMock), for dialog
    lists: bot/deleted/is_self/contact behave exactly as from Telegram."""
    return User(
        id=user_id,
        first_name=first_name,
        last_name=last_name,
        username=username,
        bot=bot or None,
        deleted=deleted or None,
        is_self=is_self or None,
        contact=contact or None,
        access_hash=user_id * 3 + 1,
    )


def make_fake_chat() -> Chat:
    return MagicMock(spec=Chat)


def banned_rights(**flags: bool) -> ChatBannedRights:
    """ChatBannedRights with only the given flags set (until_date=None,
    i.e. permanent)."""
    return ChatBannedRights(until_date=None, **flags)


def admin_rights(**flags: bool) -> ChatAdminRights:
    return ChatAdminRights(**flags)


def make_fake_channel(
    channel_id: int,
    title: str,
    *,
    username: Optional[str] = None,
    broadcast: bool = False,
    forum: bool = False,
    creator: bool = False,
    left: bool = False,
    slowmode_enabled: bool = False,
    admin: Optional[ChatAdminRights] = None,
    banned: Optional[ChatBannedRights] = None,
    default_banned: Optional[ChatBannedRights] = None,
) -> Channel:
    """A real telethon Channel: broadcast=True is a channel, otherwise a
    supergroup (megagroup), optionally a forum."""
    return Channel(
        id=channel_id,
        title=title,
        photo=None,
        date=None,
        creator=creator or None,
        left=left or None,
        broadcast=broadcast or None,
        megagroup=(not broadcast) or None,
        forum=forum or None,
        slowmode_enabled=slowmode_enabled or None,
        access_hash=channel_id * 7 + 1,
        username=username,
        admin_rights=admin,
        banned_rights=banned,
        default_banned_rights=default_banned,
    )


def make_fake_group(
    chat_id: int,
    title: str,
    *,
    creator: bool = False,
    admin: Optional[ChatAdminRights] = None,
    default_banned: Optional[ChatBannedRights] = None,
    left: bool = False,
    deactivated: bool = False,
) -> Chat:
    """A real telethon Chat (basic group)."""
    return Chat(
        id=chat_id,
        title=title,
        photo=None,
        participants_count=3,
        date=None,
        version=1,
        creator=creator or None,
        left=left or None,
        deactivated=deactivated or None,
        admin_rights=admin,
        default_banned_rights=default_banned,
    )


def _is_chat_entity(entity: Any) -> bool:
    return isinstance(entity, (Chat, Channel))


class FakeDialog:
    """The slice of telethon.tl.custom.Dialog this app reads. Put one in
    MockTelegramClient.dialogs directly to set archive/date/unread/mute;
    a bare entity there becomes FakeDialog(entity)."""

    def __init__(
        self,
        entity: Any,
        *,
        archived: bool = False,
        date: Optional[datetime] = None,
        unread_count: int = 0,
        muted: bool = False,
    ) -> None:
        self.entity = entity
        try:
            self.id = telethon_utils.get_peer_id(entity)
        except TypeError:  # make_fake_user's MagicMock
            self.id = getattr(entity, "id", None)
        self.name = getattr(entity, "title", None) or getattr(entity, "first_name", None) or ""
        # Real Telethon: folder_id 1 is the archive, archived = folder_id is not None.
        self.folder_id = 1 if archived else None
        self.archived = archived
        self.date = date
        self.unread_count = unread_count
        self.dialog = SimpleNamespace(
            unread_mark=None,
            notify_settings=SimpleNamespace(mute_until=datetime(2038, 1, 1) if muted else None),
        )


@dataclass
class MockTelegramClient:
    """Duck-compatible stand-in for telethon.TelegramClient, covering only
    the surface this application actually calls."""

    entity_behavior: Dict[Any, str] = field(default_factory=dict)
    # Optional first_name to attach to a "found" fake user, keyed by the
    # same identifier used in entity_behavior. Absent identifiers default
    # to no first_name (None), matching a real user with names hidden.
    first_name_behavior: Dict[Any, str] = field(default_factory=dict)
    send_behavior: Dict[Any, Any] = field(default_factory=dict)
    # Keyed by phone string including leading '+'. Value is either "found"
    # (resolves to a fake user), a key into PHONE_ERROR_FACTORIES, or an
    # exception instance to raise directly (e.g. make_flood_wait(...)).
    # Any phone not present defaults to "found".
    phone_behavior: Dict[str, Any] = field(default_factory=dict)
    sent_messages: List[Tuple] = field(default_factory=list)
    connected: bool = False
    get_entity_calls: int = 0
    file_to_media_calls: List[Any] = field(default_factory=list)
    raw_requests: List[Any] = field(default_factory=list)
    # Groups/channels, keyed by username (no '@') and/or marked id.
    chats: Dict[Any, Any] = field(default_factory=dict)
    # Entities returned by iter_dialogs/get_dialogs (users or chats).
    dialogs: List[Any] = field(default_factory=list)
    # Exceptions raised by successive dialog fetches, oldest first (e.g.
    # [make_flood_wait(30)] fails only the first fetch).
    dialogs_errors: List[BaseException] = field(default_factory=list)
    dialogs_calls: int = 0
    # Invite hash -> a chat entity (account already a member:
    # ChatInviteAlready), "not_member" (ChatInvite), "peek"
    # (ChatInvitePeek), "expired", "invalid", or an exception instance.
    # Absent hashes behave as "invalid".
    invite_behavior: Dict[str, Any] = field(default_factory=dict)
    # Marked chat id -> an exception instance raised by every send to that
    # chat, or a list of exceptions/None consumed one per send call.
    chat_send_behavior: Dict[int, Any] = field(default_factory=dict)
    dialogs_cached: bool = False
    # What GetDialogFiltersRequest returns: a list of DialogFilter /
    # DialogFilterChatlist / DialogFilterDefault, or an exception to raise.
    dialog_filters: Any = field(default_factory=list)

    async def connect(self) -> None:
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    async def disconnect(self) -> None:
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return True

    async def get_entity(self, identifier: Any):
        self.get_entity_calls += 1
        if identifier in self.chats and identifier not in self.entity_behavior:
            if isinstance(identifier, int) and not self.dialogs_cached:
                # Real Telethon: a bare marked id has no access_hash until
                # the dialogs (or a message from that chat) were seen.
                raise ValueError(f"Could not find the input entity for {identifier}")
            return self.chats[identifier]
        if isinstance(identifier, int) and identifier < 0 and identifier not in self.entity_behavior:
            raise ValueError(f"Could not find the input entity for {identifier}")
        behavior = self.entity_behavior.get(identifier, "found")
        if behavior == "found":
            return make_fake_user(identifier, first_name=self.first_name_behavior.get(identifier))
        if behavior == "not_a_user":
            return make_fake_chat()
        if behavior in PERMANENT_ERROR_FACTORIES:
            raise PERMANENT_ERROR_FACTORIES[behavior]()
        raise ValueError(f"unknown entity behavior: {behavior}")

    async def get_input_entity(self, entity: Any):
        return entity

    async def iter_dialogs(self, *args, **kwargs):
        self.dialogs_calls += 1
        if self.dialogs_errors:
            raise self.dialogs_errors.pop(0)
        self.dialogs_cached = True
        for item in self.dialogs:
            dialog = item if isinstance(item, FakeDialog) else FakeDialog(item)
            if kwargs.get("ignore_migrated") and getattr(dialog.entity, "migrated_to", None) is not None:
                continue
            yield dialog

    async def get_dialogs(self, *args, **kwargs):
        return [dialog async for dialog in self.iter_dialogs(*args, **kwargs)]

    def _send_outcome(self, entity):
        if _is_chat_entity(entity):
            outcome = self.chat_send_behavior.get(telethon_utils.get_peer_id(entity))
            if isinstance(outcome, list):
                outcome = outcome.pop(0) if outcome else None
            return outcome
        return self.send_behavior.get(entity)

    async def send_message(self, entity, text, formatting_entities=None):
        outcome = self._send_outcome(entity)
        if isinstance(outcome, BaseException):
            raise outcome
        self.sent_messages.append(("message", entity, text, formatting_entities))
        return None

    async def send_file(self, entity, files, caption=None, formatting_entities=None):
        outcome = self._send_outcome(entity)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(files, (list, tuple)):
            # Faithfully reproduces the real Telethon 1.36.0 behaviour:
            # send_file()'s list-like `file` branch returns from inside
            # `if utils.is_list_like(file):` *before* the
            # `if formatting_entities is not None:` check ever runs, and
            # forwards only `caption`/`parse_mode` to `_send_album` --
            # `formatting_entities` is silently dropped for albums. A mock
            # that didn't reproduce this would let a regression test pass
            # for the wrong reason.
            self.sent_messages.append(("file", entity, files, caption, None))
        else:
            self.sent_messages.append(("file", entity, files, caption, formatting_entities))
        return None

    async def _file_to_media(self, file, **kwargs):
        # Returns an already-usable InputMediaPhoto stand-in, skipping the
        # UploadMediaRequest conversion branch that some freshly-uploaded
        # photos/documents need in real Telethon -- that branch is
        # untouched, already-tested Telethon internal code the fix reuses
        # as-is, not something this suite needs to re-verify.
        self.file_to_media_calls.append(file)
        return None, MagicMock(spec=InputMediaPhoto), None

    async def __call__(self, request):
        self.raw_requests.append(request)
        if isinstance(request, SendMultiMediaRequest) and _is_chat_entity(request.peer):
            outcome = self._send_outcome(request.peer)
            if isinstance(outcome, BaseException):
                raise outcome
        if isinstance(request, GetDialogFiltersRequest):
            if isinstance(self.dialog_filters, BaseException):
                raise self.dialog_filters
            return DialogFilters(filters=list(self.dialog_filters))
        if isinstance(request, CheckChatInviteRequest):
            behavior = self.invite_behavior.get(request.hash, "invalid")
            if isinstance(behavior, BaseException):
                raise behavior
            if behavior == "expired":
                raise InviteHashExpiredError(request=None)
            if behavior == "invalid":
                raise InviteHashInvalidError(request=None)
            if behavior == "not_member":
                return ChatInvite(title="Some chat", photo=None, participants_count=10, color=0)
            if behavior == "peek":
                return ChatInvitePeek(chat=make_fake_channel(424242, "Peek chat"), expires=0)
            return ChatInviteAlready(chat=behavior)
        if isinstance(request, UploadMediaRequest):
            response = MagicMock()
            response.photo = MagicMock(spec=Photo)
            return response
        if isinstance(request, ResolvePhoneRequest):
            behavior = self.phone_behavior.get(request.phone, "found")
            if isinstance(behavior, BaseException):
                raise behavior
            if behavior == "found":
                response = MagicMock()
                response.users = [make_fake_user(request.phone)]
                return response
            if behavior in PHONE_ERROR_FACTORIES:
                raise PHONE_ERROR_FACTORIES[behavior]()
            if behavior == "empty":
                response = MagicMock()
                response.users = []
                return response
            raise ValueError(f"unknown phone behavior: {behavior}")
        return MagicMock()
