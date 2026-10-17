"""Application shell after the redesign: collapsible sidebar (remembered),
the active-account block, toasts instead of modal boxes for quick
successes, and the journal as a right-hand side panel."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from app.database.database import Database
from app.security.secure_storage import SecureStorage
from app.ui.main_window import MainWindow
from app.ui.motion import ToastHost
from app.ui.sidebar import Sidebar
from app.ui.theme import SIDEBAR_COLLAPSED_WIDTH, SIDEBAR_WIDTH


def _make_window(tmp_path: Path, db: Database = None) -> MainWindow:
    return MainWindow(database=db or Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))


async def _wait_until(predicate, timeout=5.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached")
        QApplication.processEvents()  # Qt timers/animations need the Qt loop
        await asyncio.sleep(0.02)


def test_sidebar_collapses_to_an_icon_rail_and_back(qapp):
    sidebar = Sidebar()
    assert sidebar.width() == SIDEBAR_WIDTH
    sidebar.set_collapsed(True)
    assert sidebar.width() == SIDEBAR_COLLAPSED_WIDTH
    # Labels move to tooltips/accessible names so the rail stays usable.
    assert all(button.toolTip() for button in sidebar._buttons)
    assert all(button.accessibleName() for button in sidebar._buttons)
    sidebar.set_collapsed(False)
    assert sidebar.width() == SIDEBAR_WIDTH


async def test_collapsed_state_is_remembered(qapp, tmp_path):
    db = Database(tmp_path / "app.db")
    window = _make_window(tmp_path, db)
    window._sidebar._toggle.click()
    await _wait_until(lambda: window._sidebar.is_collapsed)
    assert window._service.settings_repository.load_app_settings().sidebar_collapsed is True

    reopened = _make_window(tmp_path, db)
    assert reopened._sidebar.is_collapsed is True


async def test_account_block_shows_the_active_account_and_opens_accounts(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._enter_demo_mode()
    await _wait_until(lambda: window._sidebar._account_block._name.text() == "Demo Account")
    assert window._sidebar._account_block._avatar.text() == "DA"
    assert window._sidebar._account_block._dot.property("status") == "success"

    window._sidebar._account_block.click()
    assert window._stack.currentIndex() == 1
    assert window._sidebar._buttons[1].isChecked()


async def test_saving_a_preset_shows_a_toast_not_a_modal_box(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "Hello"
    with patch("app.ui.main_window.QInputDialog") as mock_dialog, patch("app.ui.main_window.show_info") as modal:
        mock_dialog.getText.return_value = ("Weekly", True)
        window._on_save_preset_clicked()
    modal.assert_not_called()
    toasts = window._toasts.toasts
    assert len(toasts) == 1
    assert "Weekly" in toasts[0].text_label.text()


async def test_toasts_disappear_on_their_own(qapp):
    from PySide6.QtWidgets import QWidget

    anchor = QWidget()
    anchor.resize(800, 600)
    host = ToastHost(anchor)
    host.show_toast("Saved", duration=50)
    assert len(host.toasts) == 1
    await _wait_until(lambda: not host.toasts, timeout=3)


async def test_journal_is_on_the_right_of_the_pages(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.resize(1280, 800)
    window.show()
    window._journal.setVisible(True)
    QApplication.processEvents()
    assert window._journal.geometry().left() > window._stack.geometry().left()
