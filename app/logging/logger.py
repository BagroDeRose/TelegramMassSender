"""Application logging setup: rotating file handler + secret scrubbing.

Only meaningful lifecycle events are logged (app start/stop, account
connect/disconnect, campaign start/stop/pause/resume, per-recipient send
result, FloodWait, critical exceptions) -- not every asyncio internal
step, to keep overhead low.

Secrets (API Hash, 2FA password, session contents) must never reach a log
call in the first place; SecretScrubbingFilter is a defensive second line
that redacts common secret-bearing patterns from any formatted message.
"""
from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler

from app.config.paths import get_logs_dir

LOGGER_NAME = "telegram_mass_sender"
MAX_LOG_BYTES = 8 * 1024 * 1024  # 8 MB
BACKUP_COUNT = 5

_SECRET_PATTERNS = [
    re.compile(r"(api[_-]?hash['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]{8,}", re.IGNORECASE),
    re.compile(r"(api[_-]?id['\"]?\s*[:=]\s*['\"]?)\d{5,}", re.IGNORECASE),
    re.compile(r"(password['\"]?\s*[:=]\s*['\"]?)\S+", re.IGNORECASE),
    re.compile(r"(2fa[_-]?password['\"]?\s*[:=]\s*['\"]?)\S+", re.IGNORECASE),
    re.compile(r"(session['\"]?\s*[:=]\s*['\"]?)\S{20,}", re.IGNORECASE),
]


class SecretScrubbingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        scrubbed = message
        for pattern in _SECRET_PATTERNS:
            scrubbed = pattern.sub(r"\1***REDACTED***", scrubbed)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


_configured = False


def configure_logging(debug: bool = False) -> logging.Logger:
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    log_path = get_logs_dir() / "application.log"
    file_handler = RotatingFileHandler(
        log_path, maxBytes=MAX_LOG_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    file_handler.addFilter(SecretScrubbingFilter())
    logger.addHandler(file_handler)

    if not getattr(sys, "frozen", False):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        console_handler.addFilter(SecretScrubbingFilter())
        logger.addHandler(console_handler)

    logger.propagate = False
    _configured = True
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
