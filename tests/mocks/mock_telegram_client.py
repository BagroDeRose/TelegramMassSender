"""Mock Telegram client for unit tests (spec item 59).

No test in this suite talks to the real Telegram network. Configure
per-recipient behaviour via `entity_behavior` (what get_entity should do)
and `send_behavior` (what send_message/send_file should do), keyed by the
exact identifier used to look the recipient up (username string or
numeric id).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    PeerIdInvalidError,
    UserIsBlockedError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)
from telethon.tl.types import Chat, User

PERMANENT_ERROR_FACTORIES = {
    "not_found": lambda: UsernameNotOccupiedError(request=None),
    "blocked": lambda: UserIsBlockedError(request=None),
    "invalid_id": lambda: PeerIdInvalidError(request=None),
    "write_forbidden": lambda: ChatWriteForbiddenError(request=None),
    "privacy_restricted": lambda: UserPrivacyRestrictedError(request=None),
}


def make_flood_wait(seconds: int) -> FloodWaitError:
    return FloodWaitError(request=None, capture=seconds)


def make_fake_user(identifier: Any) -> User:
    user = MagicMock(spec=User)
    user.id = identifier if isinstance(identifier, int) else abs(hash(identifier)) % (10**8)
    user.username = identifier if isinstance(identifier, str) else None
    return user


def make_fake_chat() -> Chat:
    return MagicMock(spec=Chat)


@dataclass
class MockTelegramClient:
    """Duck-compatible stand-in for telethon.TelegramClient, covering only
    the surface this application actually calls."""

    entity_behavior: Dict[Any, str] = field(default_factory=dict)
    send_behavior: Dict[Any, Any] = field(default_factory=dict)
    sent_messages: List[Tuple] = field(default_factory=list)
    connected: bool = False
    get_entity_calls: int = 0

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
        behavior = self.entity_behavior.get(identifier, "found")
        if behavior == "found":
            return make_fake_user(identifier)
        if behavior == "not_a_user":
            return make_fake_chat()
        if behavior in PERMANENT_ERROR_FACTORIES:
            raise PERMANENT_ERROR_FACTORIES[behavior]()
        raise ValueError(f"unknown entity behavior: {behavior}")

    async def send_message(self, entity, text, formatting_entities=None):
        outcome = self.send_behavior.get(entity)
        if isinstance(outcome, BaseException):
            raise outcome
        self.sent_messages.append(("message", entity, text, formatting_entities))
        return None

    async def send_file(self, entity, files, caption=None, formatting_entities=None):
        outcome = self.send_behavior.get(entity)
        if isinstance(outcome, BaseException):
            raise outcome
        self.sent_messages.append(("file", entity, files, caption, formatting_entities))
        return None
