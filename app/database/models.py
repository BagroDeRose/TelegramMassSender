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


@dataclass
class SavedReport:
    id: Optional[int]
    name: str
    created_at: str
    total: int
    successful: int
    failed: int
    skipped: int
    file_path: str
    is_favorite: bool


@dataclass
class Preset:
    """DB row shape only -- message_entities/attachment_paths are the raw
    JSON strings as stored; app.campaign.presets is where those get
    serialized/deserialized into real TypeMessageEntity/Path objects, same
    split as SavedReport (this module) vs. app.campaign.report_library."""

    id: Optional[int]
    name: str
    created_at: str
    message_text: str
    message_entities: str
    attachment_paths: str
    min_delay_seconds: Optional[int]
    max_delay_seconds: Optional[int]
