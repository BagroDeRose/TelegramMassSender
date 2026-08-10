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
from telethon.tl.functions.messages import UploadMediaRequest
from telethon.tl.types import Chat, InputMediaPhoto, Photo, User

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
    file_to_media_calls: List[Any] = field(default_factory=list)
    raw_requests: List[Any] = field(default_factory=list)

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

    async def get_input_entity(self, entity: Any):
        return entity

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
        if isinstance(request, UploadMediaRequest):
            response = MagicMock()
            response.photo = MagicMock(spec=Photo)
            return response
        return MagicMock()
