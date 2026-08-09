"""Domain-level secure storage for Telegram API credentials.

API ID/API Hash are the only long-lived secret persisted to disk (as a
DPAPI-encrypted blob, see app.security.dpapi). The 2FA password is never
written to disk anywhere in this codebase: it is used once during login
to complete the auth handshake (app.telegram.authentication) and then
discarded.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config.paths import get_secrets_path
from app.security.dpapi import decrypt_bytes, encrypt_bytes


@dataclass(frozen=True)
class ApiCredentials:
    api_id: int
    api_hash: str


class SecureStorage:
    def __init__(self, secrets_path: Optional[Path] = None) -> None:
        self._path = secrets_path or get_secrets_path()

    def save_api_credentials(self, api_id: int, api_hash: str) -> None:
        payload = json.dumps({"api_id": api_id, "api_hash": api_hash}).encode("utf-8")
        encrypted = encrypt_bytes(payload)
        self._path.write_bytes(encrypted)

    def load_api_credentials(self) -> Optional[ApiCredentials]:
        if not self._path.exists():
            return None
        try:
            encrypted = self._path.read_bytes()
            decrypted = decrypt_bytes(encrypted)
            data = json.loads(decrypted.decode("utf-8"))
            return ApiCredentials(api_id=int(data["api_id"]), api_hash=str(data["api_hash"]))
        except Exception:
            # Corrupted, foreign-user-encrypted, or missing payload: treat as
            # "not configured" rather than crashing -- the UI will prompt the
            # user to re-enter API ID/Hash.
            return None

    def clear_api_credentials(self) -> None:
        if self._path.exists():
            self._path.unlink()
