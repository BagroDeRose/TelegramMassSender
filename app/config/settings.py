"""Application-wide defaults, constants and settings validation.

Persisted values (accounts, delay range, retry count, theme, language) are
stored via app.database.repositories.SettingsRepository; this module only
defines the defaults/bounds and the validation rules shared by the UI and
the campaign engine, so both enforce the same limits.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.i18n import tr

# Sending interval (seconds). The floor exists to stop a user from
# accidentally configuring an unreasonably fast loop; it is a sanity
# guard, not a Telegram rate-limit workaround.
DEFAULT_MIN_DELAY_SECONDS = 30
DEFAULT_MAX_DELAY_SECONDS = 60
MIN_ALLOWED_DELAY_SECONDS = 5
MAX_ALLOWED_DELAY_SECONDS = 3600

# Retry policy for transient network errors only (never for FloodWait or
# permanent per-recipient errors).
DEFAULT_RETRY_COUNT = 3
MAX_RETRY_COUNT = 5
MIN_RETRY_COUNT = 0

DEFAULT_LANGUAGE = "ru"
DEFAULT_THEME = "dark"

# Application/window-state defaults. These are written back automatically
# by the UI layer (resize/move/page-switch/journal-toggle), never typed by
# hand, so they're defensively clamped on restore rather than validated
# with a raising check here -- a stray persisted value must never be able
# to crash startup.
DEFAULT_CONFIRM_BEFORE_START = False
DEFAULT_REMEMBER_WINDOW_SIZE = True
DEFAULT_WINDOW_WIDTH = 1180
DEFAULT_WINDOW_HEIGHT = 860
DEFAULT_WINDOW_MAXIMIZED = False
DEFAULT_REMEMBER_LAST_PAGE = True
DEFAULT_LAST_PAGE_INDEX = 0
DEFAULT_JOURNAL_VISIBLE = False
DEFAULT_REPORTS_DIRECTORY = ""  # empty -> app.config.paths.get_reports_dir()
DEFAULT_AUTO_SAVE_REPORTS = False
DEFAULT_DEBUG_LOGGING = False
# 0 is the "no account was active" sentinel -- real account ids are SQLite
# autoincrement, starting at 1, so 0 never collides with a real row.
DEFAULT_ACTIVE_ACCOUNT_ID = 0

SETTINGS_KEY_MIN_DELAY = "min_delay_seconds"
SETTINGS_KEY_MAX_DELAY = "max_delay_seconds"
SETTINGS_KEY_RETRY_COUNT = "retry_count"
SETTINGS_KEY_LANGUAGE = "language"
SETTINGS_KEY_THEME = "theme"
SETTINGS_KEY_CONFIRM_BEFORE_START = "confirm_before_start"
SETTINGS_KEY_REMEMBER_WINDOW_SIZE = "remember_window_size"
SETTINGS_KEY_WINDOW_WIDTH = "window_width"
SETTINGS_KEY_WINDOW_HEIGHT = "window_height"
SETTINGS_KEY_WINDOW_MAXIMIZED = "window_maximized"
SETTINGS_KEY_REMEMBER_LAST_PAGE = "remember_last_page"
SETTINGS_KEY_LAST_PAGE_INDEX = "last_page_index"
SETTINGS_KEY_JOURNAL_VISIBLE = "journal_visible"
SETTINGS_KEY_REPORTS_DIRECTORY = "reports_directory"
SETTINGS_KEY_AUTO_SAVE_REPORTS = "auto_save_reports"
SETTINGS_KEY_DEBUG_LOGGING = "debug_logging"
SETTINGS_KEY_ACTIVE_ACCOUNT_ID = "active_account_id"


class SettingsValidationError(ValueError):
    """Raised when a user-supplied setting value is out of bounds."""


def validate_delay_range(min_seconds: float, max_seconds: float) -> None:
    if min_seconds <= 0 or max_seconds <= 0:
        raise SettingsValidationError(tr("settings.validation.interval_must_be_positive"))
    if min_seconds > max_seconds:
        raise SettingsValidationError(tr("settings.validation.min_greater_than_max"))
    if min_seconds < MIN_ALLOWED_DELAY_SECONDS:
        raise SettingsValidationError(
            tr("settings.validation.interval_too_small", min=MIN_ALLOWED_DELAY_SECONDS)
        )
    if max_seconds > MAX_ALLOWED_DELAY_SECONDS:
        raise SettingsValidationError(
            tr("settings.validation.interval_too_large", max=MAX_ALLOWED_DELAY_SECONDS)
        )


def validate_retry_count(retry_count: int) -> None:
    if not (MIN_RETRY_COUNT <= retry_count <= MAX_RETRY_COUNT):
        raise SettingsValidationError(
            tr("settings.validation.retry_count_out_of_range", min=MIN_RETRY_COUNT, max=MAX_RETRY_COUNT)
        )


@dataclass
class AppSettings:
    min_delay_seconds: int = DEFAULT_MIN_DELAY_SECONDS
    max_delay_seconds: int = DEFAULT_MAX_DELAY_SECONDS
    retry_count: int = DEFAULT_RETRY_COUNT
    language: str = DEFAULT_LANGUAGE
    theme: str = DEFAULT_THEME
    confirm_before_start: bool = DEFAULT_CONFIRM_BEFORE_START
    remember_window_size: bool = DEFAULT_REMEMBER_WINDOW_SIZE
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT
    window_maximized: bool = DEFAULT_WINDOW_MAXIMIZED
    remember_last_page: bool = DEFAULT_REMEMBER_LAST_PAGE
    last_page_index: int = DEFAULT_LAST_PAGE_INDEX
    journal_visible: bool = DEFAULT_JOURNAL_VISIBLE
    reports_directory: str = DEFAULT_REPORTS_DIRECTORY
    auto_save_reports: bool = DEFAULT_AUTO_SAVE_REPORTS
    debug_logging: bool = DEFAULT_DEBUG_LOGGING
    # Persisted so the previously-active account is restored on the next
    # launch (app.telegram.account_manager.AccountManager itself is
    # recreated fresh every run and has no memory of its own). 0 means
    # "none" -- see DEFAULT_ACTIVE_ACCOUNT_ID.
    active_account_id: int = DEFAULT_ACTIVE_ACCOUNT_ID

    def validate(self) -> None:
        validate_delay_range(self.min_delay_seconds, self.max_delay_seconds)
        validate_retry_count(self.retry_count)
