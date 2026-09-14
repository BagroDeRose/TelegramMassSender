"""Diagnostic bundle export (ROADMAP: Diagnostic Bundle) -- a single ZIP
a user can attach to a bug report. Built entirely from already-sanitized
sources:

  - the Diagnostics report (app.diagnostics) -- app/Python/Telethon
    versions, DB/Telegram/session/network status
  - the same rotating log files app.logging.logger already scrubs of
    secrets at write time (SecretScrubbingFilter runs on every record as
    it is written, so these files never had a secret in them to begin
    with -- nothing extra to redact here)
  - a plain dump of AppSettings -- API ID/Hash live in
    app.security.secure_storage (a separate DPAPI-encrypted file), never
    in AppSettings, so there is nothing sensitive to strip out

Never included: Telegram session files (app.config.paths.get_sessions_dir()
is never touched here), credentials, or message content (neither is ever
persisted in AppSettings or the logs to begin with).
"""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict
from pathlib import Path

from app.config.paths import get_logs_dir
from app.config.settings import AppSettings
from app.database.database import Database
from app.diagnostics import collect_diagnostics, format_diagnostics_text

# Matches the standard Windows per-user profile path shape
# (C:\Users\<name>\...) so a user-customized reports_directory setting
# doesn't leak their Windows account name into a bundle they might share
# with a third party for troubleshooting. The default (empty string,
# meaning "app.config.paths.get_reports_dir()'s own default") never
# matches this and passes through unchanged.
_WINDOWS_USER_PATH_RE = re.compile(r"^([A-Za-z]:\\Users\\)([^\\]+)(\\.*)?$")


def _sanitize_reports_directory(path_str: str) -> str:
    match = _WINDOWS_USER_PATH_RE.match(path_str)
    if not match:
        return path_str
    prefix, _username, rest = match.groups()
    return f"{prefix}<redacted>{rest or ''}"


def export_diagnostic_bundle(
    path: Path,
    database: Database,
    settings: AppSettings,
    telegram_status: str,
    network_status: str,
) -> None:
    report = collect_diagnostics(database, telegram_status, network_status)
    diagnostics_text = format_diagnostics_text(report)
    settings_dict = asdict(settings)
    # A custom reports folder (the default is "", meaning "use the app's
    # own folder under %APPDATA%") is very often somewhere under the
    # user's own Windows profile -- e.g. Documents -- which embeds their
    # Windows account name in the path. Sanitized here, specifically for
    # this export, rather than in AppSettings itself: the real path is
    # still needed everywhere else the app actually uses this setting.
    settings_dict["reports_directory"] = _sanitize_reports_directory(settings_dict["reports_directory"])
    settings_text = json.dumps(settings_dict, indent=2, ensure_ascii=False, sort_keys=True)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("diagnostics.txt", diagnostics_text)
        bundle.writestr("settings.json", settings_text)
        logs_dir = get_logs_dir()
        if logs_dir.exists():
            for log_file in sorted(logs_dir.glob("application.log*")):
                if log_file.is_file():
                    bundle.write(log_file, arcname=f"logs/{log_file.name}")
