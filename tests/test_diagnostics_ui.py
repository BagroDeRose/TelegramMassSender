"""The Settings page's Diagnostics card: one row per check with a status
icon, plain wording and a hint when something needs doing; versions under
"Technical details"; "Open data folder" without showing the path; the
copied text and the bundle never carry secrets or the phone number."""
from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QLabel

from app.config.paths import get_app_data_dir, get_sessions_dir
from app.database.database import Database
from app.diagnostics import STATUS_INFO, STATUS_OK, STATUS_WARNING
from app.i18n import tr, trn
from app.security.secure_storage import SecureStorage
from app.ui.main_window import MainWindow
from app.version import APP_VERSION


def _make_window(tmp_path: Path) -> MainWindow:
    return MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))


async def _wait_until(predicate, timeout=5.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition not reached"
        await asyncio.sleep(0.02)


def _items(window):
    return {item.label: item for item in window._last_diagnostics_report.items}


async def test_plain_wording_without_repeats(qapp, tmp_path):
    window = _make_window(tmp_path)
    items = _items(window)
    assert items[tr("diagnostics.field.database_status")].value == tr("diagnostics.status.ok")
    assert tr("diagnostics.status.ok") in ("В порядке", "OK")
    telegram = items[tr("diagnostics.field.telegram_status")]
    assert (telegram.value, telegram.status) == (tr("diagnostics.telegram.no_account"), STATUS_WARNING)
    assert telegram.hint == tr("diagnostics.hint.add_account")
    network = items[tr("diagnostics.field.network_status")]
    assert network.status == STATUS_INFO
    sessions = items[tr("diagnostics.field.session_storage")]
    assert sessions.value == tr("diagnostics.session_storage.no_accounts")
    for item in items.values():
        # No "Telegram connection: Connected"-style repetition of the label in the value.
        assert item.label.lower() not in item.value.lower()


async def test_connected_demo_account_reads_ok_with_its_username(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._enter_demo_mode()
    await _wait_until(lambda: window._active_account_connected())
    window._refresh_diagnostics()
    items = _items(window)
    telegram = items[tr("diagnostics.field.telegram_status")]
    assert telegram.status == STATUS_OK and "@demo_account" in telegram.value and not telegram.hint
    assert items[tr("diagnostics.field.network_status")].status == STATUS_OK
    # Demo Mode never has a session file and isn't counted.
    assert items[tr("diagnostics.field.session_storage")].value == tr("diagnostics.session_storage.no_accounts")


async def test_missing_sign_in_is_a_warning_with_what_to_do(qapp, tmp_path):
    window = _make_window(tmp_path)
    repo = window._service.account_repository
    repo.create("+70000000050", "account_saved")
    repo.create("+70000000051", "account_lost")
    (get_sessions_dir() / "account_saved.session").write_bytes(b"synthetic")
    window._refresh_diagnostics()
    sessions = _items(window)[tr("diagnostics.field.session_storage")]
    assert sessions.value == trn("diagnostics.session_storage.summary", 2, present=1)
    assert sessions.status == STATUS_WARNING
    assert sessions.hint == tr("diagnostics.hint.sign_in_again")
    assert tr("diagnostics.hint.sign_in_again") in window.diagnostics_display_text()


async def test_every_row_has_a_status_icon(qapp, tmp_path):
    window = _make_window(tmp_path)
    icons = [label for label in window._diagnostics_rows.findChildren(QLabel) if label.objectName() == "diagnosticsIcon"]
    assert len(icons) == len(window._last_diagnostics_report.items)
    assert all(not icon.pixmap().isNull() for icon in icons)
    assert all(icon.accessibleName() for icon in icons)


async def test_versions_are_tucked_under_technical_details(qapp, tmp_path):
    import platform

    import telethon

    window = _make_window(tmp_path)
    window.show()
    QApplication.processEvents()
    shown = window.diagnostics_display_text()
    assert APP_VERSION in shown
    assert platform.python_version() not in shown and telethon.__version__ not in shown
    assert window._technical_details.isHidden()
    window._technical_toggle.click()
    assert not window._technical_details.isHidden()
    assert platform.python_version() in window._technical_details.text()
    assert telethon.__version__ in window._technical_details.text()


async def test_open_data_folder_opens_explorer_without_showing_the_path(qapp, tmp_path):
    window = _make_window(tmp_path)
    with patch("app.ui.main_window.QDesktopServices.openUrl") as open_url:
        window._open_data_folder_button.click()
    open_url.assert_called_once_with(QUrl.fromLocalFile(str(get_app_data_dir())))
    shown = window.diagnostics_display_text() + window._technical_details.text()
    assert str(get_app_data_dir()) not in shown
    assert "AppData" not in shown


async def test_copied_text_and_bundle_have_no_secrets_or_phone_number(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._service.account_repository.create("+70000000052", "account_no_username")
    window._refresh_diagnostics()
    window._on_copy_diagnostics_clicked()
    copied = QApplication.clipboard().text()
    out = tmp_path / "bundle.zip"
    with patch("app.ui.main_window.QFileDialog.getSaveFileName", return_value=(str(out), "")), patch(
        "app.ui.main_window.show_info"
    ):
        window._on_export_diagnostic_bundle_clicked()
    with zipfile.ZipFile(out) as bundle:
        bundled = bundle.read("diagnostics.txt").decode("utf-8")
    for text in (copied, bundled):
        assert tr("diagnostics.technical_title") in text
        for forbidden in ("+70000000052", "api_hash", "api hash", "password", ".session"):
            assert forbidden not in text.lower()


async def test_rows_follow_language_and_theme(qapp, tmp_path):
    from app.i18n import get_language, set_language
    from app.ui import theme

    window = _make_window(tmp_path)
    original_language, original_theme = get_language(), theme.get_active_theme()
    try:
        window._language_combo.setCurrentIndex(window._language_combo.findData("en"))
        QApplication.processEvents()
        assert "Saved sign-ins" in window.diagnostics_display_text() or "Telegram" in window.diagnostics_display_text()
        assert window._open_data_folder_button.text() == "Open data folder"
        before = window._diagnostics_rows
        window._theme_combo.setCurrentIndex(window._theme_combo.findData("light" if original_theme == "dark" else "dark"))
        QApplication.processEvents()
        assert window._diagnostics_rows is not before  # icons repainted in the new colours
    finally:
        set_language(original_language)
        theme.apply_theme(QApplication.instance(), original_theme)
