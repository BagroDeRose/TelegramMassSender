"""Windows DPAPI wrapper for encrypting small secret blobs at rest.

DPAPI (CryptProtectData/CryptUnprotectData) ties encryption to the
current Windows user profile -- only that same OS user account can
decrypt the resulting blob, with no key management required from us.
Used for the small API ID/API Hash blob. Telethon's own .session files
are left untouched (Telethon manages them directly by path) but live
outside the repo, under %APPDATA%, never committed to version control.
"""
from __future__ import annotations

import win32cryptcon
import win32crypt

_ENTROPY = b"TelegramMassSender.v1"


def encrypt_bytes(data: bytes, description: str = "TelegramMassSender secret") -> bytes:
    encrypted = win32crypt.CryptProtectData(
        data,
        description,
        _ENTROPY,
        None,
        None,
        win32cryptcon.CRYPTPROTECT_UI_FORBIDDEN,
    )
    return encrypted


def decrypt_bytes(blob: bytes) -> bytes:
    _description, decrypted = win32crypt.CryptUnprotectData(
        blob,
        _ENTROPY,
        None,
        None,
        win32cryptcon.CRYPTPROTECT_UI_FORBIDDEN,
    )
    return decrypted
