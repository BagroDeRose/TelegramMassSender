"""Filesystem path resolution for runtime data and bundled resources.

All runtime data (database, Telegram sessions, logs, secrets) lives under
the user's Windows AppData directory, never inside the application/repo
directory. Paths are resolved programmatically -- nothing here is
hardcoded to a specific machine or drive.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "TelegramMassSender"


def _app_data_root() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata)
    # Defensive fallback; APPDATA is always set on real Windows sessions.
    return Path.home() / "AppData" / "Roaming"


def get_app_data_dir() -> Path:
    path = _app_data_root() / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_database_dir() -> Path:
    path = get_app_data_dir() / "database"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_sessions_dir() -> Path:
    path = get_app_data_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_logs_dir() -> Path:
    path = get_app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_config_dir() -> Path:
    path = get_app_data_dir() / "config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_database_path() -> Path:
    return get_database_dir() / "app.db"


def get_secrets_path() -> Path:
    return get_config_dir() / "secrets.dat"


def get_session_path(session_name: str) -> Path:
    """Return the Telethon session path (without extension) for a given
    internal session identifier. Telethon appends '.session' itself."""
    return get_sessions_dir() / session_name


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_app_root() -> Path:
    """Root directory containing bundled resources (assets/, etc.).

    In a frozen PyInstaller build this is the directory containing the
    executable (or the _MEIPASS extraction dir for --onefile builds).
    In development it is the project root (parent of app/).
    """
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_resource_path(*relative_parts: str) -> Path:
    """Resolve a path to a bundled read-only resource (icons, styles)."""
    return get_app_root().joinpath(*relative_parts)
