"""Diagnostics collection -- read-only application/
environment/status information for troubleshooting, surfaced on the
Settings page. Never includes API ID/Hash, 2FA passwords, phone numbers or
session file contents -- only whether a session file exists on disk (a
count) and the active account's public @username.

Each line is a DiagnosticItem: a status (ok / warning / error / info), a
plain-language value and, when something needs doing, a short hint. The
Python/Telethon versions are kept apart as technical details. The same
report is copied as text and written into the diagnostic bundle.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass, field
from typing import List, Tuple, Union

import telethon

from app.config.paths import get_session_file_path
from app.database.database import Database
from app.database.repositories import AccountRepository
from app.i18n import tr, trn
from app.telegram.demo_client import DEMO_ACCOUNT_PHONE
from app.version import APP_VERSION

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"
STATUS_INFO = "info"


@dataclass(frozen=True)
class DiagnosticItem:
    label: str
    value: str
    status: str = STATUS_INFO
    hint: str = ""


@dataclass(frozen=True)
class ConnectionState:
    """What the window knows about Telegram / the network, already worded."""

    value: str
    status: str = STATUS_INFO
    hint: str = ""


@dataclass
class DiagnosticsReport:
    items: List[DiagnosticItem]
    technical: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def fields(self) -> List[Tuple[str, str]]:
        """(label, value) of every line, technical details last."""
        return [(item.label, item.value) for item in self.items] + list(self.technical)


def _database_item(database: Database) -> DiagnosticItem:
    label = tr("diagnostics.field.database_status")
    try:
        with database.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 -- any failure here IS the diagnostic being reported
        return DiagnosticItem(label, tr("diagnostics.status.error", error=exc), STATUS_ERROR, tr("diagnostics.hint.database"))
    return DiagnosticItem(label, tr("diagnostics.status.ok"), STATUS_OK)


def _session_storage_item(database: Database) -> DiagnosticItem:
    label = tr("diagnostics.field.session_storage")
    try:
        accounts = AccountRepository(database).list_all()
    except Exception as exc:  # noqa: BLE001 -- same degrade-gracefully rule as the database line
        return DiagnosticItem(label, tr("diagnostics.status.error", error=exc), STATUS_ERROR, tr("diagnostics.hint.database"))
    # The demo account never has a session file (Demo Mode opens none).
    accounts = [account for account in accounts if account.phone != DEMO_ACCOUNT_PHONE]
    if not accounts:
        return DiagnosticItem(label, tr("diagnostics.session_storage.no_accounts"), STATUS_INFO)
    # The file Telethon writes is "<name>.session"; get_session_path() is
    # the name without that extension, so checking it always found 0.
    present = sum(1 for account in accounts if get_session_file_path(account.session_name).exists())
    value = trn("diagnostics.session_storage.summary", len(accounts), present=present)
    if present == len(accounts):
        return DiagnosticItem(label, value, STATUS_OK)
    return DiagnosticItem(label, value, STATUS_WARNING, tr("diagnostics.hint.sign_in_again"))


def _connection_item(label: str, state: Union[ConnectionState, str]) -> DiagnosticItem:
    if isinstance(state, str):
        state = ConnectionState(state)
    return DiagnosticItem(label, state.value, state.status, state.hint)


def collect_diagnostics(
    database: Database, telegram: Union[ConnectionState, str], network: Union[ConnectionState, str]
) -> DiagnosticsReport:
    items = [
        DiagnosticItem(tr("diagnostics.field.app_version"), APP_VERSION, STATUS_INFO),
        _database_item(database),
        _connection_item(tr("diagnostics.field.telegram_status"), telegram),
        _session_storage_item(database),
        _connection_item(tr("diagnostics.field.network_status"), network),
    ]
    technical = [
        (tr("diagnostics.field.python_version"), platform.python_version()),
        (tr("diagnostics.field.telethon_version"), telethon.__version__),
    ]
    return DiagnosticsReport(items=items, technical=technical)


def format_diagnostics_text(report: DiagnosticsReport) -> str:
    """Plain text for copying and the bundle: one line per item (with its
    hint indented under it), then the technical details."""
    lines = []
    for item in report.items:
        lines.append(f"{item.label}: {item.value}")
        if item.hint:
            lines.append(f"  {item.hint}")
    if report.technical:
        lines.append(f"{tr('diagnostics.technical_title')}:")
        lines.extend(f"  {label}: {value}" for label, value in report.technical)
    return "\n".join(lines)
