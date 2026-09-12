"""Diagnostics collection (ROADMAP: Diagnostics) -- read-only application/
environment/status information for troubleshooting, surfaced on the
Settings page. Never includes API ID/Hash, 2FA passwords, or session file
contents -- only whether a session file exists on disk (a count), the
same "not a secret" convention this app already applies to an account's
own phone/username in the status bar's connection indicator.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import List, Tuple

import telethon

from app.config.paths import get_session_path
from app.database.database import Database
from app.database.repositories import AccountRepository
from app.i18n import tr
from app.version import APP_VERSION


@dataclass
class DiagnosticsReport:
    fields: List[Tuple[str, str]]  # (label, value), in display order


def _database_status(database: Database) -> str:
    try:
        with database.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 -- any failure here IS the diagnostic being reported
        return tr("diagnostics.status.error", error=exc)
    return tr("diagnostics.status.ok")


def _session_storage_status(database: Database) -> str:
    try:
        accounts = AccountRepository(database).list_all()
    except Exception as exc:  # noqa: BLE001 -- same degrade-gracefully rule as _database_status
        return tr("diagnostics.status.error", error=exc)
    if not accounts:
        return tr("diagnostics.session_storage.no_accounts")
    present = sum(1 for account in accounts if get_session_path(account.session_name).exists())
    return tr("diagnostics.session_storage.summary", present=present, total=len(accounts))


def collect_diagnostics(database: Database, telegram_status: str, network_status: str) -> DiagnosticsReport:
    fields = [
        (tr("diagnostics.field.app_version"), APP_VERSION),
        (tr("diagnostics.field.python_version"), platform.python_version()),
        (tr("diagnostics.field.telethon_version"), telethon.__version__),
        (tr("diagnostics.field.database_status"), _database_status(database)),
        (tr("diagnostics.field.telegram_status"), telegram_status),
        (tr("diagnostics.field.session_storage"), _session_storage_status(database)),
        (tr("diagnostics.field.network_status"), network_status),
    ]
    return DiagnosticsReport(fields=fields)


def format_diagnostics_text(report: DiagnosticsReport) -> str:
    return "\n".join(f"{label}: {value}" for label, value in report.fields)
