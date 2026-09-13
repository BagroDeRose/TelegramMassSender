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
        self.logged_out: List[str] = []
        # session_name -> exception instance: log_out() itself never
        # raises (see ClientManager.log_out's contract), it just records
        # the attempt failed here instead -- mirrors the real
        # implementation's best-effort/never-blocks-removal behavior.
        self.raise_on_log_out: Dict[str, BaseException] = {}
        self.log_out_failures: List[str] = []

    async def connect(self, session_name: str) -> None:
        return None

    async def is_authorized(self, session_name: str) -> bool:
        if session_name in self.raise_on_check:
            raise self.raise_on_check[session_name]
        return session_name in self.authorized_sessions

    async def disconnect(self, session_name: str) -> None:
        self.disconnected.append(session_name)

    async def log_out(self, session_name: str) -> None:
        self.logged_out.append(session_name)
        if session_name in self.raise_on_log_out:
            self.log_out_failures.append(session_name)

    def remove(self, session_name: str) -> None:
        self.removed.append(session_name)

    def get_active_client(self, session_name: str):
        # This fake never models real TelegramClient instances (only
        # authorization booleans), so there is never a "live client" to
        # return -- None is the honest answer, matching the real
        # ClientManager.get_active_client's behavior for a session it
        # hasn't created a client for yet.
        return None
