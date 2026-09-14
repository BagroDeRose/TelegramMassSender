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
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

from telethon.errors import UserIsBlockedError, UsernameNotOccupiedError
from telethon.tl.functions.contacts import ResolvePhoneRequest
from telethon.tl.functions.messages import UploadMediaRequest
from telethon.tl.types import InputMediaPhoto, Photo, User

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

    async def get_entity(self, identifier: Any) -> User:
        if random.random() < FAILURE_RATE:
            raise UsernameNotOccupiedError(request=None)
        return make_demo_user(identifier)

    async def get_input_entity(self, entity: Any) -> Any:
        return entity

    async def send_message(self, entity: Any, text: str, formatting_entities: Optional[list] = None) -> None:
        if random.random() < FAILURE_RATE:
            raise UserIsBlockedError(request=None)
        self.sent_messages.append(("message", entity, text, formatting_entities))

    async def send_file(
        self, entity: Any, files: Any, caption: Optional[str] = None, formatting_entities: Optional[list] = None
    ) -> None:
        if random.random() < FAILURE_RATE:
            raise UserIsBlockedError(request=None)
        self.sent_messages.append(("file", entity, files, caption, formatting_entities))

    async def _file_to_media(self, file: Any, **kwargs: Any) -> Tuple[None, Any, None]:
        # Matches MockTelegramClient's approach: a stand-in good enough
        # for the calling code's isinstance checks, not a faithful
        # reproduction of Telethon's actual upload internals -- nothing
        # here ever reaches a real network call to compare against.
        return None, MagicMock(spec=InputMediaPhoto), None

    async def __call__(self, request: Any) -> Any:
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
