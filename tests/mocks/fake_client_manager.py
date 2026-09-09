"""Duck-compatible stand-in for app.telegram.client_manager.ClientManager,
shared by tests that exercise AccountManager without touching the real
Telegram network. Configure per-session-name behavior via
`authorized_sessions` / `raise_on_check`, mirroring
tests/mocks/mock_telegram_client.py's style.
"""
from __future__ import annotations

from typing import Dict, List, Set


class FakeClientManager:
    def __init__(self) -> None:
        self.authorized_sessions: Set[str] = set()
        self.raise_on_check: Dict[str, BaseException] = {}  # session_name -> exception instance
        self.disconnected: List[str] = []
        self.removed: List[str] = []

    async def connect(self, session_name: str) -> None:
        return None

    async def is_authorized(self, session_name: str) -> bool:
        if session_name in self.raise_on_check:
            raise self.raise_on_check[session_name]
        return session_name in self.authorized_sessions

    async def disconnect(self, session_name: str) -> None:
        self.disconnected.append(session_name)

    def remove(self, session_name: str) -> None:
        self.removed.append(session_name)
