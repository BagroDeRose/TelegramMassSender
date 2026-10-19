"""Session files on disk: where Telethon writes them, that they survive a
restart, that Diagnostics counts them, and that the test suite never
touches the user's real %APPDATA%.

Diagnostics used to report "session files found: 0 of 2" for connected
accounts: it checked get_session_path(name), the path *without* the
".session" extension Telethon appends itself, which never exists."""
from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient

from app.config.paths import get_app_data_dir, get_session_file_path, get_session_path
from app.database.database import Database
from app.database.repositories import AccountRepository
from app.diagnostics import collect_diagnostics
from app.i18n import tr
from app.telegram.demo_client import DEMO_ACCOUNT_PHONE
from tests.conftest import REAL_APPDATA

API_HASH = "0123456789abcdef0123456789abcdef"  # synthetic


def _client(session_name: str) -> TelegramClient:
    return TelegramClient(str(get_session_path(session_name)), 12345, API_HASH)


def _close(client: TelegramClient) -> None:
    client.session.close()


def test_the_test_suite_never_uses_the_real_appdata():
    data_dir = get_app_data_dir().resolve()
    assert "tms_test_appdata_" in str(data_dir)
    if REAL_APPDATA:
        assert not str(data_dir).lower().startswith(str(Path(REAL_APPDATA).resolve()).lower())


async def test_session_file_path_is_the_file_telethon_writes():
    client = _client("account_path_check")
    try:
        client.session.save()
        assert get_session_file_path("account_path_check").is_file()
        assert not get_session_path("account_path_check").exists()  # the extension-less name never exists
    finally:
        _close(client)


async def test_a_saved_session_is_restored_by_the_next_run():
    first = _client("account_restart")
    try:
        first.session.set_dc(2, "149.154.167.51", 443)
        first.session.save()
    finally:
        _close(first)
    second = _client("account_restart")  # as after an application restart
    try:
        assert second.session.dc_id == 2
        assert second.session.server_address == "149.154.167.51"
    finally:
        _close(second)


def _session_storage_value(db: Database) -> str:
    report = collect_diagnostics(db, "x", "y")
    return dict(report.fields)[tr("diagnostics.field.session_storage")]


async def test_diagnostics_counts_real_session_files(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = AccountRepository(db)
        repo.create("+70001112233", "account_with_session")
        repo.create("+70004445566", "account_without_session")
        client = _client("account_with_session")
        try:
            client.session.save()
        finally:
            _close(client)
        assert _session_storage_value(db) == tr("diagnostics.session_storage.summary", present=1, total=2)

        other = _client("account_without_session")
        try:
            other.session.save()
        finally:
            _close(other)
        assert _session_storage_value(db) == tr("diagnostics.session_storage.summary", present=2, total=2)
    finally:
        db.close()


async def test_diagnostics_leaves_the_demo_account_out(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        repo = AccountRepository(db)
        repo.create("+70001112233", "account_real_one")
        repo.create(DEMO_ACCOUNT_PHONE, "account_demo")
        client = _client("account_real_one")
        try:
            client.session.save()
        finally:
            _close(client)
        # 1 of 1: Demo Mode never opens a session file, so it isn't counted.
        assert _session_storage_value(db) == tr("diagnostics.session_storage.summary", present=1, total=1)
    finally:
        db.close()


def test_only_the_demo_account_counts_as_no_accounts(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    try:
        AccountRepository(db).create(DEMO_ACCOUNT_PHONE, "account_demo")
        assert _session_storage_value(db) == tr("diagnostics.session_storage.no_accounts")
    finally:
        db.close()
