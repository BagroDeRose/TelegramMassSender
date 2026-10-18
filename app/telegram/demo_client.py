"""Fully local, simulated Telegram client for Demo Mode (ROADMAP v2.0).

Duck-compatible with telethon.TelegramClient/app.telegram.client_manager.
ClientManager for exactly the surface this app calls (see
app.telegram.sender/media_sender/recipient_resolver) -- entity
resolution, message/media sending, connection state -- all fabricated
locally with realistic random outcomes, never opening a network
connection or touching a real session file.

Deliberately a separate implementation from
tests/mocks/mock_telegram_client.py rather than a shared one, even though
the two look similar: that mock must behave exactly as each test
explicitly configures it, deterministically, and 600+ tests already
depend on that today. This client instead wants organic randomness (so a
demo doesn't feel scripted) -- gating that behind opt-in flags on the
test double would risk destabilizing the existing suite for a UX concern
tests don't have. ~150 lines of controlled duplication is a smaller risk
than sharing one class between two genuinely different needs.

Groups/channels: the demo account "is in" a fixed set of simulated chats
(DEMO_CHATS, real Telethon Chat/Channel objects so the app's own rights
preflight runs on them unchanged), each set up for one realistic outcome:
posting works, no admin rights in someone else's channel, members may not
write, no media allowed, a forum, and a slow-mode chat that only accepts
one message per DEMO_SLOWMODE_SECONDS (the demo account "posted there
just now" when the session starts, so the first campaign meets slow mode
and a later Retry succeeds). Only one invite link is "already joined";
any other is a chat the account isn't in -- nothing ever joins anything.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

from telethon import utils as telethon_utils
from telethon.errors import SlowModeWaitError, UserIsBlockedError, UsernameNotOccupiedError
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
    InputMediaPhoto,
    Photo,
    User,
)
from telethon.tl.types.messages import DialogFilters

# Simulated failure rate for resolving/sending to a demo recipient --
# high enough to realistically exercise retry/results/diagnostics (the
# whole point of a demo showing those features), low enough that most of
# a demo campaign still visibly succeeds.
FAILURE_RATE = 0.12

_DEMO_FIRST_NAMES = (
    "Anna",
    "Ivan",
    "Maria",
    "Pavel",
    "Olga",
    "Dmitry",
    "Elena",
    "Sergey",
    "Natalia",
    "Andrei",
    "Ekaterina",
    "Mikhail",
)


def _demo_first_name(identifier: Any) -> str:
    return _DEMO_FIRST_NAMES[abs(hash(identifier)) % len(_DEMO_FIRST_NAMES)]


DEMO_SLOWMODE_SECONDS = 60
DEMO_INVITE_HASH = "DemoTeamInvite"


def _demo_channel(channel_id: int, title: str, username: Optional[str], **flags: Any) -> Channel:
    broadcast = flags.pop("broadcast", False)
    return Channel(
        id=channel_id,
        title=title,
        photo=None,
        date=None,
        broadcast=broadcast or None,
        megagroup=(not broadcast) or None,
        access_hash=channel_id * 31 + 7,
        username=username,
        **flags,
    )


def make_demo_chats() -> List[Any]:
    """Fresh objects per client -- Telethon TL objects are mutable."""
    return [
        _demo_channel(1900000001, "Demo News", "demo_news", broadcast=True, creator=True),
        _demo_channel(1900000002, "Demo Team Chat", "demo_team_chat"),
        Chat(id=900000003, title="Demo Family", photo=None, participants_count=4, date=None, version=1),
        _demo_channel(1900000004, "Demo Forum", "demo_forum", forum=True),
        _demo_channel(
            1900000005,
            "Demo Partner Channel",
            "demo_partner_channel",
            broadcast=True,
            admin_rights=ChatAdminRights(edit_messages=True),
        ),
        _demo_channel(
            1900000006,
            "Demo Read-Only Group",
            "demo_readonly_group",
            default_banned_rights=ChatBannedRights(until_date=None, send_messages=True),
        ),
        _demo_channel(
            1900000007,
            "Demo Text-Only Group",
            "demo_text_only",
            default_banned_rights=ChatBannedRights(until_date=None, send_media=True),
        ),
        _demo_channel(1900000008, "Demo Slow Chat", "demo_slow_chat", slowmode_enabled=True),
    ]


class _DemoDialog:
    def __init__(self, entity: Any) -> None:
        self.entity = entity
        self.id = telethon_utils.get_peer_id(entity) if isinstance(entity, (Chat, Channel)) else entity.id
        self.name = getattr(entity, "title", None) or getattr(entity, "first_name", None) or ""


def _is_demo_chat(entity: Any) -> bool:
    return isinstance(entity, (Chat, Channel))


def make_demo_user(identifier: Any) -> User:
    user = MagicMock(spec=User)
    user.id = identifier if isinstance(identifier, int) else abs(hash(identifier)) % (10**8)
    user.username = identifier if isinstance(identifier, str) else None
    user.first_name = _demo_first_name(identifier)
    user.last_name = None
    return user


@dataclass
class DemoTelegramClient:
    """One simulated 'connection' per demo account. `sent_messages`
    mirrors MockTelegramClient's own record shape so tooling built
    against one reads naturally against the other."""

    connected: bool = False
    sent_messages: List[Tuple] = field(default_factory=list)
    chats: List[Any] = field(default_factory=make_demo_chats)
    # Marked chat id -> time.monotonic() of the last post there; the slow
    # chat starts "just posted to" (see the module docstring).
    last_chat_post: Dict[int, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for chat in self.chats:
            if getattr(chat, "slowmode_enabled", False):
                self.last_chat_post.setdefault(telethon_utils.get_peer_id(chat), time.monotonic())

    def _chat_by_identifier(self, identifier: Any) -> Optional[Any]:
        for chat in self.chats:
            if isinstance(identifier, str) and getattr(chat, "username", None) == identifier:
                return chat
            if isinstance(identifier, int) and identifier < 0 and telethon_utils.get_peer_id(chat) == identifier:
                return chat
        return None

    def _post_to_chat(self, entity: Any) -> None:
        """Slow mode, as Telegram applies it to a non-admin member."""
        peer_id = telethon_utils.get_peer_id(entity)
        if getattr(entity, "slowmode_enabled", False):
            last = self.last_chat_post.get(peer_id)
            if last is not None:
                remaining = DEMO_SLOWMODE_SECONDS - (time.monotonic() - last)
                if remaining > 0:
                    raise SlowModeWaitError(request=None, capture=max(1, int(remaining)))
        self.last_chat_post[peer_id] = time.monotonic()

    async def connect(self) -> None:
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    async def disconnect(self) -> None:
        self.connected = False

    async def log_out(self) -> None:
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return True

    async def get_entity(self, identifier: Any) -> Any:
        chat = self._chat_by_identifier(identifier)
        if chat is not None:
            return chat
        if isinstance(identifier, int) and identifier < 0:
            raise ValueError(f"Could not find the input entity for {identifier}")
        if random.random() < FAILURE_RATE:
            raise UsernameNotOccupiedError(request=None)
        return make_demo_user(identifier)

    async def iter_dialogs(self, *args: Any, **kwargs: Any):
        yield _DemoDialog(User(id=700000001, first_name="Anna", username="demo_friend", access_hash=700000001 * 31 + 7))
        for chat in self.chats:
            yield _DemoDialog(chat)

    async def get_dialogs(self, *args: Any, **kwargs: Any) -> List[Any]:
        return [dialog async for dialog in self.iter_dialogs()]

    async def get_input_entity(self, entity: Any) -> Any:
        return entity

    async def send_message(self, entity: Any, text: str, formatting_entities: Optional[list] = None) -> None:
        if _is_demo_chat(entity):
            self._post_to_chat(entity)
        elif random.random() < FAILURE_RATE:
            raise UserIsBlockedError(request=None)
        self.sent_messages.append(("message", entity, text, formatting_entities))

    async def send_file(
        self, entity: Any, files: Any, caption: Optional[str] = None, formatting_entities: Optional[list] = None
    ) -> None:
        if _is_demo_chat(entity):
            self._post_to_chat(entity)
        elif random.random() < FAILURE_RATE:
            raise UserIsBlockedError(request=None)
        self.sent_messages.append(("file", entity, files, caption, formatting_entities))

    async def _file_to_media(self, file: Any, **kwargs: Any) -> Tuple[None, Any, None]:
        # Matches MockTelegramClient's approach: a stand-in good enough
        # for the calling code's isinstance checks, not a faithful
        # reproduction of Telethon's actual upload internals -- nothing
        # here ever reaches a real network call to compare against.
        return None, MagicMock(spec=InputMediaPhoto), None

    async def __call__(self, request: Any) -> Any:
        if isinstance(request, GetDialogFiltersRequest):
            return DialogFilters(filters=[])
        if isinstance(request, CheckChatInviteRequest):
            if request.hash == DEMO_INVITE_HASH:
                return ChatInviteAlready(chat=self._chat_by_identifier("demo_team_chat"))
            return ChatInvite(title="Demo Private Club", photo=None, participants_count=12, color=0)
        if isinstance(request, SendMultiMediaRequest) and _is_demo_chat(request.peer):
            self._post_to_chat(request.peer)
            self.sent_messages.append(("album", request.peer, request.multi_media, None, None))
            return MagicMock()
        if isinstance(request, UploadMediaRequest):
            response = MagicMock()
            response.photo = MagicMock(spec=Photo)
            return response
        if isinstance(request, ResolvePhoneRequest):
            response = MagicMock()
            response.users = [] if random.random() < FAILURE_RATE else [make_demo_user(request.phone)]
            return response
        return MagicMock()


class DemoClientManager:
    """Duck-compatible stand-in for app.telegram.client_manager.ClientManager
    -- every demo 'account' gets its own DemoTelegramClient, never a real
    Telethon client or session file."""

    def __init__(self) -> None:
        self._clients: Dict[str, DemoTelegramClient] = {}

    def get_or_create(self, session_name: str) -> DemoTelegramClient:
        client = self._clients.get(session_name)
        if client is None:
            client = DemoTelegramClient()
            self._clients[session_name] = client
        return client

    async def connect(self, session_name: str) -> DemoTelegramClient:
        client = self.get_or_create(session_name)
        if not client.is_connected():
            await client.connect()
        return client

    async def is_authorized(self, session_name: str) -> bool:
        client = await self.connect(session_name)
        return await client.is_user_authorized()

    async def disconnect(self, session_name: str) -> None:
        client = self._clients.get(session_name)
        if client is not None:
            await client.disconnect()

    async def disconnect_all(self) -> None:
        for session_name in list(self._clients.keys()):
            await self.disconnect(session_name)

    async def log_out(self, session_name: str) -> None:
        client = self._clients.get(session_name)
        if client is not None:
            await client.log_out()

    def get_active_client(self, session_name: str) -> Optional[DemoTelegramClient]:
        return self._clients.get(session_name)

    def remove(self, session_name: str) -> None:
        self._clients.pop(session_name, None)


# A stable, obviously-fake phone number -- never a real E.164 range, and
# distinct enough that it can't be mistaken for a real recipient/account
# anywhere it's displayed (account cards, diagnostics, logs).
DEMO_ACCOUNT_PHONE = "+10000000000"
DEMO_ACCOUNT_USERNAME = "demo_account"
DEMO_ACCOUNT_DISPLAY_NAME = "Demo Account"
