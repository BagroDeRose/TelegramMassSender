"""Telethon TelegramClient lifecycle management.

Each account has exactly one TelegramClient bound to exactly one session
file (see app.config.paths.get_session_path) -- sessions are never shared
or mixed between accounts (spec item 7). This module owns creation and
connect/disconnect of clients; app.telegram.account_manager builds
account-level operations (add/authorize/switch/delete) on top of it.

api_id/api_hash identify the *application* with Telegram, not the user --
it is correct and expected for every account's client in this app to be
constructed with the same api_id/api_hash pair.
"""
from __future__ import annotations

from typing import Dict, Optional

from telethon import TelegramClient

from app.config.paths import get_session_path
from app.logging.logger import get_logger

logger = get_logger()


class ClientManager:
    def __init__(self, api_id: int, api_hash: str) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._clients: Dict[str, TelegramClient] = {}

    def get_or_create(self, session_name: str) -> TelegramClient:
        client = self._clients.get(session_name)
        if client is None:
            session_path = str(get_session_path(session_name))
            client = TelegramClient(session_path, self._api_id, self._api_hash)
            self._clients[session_name] = client
        return client

    async def connect(self, session_name: str) -> TelegramClient:
        client = self.get_or_create(session_name)
        if not client.is_connected():
            await client.connect()
            logger.info("Telegram client подключён: %s", session_name)
        return client

    async def is_authorized(self, session_name: str) -> bool:
        client = await self.connect(session_name)
        return await client.is_user_authorized()

    async def disconnect(self, session_name: str) -> None:
        client = self._clients.get(session_name)
        if client is not None:
            # client.disconnect() is safe to call even if connect() was
            # never invoked -- it always closes the underlying session
            # file, which is required before that file can be deleted.
            await client.disconnect()
            logger.info("Telegram client отключён: %s", session_name)

    async def disconnect_all(self) -> None:
        for session_name in list(self._clients.keys()):
            await self.disconnect(session_name)

    def get_active_client(self, session_name: str) -> Optional[TelegramClient]:
        return self._clients.get(session_name)

    def remove(self, session_name: str) -> None:
        self._clients.pop(session_name, None)
