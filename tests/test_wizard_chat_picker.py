"""The Campaign Wizard's recipients step has the same "From my chats…"
button as the Campaign page, opening the same picker through the same
loading path -- and what's picked lands in the wizard, not on the page."""
from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6.QtCore import Qt

from app.database.database import Database
from app.i18n import tr
from app.security.secure_storage import SecureStorage
from app.ui.chat_picker_dialog import ChatPickerDialog
from app.ui.main_window import MainWindow


def _make_window(tmp_path: Path) -> MainWindow:
    return MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "secrets.dat"))


async def _wait_until(predicate, timeout=5.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.02)


async def test_wizard_recipients_step_has_the_picker_button(qapp, tmp_path):
    window = _make_window(tmp_path)
    wizard = window._build_campaign_wizard()
    button = wizard.recipient_widget._pick_chats_button
    assert not button.isHidden()
    assert button.text() == tr("recipient_widget.pick_chats_button")
    assert button.isEnabled() is False  # no account yet

    window._enter_demo_mode()
    await _wait_until(lambda: window._active_account_connected())
    window._update_pick_chats_enabled()
    assert button.isEnabled() is True


async def test_wizard_picker_fills_the_wizard_through_the_same_path(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._enter_demo_mode()
    await _wait_until(lambda: window._recipient_widget._pick_chats_button.isEnabled())
    window._recipient_widget.set_text("@page_only")

    wizard = window._build_campaign_wizard()
    wizard.show()
    wizard.recipient_widget.set_text("@demo_news")
    wizard.recipient_widget._pick_chats_button.click()

    picker = window._chat_picker
    assert isinstance(picker, ChatPickerDialog)
    assert picker.parent() is wizard  # over the wizard, not the window
    assert wizard.recipient_widget._pick_chats_button.isEnabled() is False
    await _wait_until(lambda: picker._loaded)

    model = picker._model
    titles = [model.dialog(row).title for row in range(model.rowCount())]
    # Already in the wizard's box: marked, not offered again.
    assert model.is_already_added(titles.index("Demo News"))
    for row, title in enumerate(titles):
        if title in ("Anna Smirnova", "Demo Family"):
            model.setData(model.index(row), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    picker._add_button.click()
    await _wait_until(lambda: window._chat_picker is None)

    assert wizard.recipient_widget.get_text() == "@demo_news\n@demo_friend\n-900000003"
    assert window._recipient_widget.get_text() == "@page_only"  # the page is untouched
    assert wizard.recipient_widget._pick_chats_button.isEnabled() is True
    wizard.reject()
