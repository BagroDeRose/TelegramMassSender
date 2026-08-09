"""Application-wide defaults, constants and settings validation.

Persisted values (accounts, delay range, retry count, theme, language) are
stored via app.database.repositories.SettingsRepository; this module only
defines the defaults/bounds and the validation rules shared by the UI and
the campaign engine, so both enforce the same limits.
"""
from __future__ import annotations

from dataclasses import dataclass

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

SETTINGS_KEY_MIN_DELAY = "min_delay_seconds"
SETTINGS_KEY_MAX_DELAY = "max_delay_seconds"
SETTINGS_KEY_RETRY_COUNT = "retry_count"
SETTINGS_KEY_LANGUAGE = "language"
SETTINGS_KEY_THEME = "theme"


class SettingsValidationError(ValueError):
    """Raised when a user-supplied setting value is out of bounds."""


def validate_delay_range(min_seconds: float, max_seconds: float) -> None:
    if min_seconds <= 0 or max_seconds <= 0:
        raise SettingsValidationError("Интервал должен быть больше нуля.")
    if min_seconds > max_seconds:
        raise SettingsValidationError(
            "Минимальная задержка не может быть больше максимальной."
        )
    if min_seconds < MIN_ALLOWED_DELAY_SECONDS:
        raise SettingsValidationError(
            f"Слишком маленький интервал. Минимально допустимое значение: "
            f"{MIN_ALLOWED_DELAY_SECONDS} сек."
        )
    if max_seconds > MAX_ALLOWED_DELAY_SECONDS:
        raise SettingsValidationError(
            f"Слишком большой интервал. Максимально допустимое значение: "
            f"{MAX_ALLOWED_DELAY_SECONDS} сек."
        )


def validate_retry_count(retry_count: int) -> None:
    if not (MIN_RETRY_COUNT <= retry_count <= MAX_RETRY_COUNT):
        raise SettingsValidationError(
            f"Количество повторов должно быть от {MIN_RETRY_COUNT} до "
            f"{MAX_RETRY_COUNT}."
        )


@dataclass
class AppSettings:
    min_delay_seconds: int = DEFAULT_MIN_DELAY_SECONDS
    max_delay_seconds: int = DEFAULT_MAX_DELAY_SECONDS
    retry_count: int = DEFAULT_RETRY_COUNT
    language: str = DEFAULT_LANGUAGE
    theme: str = DEFAULT_THEME

    def validate(self) -> None:
        validate_delay_range(self.min_delay_seconds, self.max_delay_seconds)
        validate_retry_count(self.retry_count)
