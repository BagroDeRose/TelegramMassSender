"""Data models mirroring the SQLite schema. No secrets live here."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Account:
    id: Optional[int]
    phone: str
    telegram_user_id: Optional[int]
    username: Optional[str]
    display_name: Optional[str]
    session_name: str
    created_at: str
    last_used_at: Optional[str]
