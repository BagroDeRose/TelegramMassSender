"""Repository layer for accounts and settings persistence."""
from __future__ import annotations

from typing import List, Optional

from app.database.database import Database
from app.database.models import Account


class AccountRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def create(self, phone: str, session_name: str) -> Account:
        with self._db.cursor() as cur:
            cur.execute(
                "INSERT INTO accounts (phone, session_name) VALUES (?, ?)",
                (phone, session_name),
            )
            account_id = cur.lastrowid
        account = self.get_by_id(account_id)
        assert account is not None
        return account

    def get_by_id(self, account_id: int) -> Optional[Account]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
            row = cur.fetchone()
        return self._row_to_account(row) if row else None

    def get_by_phone(self, phone: str) -> Optional[Account]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM accounts WHERE phone = ?", (phone,))
            row = cur.fetchone()
        return self._row_to_account(row) if row else None

    def list_all(self) -> List[Account]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM accounts ORDER BY created_at ASC")
            rows = cur.fetchall()
        return [self._row_to_account(row) for row in rows]

    def update_profile(
        self,
        account_id: int,
        telegram_user_id: int,
        username: Optional[str],
        display_name: Optional[str],
    ) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                """UPDATE accounts
                   SET telegram_user_id = ?, username = ?, display_name = ?
                   WHERE id = ?""",
                (telegram_user_id, username, display_name, account_id),
            )

    def touch_last_used(self, account_id: int) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                "UPDATE accounts SET last_used_at = datetime('now') WHERE id = ?",
                (account_id,),
            )

    def delete(self, account_id: int) -> None:
        with self._db.cursor() as cur:
            cur.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    @staticmethod
    def _row_to_account(row) -> Account:
        return Account(
            id=row["id"],
            phone=row["phone"],
            telegram_user_id=row["telegram_user_id"],
            username=row["username"],
            display_name=row["display_name"],
            session_name=row["session_name"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
        )


class SettingsRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._db.cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )

    def get_all(self) -> dict:
        with self._db.cursor() as cur:
            cur.execute("SELECT key, value FROM settings")
            rows = cur.fetchall()
        return {row["key"]: row["value"] for row in rows}

    def load_app_settings(self):
        from app.config.settings import (
            AppSettings,
            DEFAULT_LANGUAGE,
            DEFAULT_MAX_DELAY_SECONDS,
            DEFAULT_MIN_DELAY_SECONDS,
            DEFAULT_RETRY_COUNT,
            DEFAULT_THEME,
            SETTINGS_KEY_LANGUAGE,
            SETTINGS_KEY_MAX_DELAY,
            SETTINGS_KEY_MIN_DELAY,
            SETTINGS_KEY_RETRY_COUNT,
            SETTINGS_KEY_THEME,
        )

        values = self.get_all()
        return AppSettings(
            min_delay_seconds=int(values.get(SETTINGS_KEY_MIN_DELAY, DEFAULT_MIN_DELAY_SECONDS)),
            max_delay_seconds=int(values.get(SETTINGS_KEY_MAX_DELAY, DEFAULT_MAX_DELAY_SECONDS)),
            retry_count=int(values.get(SETTINGS_KEY_RETRY_COUNT, DEFAULT_RETRY_COUNT)),
            language=values.get(SETTINGS_KEY_LANGUAGE, DEFAULT_LANGUAGE),
            theme=values.get(SETTINGS_KEY_THEME, DEFAULT_THEME),
        )

    def save_app_settings(self, settings) -> None:
        from app.config.settings import (
            SETTINGS_KEY_LANGUAGE,
            SETTINGS_KEY_MAX_DELAY,
            SETTINGS_KEY_MIN_DELAY,
            SETTINGS_KEY_RETRY_COUNT,
            SETTINGS_KEY_THEME,
        )

        settings.validate()
        self.set(SETTINGS_KEY_MIN_DELAY, str(settings.min_delay_seconds))
        self.set(SETTINGS_KEY_MAX_DELAY, str(settings.max_delay_seconds))
        self.set(SETTINGS_KEY_RETRY_COUNT, str(settings.retry_count))
        self.set(SETTINGS_KEY_LANGUAGE, settings.language)
        self.set(SETTINGS_KEY_THEME, settings.theme)
