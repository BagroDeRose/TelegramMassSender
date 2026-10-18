"""Group/supergroup/channel targets: type detection, pre-send permission
checks ("preflight"), Telegram-error -> user-facing reason mapping, and
the account's own dialog list behind the "From my chats…" picker
(list_dialogs: people, bots, groups and channels, with folders).

Scope, deliberately narrow: this only ever reads what Telegram already
says about a chat the account is *already* in -- it never joins a chat
(no ImportChatInviteRequest / JoinChannelRequest anywhere), never works
around slow mode or FloodWait, and never guesses an access_hash. A chat
the account isn't a member of, or can't write to, is reported as a
failed target with a readable reason; the campaign moves on.

Preflight is a best-effort early answer computed from the entity's own
rights fields (admin_rights / banned_rights / default_banned_rights, as
present on Telethon 1.36's Chat/Channel). Telegram stays the authority:
whatever the send call itself raises is mapped through
chat_error_reason_key() too, so a check this module can't see in advance
still ends as a clear per-target reason rather than "unexpected error".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, FrozenSet, List, Optional, Tuple

from telethon import utils as telethon_utils
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatForbiddenError,
    ChatGuestSendForbiddenError,
    ChatIdInvalidError,
    ChatInvalidError,
    ChatRestrictedError,
    ChatSendGifsForbiddenError,
    ChatSendMediaForbiddenError,
    ChatWriteForbiddenError,
    PeerIdInvalidError,
    SlowModeMultiMsgsDisabledError,
    TopicDeletedError,
    UserBannedInChannelError,
)
from telethon.errors import RPCError
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import (
    Channel,
    ChannelForbidden,
    Chat,
    ChatForbidden,
    DialogFilter,
    DialogFilterChatlist,
    User,
)

from app.i18n import tr
from app.logging.logger import get_logger
from app.telegram.media_sender import (
    CAPTION_MAX_LENGTH,
    Attachment,
    AttachmentKind,
    build_send_groups,
)

logger = get_logger()


class TargetType(Enum):
    USER = "user"
    GROUP = "group"  # basic (legacy) group
    SUPERGROUP = "supergroup"
    FORUM = "forum"  # supergroup with topics enabled
    CHANNEL = "channel"  # broadcast channel

    @property
    def is_chat(self) -> bool:
        return self is not TargetType.USER


CHAT_TARGET_TYPES = (TargetType.GROUP, TargetType.SUPERGROUP, TargetType.FORUM, TargetType.CHANNEL)

_TYPE_LABEL_KEYS = {
    TargetType.USER: "chat_targets.type.user",
    TargetType.GROUP: "chat_targets.type.group",
    TargetType.SUPERGROUP: "chat_targets.type.supergroup",
    TargetType.FORUM: "chat_targets.type.forum",
    TargetType.CHANNEL: "chat_targets.type.channel",
}


def target_type_label(target_type: TargetType) -> str:
    return tr(_TYPE_LABEL_KEYS[target_type])


def target_type_of(entity: Any) -> Optional[TargetType]:
    """None for anything that is neither a user nor a chat/channel."""
    if isinstance(entity, User):
        return TargetType.USER
    if isinstance(entity, (Chat, ChatForbidden)):
        return TargetType.GROUP
    if isinstance(entity, (Channel, ChannelForbidden)):
        if getattr(entity, "broadcast", False) and not getattr(entity, "megagroup", False):
            return TargetType.CHANNEL
        if getattr(entity, "forum", False):
            return TargetType.FORUM
        return TargetType.SUPERGROUP
    return None


def chat_peer_id(entity: Any) -> int:
    """Marked peer id (-100... for channels/supergroups, -... for basic
    groups) -- the same convention the recipient parser accepts back."""
    return telethon_utils.get_peer_id(entity)


@dataclass(frozen=True)
class SendRequirements:
    """What one recipient's send actually needs, derived from the campaign's
    message/attachments the same way app.telegram.media_sender plans the
    send -- the input to the permission preflight."""

    has_plain_text_message: bool = False
    media_kinds: FrozenSet[AttachmentKind] = field(default_factory=frozenset)
    # Number of separate Telegram messages the send produces (an album of N
    # files is N messages). Slow mode lets a non-admin post only one.
    message_count: int = 1


def send_requirements(text: str, attachments: List[Attachment]) -> SendRequirements:
    """Mirrors build_media_send_plan's leading-text-vs-caption decision
    without validating the files (the campaign start already did, and the
    send itself re-validates)."""
    text = text or ""
    attachments = attachments or []
    groups = build_send_groups(attachments)
    if not groups:
        return SendRequirements(has_plain_text_message=bool(text), message_count=1 if text else 0)
    leading_text = bool(text) and len(text) > CAPTION_MAX_LENGTH
    return SendRequirements(
        has_plain_text_message=leading_text,
        media_kinds=frozenset(a.kind for a in attachments),
        message_count=len(attachments) + (1 if leading_text else 0),
    )


# Per-kind ChatBannedRights flags (Telethon 1.36 / layer 1xx granular
# media rights). send_media is the blanket flag checked in addition.
_MEDIA_KIND_RIGHT = {
    AttachmentKind.PHOTO: "send_photos",
    AttachmentKind.VIDEO: "send_videos",
    AttachmentKind.ANIMATION: "send_gifs",
    AttachmentKind.AUDIO: "send_audios",
    AttachmentKind.IMAGE_OTHER: "send_docs",
    AttachmentKind.ARCHIVE: "send_docs",
    AttachmentKind.DOCUMENT: "send_docs",
}

# Telegram encodes "forever" as an until_date far in the future (or 0);
# an until_date already in the past means the restriction has expired.
def _is_active(rights: Any, now: datetime) -> bool:
    if rights is None:
        return False
    until = getattr(rights, "until_date", None)
    if isinstance(until, datetime):
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if until.timestamp() > 0 and until <= now:
            return False
    return True


def _restriction_reason(rights: Any, requirements: SendRequirements, personal: bool) -> Optional[str]:
    if getattr(rights, "view_messages", False) and personal:
        return "chat_targets.reason.banned"
    if getattr(rights, "send_messages", False):
        return "chat_targets.reason.write_forbidden_personal" if personal else "chat_targets.reason.write_forbidden"
    if requirements.has_plain_text_message and getattr(rights, "send_plain", False):
        return "chat_targets.reason.plain_forbidden"
    if requirements.media_kinds:
        if getattr(rights, "send_media", False):
            return "chat_targets.reason.media_forbidden"
        for kind in requirements.media_kinds:
            flag = _MEDIA_KIND_RIGHT.get(kind)
            if flag and getattr(rights, flag, False):
                return "chat_targets.reason.media_forbidden"
    return None


def check_send_rights(
    entity: Any, requirements: SendRequirements, now: Optional[datetime] = None
) -> Optional[str]:
    """Return an i18n reason key if the account evidently can't post this
    message to this chat, or None if nothing in the entity says it can't.
    Users are never checked here (always None)."""
    target_type = target_type_of(entity)
    if target_type is None or target_type is TargetType.USER:
        return None
    now = now or datetime.now(timezone.utc)

    if isinstance(entity, (ChatForbidden, ChannelForbidden)):
        return "chat_targets.reason.no_access"
    if getattr(entity, "left", False):
        return "chat_targets.reason.not_member"
    if isinstance(entity, Chat):
        if getattr(entity, "migrated_to", None) is not None:
            return "chat_targets.reason.migrated"
        if getattr(entity, "deactivated", False):
            return "chat_targets.reason.deactivated"

    is_creator = bool(getattr(entity, "creator", False))
    admin_rights = getattr(entity, "admin_rights", None)

    if target_type is TargetType.CHANNEL:
        if is_creator or (admin_rights is not None and getattr(admin_rights, "post_messages", False)):
            return None
        return "chat_targets.reason.channel_admin_required"

    # Groups/supergroups: the creator and admins aren't bound by the
    # members' default restrictions or slow mode.
    if is_creator or admin_rights is not None:
        return None

    personal = getattr(entity, "banned_rights", None)
    if _is_active(personal, now):
        reason = _restriction_reason(personal, requirements, personal=True)
        if reason:
            return reason
    default = getattr(entity, "default_banned_rights", None)
    if _is_active(default, now):
        reason = _restriction_reason(default, requirements, personal=False)
        if reason:
            return reason

    if getattr(entity, "slowmode_enabled", False) and requirements.message_count > 1:
        return "chat_targets.reason.slowmode_multi"
    return None


# ---- send/resolve-time Telegram errors -> reasons ---------------------------

_ERROR_REASON_KEYS = (
    (ChatWriteForbiddenError, "chat_targets.reason.write_forbidden"),
    (ChatAdminRequiredError, "chat_targets.reason.channel_admin_required"),
    (ChannelPrivateError, "chat_targets.reason.private"),
    (UserBannedInChannelError, "chat_targets.reason.account_restricted"),
    (ChatRestrictedError, "chat_targets.reason.restricted"),
    (ChatSendMediaForbiddenError, "chat_targets.reason.media_forbidden"),
    (ChatSendGifsForbiddenError, "chat_targets.reason.media_forbidden"),
    (SlowModeMultiMsgsDisabledError, "chat_targets.reason.slowmode_multi"),
    (ChatGuestSendForbiddenError, "chat_targets.reason.not_member"),
    (ChatForbiddenError, "chat_targets.reason.no_access"),
    (TopicDeletedError, "chat_targets.reason.forum_general_unavailable"),
    (ChannelInvalidError, "chat_targets.reason.invalid"),
    (ChatIdInvalidError, "chat_targets.reason.invalid"),
    (ChatInvalidError, "chat_targets.reason.invalid"),
    (PeerIdInvalidError, "chat_targets.reason.invalid"),
)

# RPC errors newer than Telethon 1.36's generated error list arrive as a
# generic BadRequestError/ForbiddenError carrying only the message code.
_ERROR_MESSAGE_REASON_KEYS = {
    "CHAT_SEND_PLAIN_FORBIDDEN": "chat_targets.reason.plain_forbidden",
    "CHAT_SEND_PHOTOS_FORBIDDEN": "chat_targets.reason.media_forbidden",
    "CHAT_SEND_VIDEOS_FORBIDDEN": "chat_targets.reason.media_forbidden",
    "CHAT_SEND_DOCS_FORBIDDEN": "chat_targets.reason.media_forbidden",
    "CHAT_SEND_AUDIOS_FORBIDDEN": "chat_targets.reason.media_forbidden",
    "CHAT_SEND_VOICES_FORBIDDEN": "chat_targets.reason.media_forbidden",
    "CHAT_SEND_ROUNDVIDEOS_FORBIDDEN": "chat_targets.reason.media_forbidden",
    "TOPIC_CLOSED": "chat_targets.reason.forum_general_closed",
    "TOPIC_DELETED": "chat_targets.reason.forum_general_unavailable",
    "CHANNEL_PUBLIC_GROUP_NA": "chat_targets.reason.no_access",
}
_ERROR_MESSAGE_PREFIX_REASON_KEYS = (("ALLOW_PAYMENT_REQUIRED", "chat_targets.reason.paid_messages"),)


def chat_error_reason_key(exc: BaseException) -> Optional[str]:
    for error_type, key in _ERROR_REASON_KEYS:
        if isinstance(exc, error_type):
            return key
    message = getattr(exc, "message", None)
    if isinstance(message, str):
        key = _ERROR_MESSAGE_REASON_KEYS.get(message)
        if key:
            return key
        for prefix, key in _ERROR_MESSAGE_PREFIX_REASON_KEYS:
            if message.startswith(prefix):
                return key
    return None


def chat_error_reason(exc: BaseException) -> Optional[str]:
    key = chat_error_reason_key(exc)
    return tr(key) if key else None


# ---- "From my chats…" -----------------------------------------------------------

# Telegram's own service-notifications account (login codes, notices): a
# dialog every account has, never a recipient.
SERVICE_NOTIFICATIONS_ID = 777000


class DialogCategory(Enum):
    """The picker's type filter: forums count as groups, bots apart from
    people."""

    PEOPLE = "people"
    BOTS = "bots"
    GROUPS = "groups"
    CHANNELS = "channels"


@dataclass(frozen=True)
class DialogFolder:
    folder_id: int
    title: str


@dataclass(frozen=True)
class DialogTarget:
    """One dialog of the account, as the picker shows it. Never holds the
    entity itself (or an access_hash): only what's needed to show it and
    write it into the Recipients box, which resolves it again at send."""

    peer_id: int  # users: their positive id; chats: the marked id
    title: str
    username: Optional[str]
    target_type: TargetType
    is_bot: bool = False
    archived: bool = False
    last_message_date: Optional[datetime] = None
    # i18n key of why a plain text message can't be posted here, or None.
    unavailable_reason_key: Optional[str] = None
    folder_ids: FrozenSet[int] = frozenset()

    @property
    def writable(self) -> bool:
        return self.unavailable_reason_key is None

    @property
    def category(self) -> DialogCategory:
        if self.target_type is TargetType.USER:
            return DialogCategory.BOTS if self.is_bot else DialogCategory.PEOPLE
        if self.target_type is TargetType.CHANNEL:
            return DialogCategory.CHANNELS
        return DialogCategory.GROUPS

    @property
    def type_label(self) -> str:
        return tr("chat_targets.type.bot") if self.is_bot else target_type_label(self.target_type)

    @property
    def recipient_line(self) -> str:
        """What gets written into the Recipients box: @username when there
        is one (stable, readable), else the numeric id -- positive for a
        user, marked (-100…/-…) for a chat, exactly what the recipient
        parser reads back as the same addressee."""
        return f"@{self.username}" if self.username else str(self.peer_id)


@dataclass(frozen=True)
class DialogList:
    dialogs: Tuple[DialogTarget, ...]
    # Empty when the account has no folders or they couldn't be read --
    # the picker then hides its folder filter.
    folders: Tuple[DialogFolder, ...] = ()


def _is_excluded_dialog(entity: Any) -> bool:
    """Saved Messages (the account itself), deleted accounts and Telegram's
    service notifications are dialogs, but nobody to send a campaign to."""
    if not isinstance(entity, User):
        return False
    return bool(entity.is_self or entity.deleted) or entity.id == SERVICE_NOTIFICATIONS_ID


def _is_muted(dialog: Any, now: datetime) -> bool:
    settings = getattr(getattr(dialog, "dialog", None), "notify_settings", None)
    until = getattr(settings, "mute_until", None)
    if isinstance(until, datetime):
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until > now
    return isinstance(until, int) and until > now.timestamp()


def _is_unread(dialog: Any) -> bool:
    if getattr(dialog, "unread_count", 0):
        return True
    return bool(getattr(getattr(dialog, "dialog", None), "unread_mark", False))


def _input_peer_ids(peers: Any) -> FrozenSet[int]:
    ids = set()
    for peer in peers or ():
        try:
            ids.add(telethon_utils.get_peer_id(peer))
        except (TypeError, ValueError):  # InputPeerSelf/InputPeerEmpty: no id
            continue
    return frozenset(ids)


@dataclass(frozen=True)
class _FolderRule:
    """A Telegram folder (DialogFilter) as a membership test, with the
    precedence Telegram's own apps use: explicitly added chats are always
    in, explicitly removed ones always out, then the exclusion flags
    (archived/read/muted), then the chat-type flags."""

    folder: DialogFolder
    included: FrozenSet[int]
    excluded: FrozenSet[int] = frozenset()
    contacts: bool = False
    non_contacts: bool = False
    groups: bool = False
    broadcasts: bool = False
    bots: bool = False
    exclude_archived: bool = False
    exclude_read: bool = False
    exclude_muted: bool = False

    def contains(
        self, peer_id: int, entity: Any, target_type: TargetType, archived: bool, unread: bool, muted: bool
    ) -> bool:
        if peer_id in self.included:
            return True
        if peer_id in self.excluded:
            return False
        if self.exclude_archived and archived:
            return False
        if self.exclude_read and not unread:
            return False
        if self.exclude_muted and muted:
            return False
        if target_type is TargetType.USER:
            if getattr(entity, "bot", False):
                return self.bots
            return self.contacts if getattr(entity, "contact", False) else self.non_contacts
        if target_type is TargetType.CHANNEL:
            return self.broadcasts
        return self.groups


def _plain_title(title: Any) -> str:
    # Newer layers wrap a folder title in TextWithEntities.
    return str(getattr(title, "text", title) or "")


async def _load_folder_rules(client: Any) -> List[_FolderRule]:
    """The account's folders, or [] if it has none or they can't be read.
    Folders only narrow the picker's view, so a failure -- FloodWait
    included -- hides the folder filter instead of failing the whole
    list; the request is never repeated."""
    try:
        response = await client(GetDialogFiltersRequest())
    except (RPCError, ConnectionError, OSError) as exc:
        logger.warning("Dialog folders unavailable: %s", type(exc).__name__)
        return []
    rules: List[_FolderRule] = []
    for item in getattr(response, "filters", response) or ():
        if isinstance(item, DialogFilter):
            rules.append(
                _FolderRule(
                    folder=DialogFolder(item.id, _plain_title(item.title)),
                    included=_input_peer_ids(item.pinned_peers) | _input_peer_ids(item.include_peers),
                    excluded=_input_peer_ids(item.exclude_peers),
                    contacts=bool(item.contacts),
                    non_contacts=bool(item.non_contacts),
                    groups=bool(item.groups),
                    broadcasts=bool(item.broadcasts),
                    bots=bool(item.bots),
                    exclude_archived=bool(item.exclude_archived),
                    exclude_read=bool(item.exclude_read),
                    exclude_muted=bool(item.exclude_muted),
                )
            )
        elif isinstance(item, DialogFilterChatlist):
            rules.append(
                _FolderRule(
                    folder=DialogFolder(item.id, _plain_title(item.title)),
                    included=_input_peer_ids(item.pinned_peers) | _input_peer_ids(item.include_peers),
                )
            )
        # DialogFilterDefault is "All chats" -- the picker's own default.
    return rules


def _dialog_title(entity: Any, peer_id: int) -> str:
    return telethon_utils.get_display_name(entity) or getattr(entity, "username", None) or str(peer_id)


async def list_dialogs(client: Any, now: Optional[datetime] = None) -> DialogList:
    """Every dialog of the account (archived ones included; migrated basic
    groups left out, since their supergroup is listed), in Telegram's own
    order, with the folders each belongs to. People and bots count as
    writable; a chat is writable if check_send_rights allows a plain text
    message. Reads only the dialog list and the folder list -- nothing is
    joined, resolved or downloaded (no avatars). FloodWaitError from the
    dialog list propagates to the caller untouched."""
    now = now or datetime.now(timezone.utc)
    text_only = SendRequirements(has_plain_text_message=True, message_count=1)
    rows: List[Tuple[Any, Any, int, TargetType]] = []
    seen: set = set()
    async for dialog in client.iter_dialogs(ignore_migrated=True):
        entity = dialog.entity
        target_type = target_type_of(entity)
        if target_type is None or _is_excluded_dialog(entity):
            continue
        peer_id = telethon_utils.get_peer_id(entity)
        if peer_id in seen:
            continue
        seen.add(peer_id)
        rows.append((dialog, entity, peer_id, target_type))

    rules = await _load_folder_rules(client) if rows else []
    targets: List[DialogTarget] = []
    for dialog, entity, peer_id, target_type in rows:
        archived = bool(getattr(dialog, "archived", False))
        folder_ids: FrozenSet[int] = frozenset()
        if rules:
            unread, muted = _is_unread(dialog), _is_muted(dialog, now)
            folder_ids = frozenset(
                rule.folder.folder_id
                for rule in rules
                if rule.contains(peer_id, entity, target_type, archived, unread, muted)
            )
        is_user = target_type is TargetType.USER
        targets.append(
            DialogTarget(
                peer_id=peer_id,
                title=_dialog_title(entity, peer_id),
                username=getattr(entity, "username", None) or None,
                target_type=target_type,
                is_bot=is_user and bool(getattr(entity, "bot", False)),
                archived=archived,
                last_message_date=getattr(dialog, "date", None),
                unavailable_reason_key=None if is_user else check_send_rights(entity, text_only, now),
                folder_ids=folder_ids,
            )
        )
    return DialogList(dialogs=tuple(targets), folders=tuple(rule.folder for rule in rules))


# Superseded by list_dialogs; removed once the picker moves over.
@dataclass(frozen=True)
class ChatTarget:
    peer_id: int  # marked id
    title: str
    username: Optional[str]
    target_type: TargetType

    @property
    def recipient_line(self) -> str:
        """What gets written into the Recipients box: @username when the
        chat has one (stable, readable), else the marked numeric id."""
        return f"@{self.username}" if self.username else str(self.peer_id)


async def list_writable_chats(client: Any) -> List[ChatTarget]:
    """Every group/supergroup/channel among the account's own dialogs that
    a plain text message could be posted to right now (per
    check_send_rights). Users and chats the account can't write to are
    left out. FloodWaitError propagates to the caller untouched."""
    text_only = SendRequirements(has_plain_text_message=True, message_count=1)
    targets: List[ChatTarget] = []
    seen: set = set()
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        target_type = target_type_of(entity)
        if target_type is None or not target_type.is_chat:
            continue
        if check_send_rights(entity, text_only) is not None:
            continue
        peer_id = chat_peer_id(entity)
        if peer_id in seen:
            continue
        seen.add(peer_id)
        targets.append(
            ChatTarget(
                peer_id=peer_id,
                title=getattr(entity, "title", "") or "",
                username=getattr(entity, "username", None) or None,
                target_type=target_type,
            )
        )
    return targets
