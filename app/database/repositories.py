"""Repository layer for accounts, settings, and saved-report persistence."""
from __future__ import annotations

from typing import List, Optional

from app.database.database import Database
from app.database.models import Account, Preset, SavedReport


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
        from app.config import settings as settings_module
        from app.config.settings import AppSettings

        values = self.get_all()

        def _str(key: str, default: str) -> str:
            return values.get(key, default)

        def _int(key: str, default: int) -> int:
            try:
                return int(values.get(key, default))
            except (TypeError, ValueError):
                return default

        def _bool(key: str, default: bool) -> bool:
            raw = values.get(key)
            if raw is None:
                return default
            return raw == "1"

        return AppSettings(
            min_delay_seconds=_int(settings_module.SETTINGS_KEY_MIN_DELAY, settings_module.DEFAULT_MIN_DELAY_SECONDS),
            max_delay_seconds=_int(settings_module.SETTINGS_KEY_MAX_DELAY, settings_module.DEFAULT_MAX_DELAY_SECONDS),
            retry_count=_int(settings_module.SETTINGS_KEY_RETRY_COUNT, settings_module.DEFAULT_RETRY_COUNT),
            language=_str(settings_module.SETTINGS_KEY_LANGUAGE, settings_module.DEFAULT_LANGUAGE),
            theme=_str(settings_module.SETTINGS_KEY_THEME, settings_module.DEFAULT_THEME),
            confirm_before_start=_bool(
                settings_module.SETTINGS_KEY_CONFIRM_BEFORE_START, settings_module.DEFAULT_CONFIRM_BEFORE_START
            ),
            remember_window_size=_bool(
                settings_module.SETTINGS_KEY_REMEMBER_WINDOW_SIZE, settings_module.DEFAULT_REMEMBER_WINDOW_SIZE
            ),
            window_width=_int(settings_module.SETTINGS_KEY_WINDOW_WIDTH, settings_module.DEFAULT_WINDOW_WIDTH),
            window_height=_int(settings_module.SETTINGS_KEY_WINDOW_HEIGHT, settings_module.DEFAULT_WINDOW_HEIGHT),
            window_maximized=_bool(
                settings_module.SETTINGS_KEY_WINDOW_MAXIMIZED, settings_module.DEFAULT_WINDOW_MAXIMIZED
            ),
            remember_last_page=_bool(
                settings_module.SETTINGS_KEY_REMEMBER_LAST_PAGE, settings_module.DEFAULT_REMEMBER_LAST_PAGE
            ),
            last_page_index=_int(settings_module.SETTINGS_KEY_LAST_PAGE_INDEX, settings_module.DEFAULT_LAST_PAGE_INDEX),
            journal_visible=_bool(settings_module.SETTINGS_KEY_JOURNAL_VISIBLE, settings_module.DEFAULT_JOURNAL_VISIBLE),
            reports_directory=_str(
                settings_module.SETTINGS_KEY_REPORTS_DIRECTORY, settings_module.DEFAULT_REPORTS_DIRECTORY
            ),
            auto_save_reports=_bool(
                settings_module.SETTINGS_KEY_AUTO_SAVE_REPORTS, settings_module.DEFAULT_AUTO_SAVE_REPORTS
            ),
            debug_logging=_bool(settings_module.SETTINGS_KEY_DEBUG_LOGGING, settings_module.DEFAULT_DEBUG_LOGGING),
            active_account_id=_int(
                settings_module.SETTINGS_KEY_ACTIVE_ACCOUNT_ID, settings_module.DEFAULT_ACTIVE_ACCOUNT_ID
            ),
        )

    def save_app_settings(self, settings) -> None:
        from app.config import settings as settings_module

        settings.validate()
        self.set(settings_module.SETTINGS_KEY_MIN_DELAY, str(settings.min_delay_seconds))
        self.set(settings_module.SETTINGS_KEY_MAX_DELAY, str(settings.max_delay_seconds))
        self.set(settings_module.SETTINGS_KEY_RETRY_COUNT, str(settings.retry_count))
        self.set(settings_module.SETTINGS_KEY_LANGUAGE, settings.language)
        self.set(settings_module.SETTINGS_KEY_THEME, settings.theme)
        self.set(settings_module.SETTINGS_KEY_CONFIRM_BEFORE_START, "1" if settings.confirm_before_start else "0")
        self.set(settings_module.SETTINGS_KEY_REMEMBER_WINDOW_SIZE, "1" if settings.remember_window_size else "0")
        self.set(settings_module.SETTINGS_KEY_WINDOW_WIDTH, str(settings.window_width))
        self.set(settings_module.SETTINGS_KEY_WINDOW_HEIGHT, str(settings.window_height))
        self.set(settings_module.SETTINGS_KEY_WINDOW_MAXIMIZED, "1" if settings.window_maximized else "0")
        self.set(settings_module.SETTINGS_KEY_REMEMBER_LAST_PAGE, "1" if settings.remember_last_page else "0")
        self.set(settings_module.SETTINGS_KEY_LAST_PAGE_INDEX, str(settings.last_page_index))
        self.set(settings_module.SETTINGS_KEY_JOURNAL_VISIBLE, "1" if settings.journal_visible else "0")
        self.set(settings_module.SETTINGS_KEY_REPORTS_DIRECTORY, settings.reports_directory)
        self.set(settings_module.SETTINGS_KEY_AUTO_SAVE_REPORTS, "1" if settings.auto_save_reports else "0")
        self.set(settings_module.SETTINGS_KEY_DEBUG_LOGGING, "1" if settings.debug_logging else "0")
        self.set(settings_module.SETTINGS_KEY_ACTIVE_ACCOUNT_ID, str(settings.active_account_id))


class SavedReportRepository:
    """Pure DB access for the saved-report library metadata -- file
    read/write/cleanup is business logic that lives in
    app.campaign.report_library, not here (same split as AccountRepository
    vs. AccountManager's session-file handling)."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def create(
        self, name: str, total: int, successful: int, failed: int, skipped: int, file_path: str
    ) -> SavedReport:
        with self._db.cursor() as cur:
            cur.execute(
                """INSERT INTO saved_reports (name, total, successful, failed, skipped, file_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, total, successful, failed, skipped, file_path),
            )
            report_id = cur.lastrowid
        report = self.get_by_id(report_id)
        assert report is not None
        return report

    def get_by_id(self, report_id: int) -> Optional[SavedReport]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM saved_reports WHERE id = ?", (report_id,))
            row = cur.fetchone()
        return self._row_to_report(row) if row else None

    def list_all(self) -> List[SavedReport]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM saved_reports ORDER BY created_at DESC")
            rows = cur.fetchall()
        return [self._row_to_report(row) for row in rows]

    def rename(self, report_id: int, new_name: str) -> None:
        with self._db.cursor() as cur:
            cur.execute("UPDATE saved_reports SET name = ? WHERE id = ?", (new_name, report_id))

    def set_favorite(self, report_id: int, is_favorite: bool) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                "UPDATE saved_reports SET is_favorite = ? WHERE id = ?",
                (1 if is_favorite else 0, report_id),
            )

    def delete(self, report_id: int) -> None:
        with self._db.cursor() as cur:
            cur.execute("DELETE FROM saved_reports WHERE id = ?", (report_id,))

    @staticmethod
    def _row_to_report(row) -> SavedReport:
        return SavedReport(
            id=row["id"],
            name=row["name"],
            created_at=row["created_at"],
            total=row["total"],
            successful=row["successful"],
            failed=row["failed"],
            skipped=row["skipped"],
            file_path=row["file_path"],
            is_favorite=bool(row["is_favorite"]),
        )


class PresetRepository:
    """Pure DB access for named message presets -- JSON encode/decode of
    entities/attachment paths and missing-file handling is business logic
    that lives in app.campaign.presets, not here (same split as
    SavedReportRepository above vs. app.campaign.report_library)."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def create(
        self,
        name: str,
        message_text: str,
        message_entities_json: str,
        attachment_paths_json: str,
        min_delay_seconds: Optional[int],
        max_delay_seconds: Optional[int],
    ) -> Preset:
        with self._db.cursor() as cur:
            cur.execute(
                """INSERT INTO presets
                   (name, message_text, message_entities, attachment_paths, min_delay_seconds, max_delay_seconds)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, message_text, message_entities_json, attachment_paths_json, min_delay_seconds, max_delay_seconds),
            )
            preset_id = cur.lastrowid
        preset = self.get_by_id(preset_id)
        assert preset is not None
        return preset

    def get_by_id(self, preset_id: int) -> Optional[Preset]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM presets WHERE id = ?", (preset_id,))
            row = cur.fetchone()
        return self._row_to_preset(row) if row else None

    def list_all(self) -> List[Preset]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM presets ORDER BY created_at DESC")
            rows = cur.fetchall()
        return [self._row_to_preset(row) for row in rows]

    def rename(self, preset_id: int, new_name: str) -> None:
        with self._db.cursor() as cur:
            cur.execute("UPDATE presets SET name = ? WHERE id = ?", (new_name, preset_id))

    def delete(self, preset_id: int) -> None:
        with self._db.cursor() as cur:
            cur.execute("DELETE FROM presets WHERE id = ?", (preset_id,))

    @staticmethod
    def _row_to_preset(row) -> Preset:
        return Preset(
            id=row["id"],
            name=row["name"],
            created_at=row["created_at"],
            message_text=row["message_text"],
            message_entities=row["message_entities"],
            attachment_paths=row["attachment_paths"],
            min_delay_seconds=row["min_delay_seconds"],
            max_delay_seconds=row["max_delay_seconds"],
        )
