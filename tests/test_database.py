"""Tests for app.database.database.Database's schema migration.

No prior coverage existed for this module. accounts.local_alias is the
first column ever added to an existing table in this app's history --
CREATE TABLE IF NOT EXISTS is a no-op against a database file created by
an earlier version of the app, so a real ALTER TABLE migration path is
required, and needs its own test since nothing else exercises it.
"""
from __future__ import annotations

import sqlite3

from app.database.database import Database
from app.database.repositories import AccountRepository


def _create_pre_migration_database(path):
    """A database file shaped exactly like one created by a version of
    this app before the local_alias column existed -- the accounts table
    is created directly via raw SQL, deliberately bypassing Database's own
    (already-migrated) SCHEMA constant."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL UNIQUE,
            telegram_user_id INTEGER,
            username TEXT,
            display_name TEXT,
            session_name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_used_at TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO accounts (phone, telegram_user_id, username, display_name, session_name) VALUES (?, ?, ?, ?, ?)",
        ("+70001112233", 42, "olduser", "Old User", "account_preexisting"),
    )
    conn.commit()
    conn.close()


def test_opening_a_pre_migration_database_adds_the_local_alias_column(tmp_path):
    db_path = tmp_path / "app.db"
    _create_pre_migration_database(db_path)

    db = Database(db_path=db_path)
    conn = db.connect()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
    db.close()

    assert "local_alias" in columns


def test_migration_preserves_existing_account_data(tmp_path):
    db_path = tmp_path / "app.db"
    _create_pre_migration_database(db_path)

    db = Database(db_path=db_path)
    repo = AccountRepository(db)
    accounts = repo.list_all()
    db.close()

    assert len(accounts) == 1
    account = accounts[0]
    assert account.phone == "+70001112233"
    assert account.telegram_user_id == 42
    assert account.username == "olduser"
    assert account.display_name == "Old User"
    assert account.session_name == "account_preexisting"
    assert account.local_alias is None  # new column, no value ever set for this pre-existing row


def test_migrated_database_can_then_rename_the_pre_existing_account(tmp_path):
    db_path = tmp_path / "app.db"
    _create_pre_migration_database(db_path)

    db = Database(db_path=db_path)
    repo = AccountRepository(db)
    account = repo.list_all()[0]

    repo.rename(account.id, "My work account")

    reloaded = repo.get_by_id(account.id)
    db.close()
    assert reloaded.local_alias == "My work account"


def test_migration_is_idempotent_across_repeated_opens(tmp_path):
    # Reopening an already-migrated database (the normal case on every
    # app launch after the first one following this change) must not
    # raise "duplicate column" or otherwise fail.
    db_path = tmp_path / "app.db"
    _create_pre_migration_database(db_path)

    db1 = Database(db_path=db_path)
    db1.connect()
    db1.close()

    db2 = Database(db_path=db_path)
    db2.connect()  # must not raise
    columns = {row[1] for row in db2.connect().execute("PRAGMA table_info(accounts)")}
    db2.close()

    assert "local_alias" in columns


def test_a_freshly_created_database_already_has_the_column(tmp_path):
    # The normal (non-migration) path: a brand-new install's database is
    # created straight from SCHEMA, which already declares local_alias.
    db_path = tmp_path / "app.db"
    db = Database(db_path=db_path)
    conn = db.connect()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
    db.close()

    assert "local_alias" in columns
