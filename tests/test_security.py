"""Security tests (spec item 58): secrets must never land on disk in
plaintext, and must never survive into the log output.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.logging.logger import SecretScrubbingFilter
from app.security.secure_storage import SecureStorage


def test_api_credentials_not_stored_in_plaintext(tmp_path: Path):
    secrets_path = tmp_path / "secrets.dat"
    storage = SecureStorage(secrets_path)

    assert storage.load_api_credentials() is None

    api_hash = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    storage.save_api_credentials(123456, api_hash)

    raw_bytes = secrets_path.read_bytes()
    assert api_hash.encode() not in raw_bytes
    assert b"123456" not in raw_bytes

    loaded = storage.load_api_credentials()
    assert loaded is not None
    assert loaded.api_id == 123456
    assert loaded.api_hash == api_hash

    storage.clear_api_credentials()
    assert storage.load_api_credentials() is None


def _filtered_message(raw_message: str) -> str:
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=raw_message, args=(), exc_info=None,
    )
    SecretScrubbingFilter().filter(record)
    return record.getMessage()


def test_api_hash_scrubbed_from_log_message():
    scrubbed = _filtered_message("connecting with api_hash=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
    assert "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" not in scrubbed
    assert "REDACTED" in scrubbed


def test_api_id_scrubbed_from_log_message():
    scrubbed = _filtered_message("using api_id=1234567 for this session")
    assert "1234567" not in scrubbed


def test_password_scrubbed_from_log_message():
    scrubbed = _filtered_message("2fa password=SuperSecret123 accepted")
    assert "SuperSecret123" not in scrubbed


def test_session_value_scrubbed_from_log_message():
    scrubbed = _filtered_message("session=abcdefghijklmnopqrstuvwxyz1234567890 loaded")
    assert "abcdefghijklmnopqrstuvwxyz1234567890" not in scrubbed


def test_normal_log_messages_pass_through_unchanged():
    scrubbed = _filtered_message("Аккаунт успешно авторизован: +70001112233")
    assert scrubbed == "Аккаунт успешно авторизован: +70001112233"
