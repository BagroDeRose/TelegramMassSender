"""The counts under the Recipients box use the session's dialog cache: a
@username known from it counts as a person, a bot or a group/channel; an
unknown one gets its own "@username: N" pill. They follow the cache and
the active account. (A channel added by @username used to be missing from
"groups & channels" altogether -- its type is unknown until resolved.)"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from app.database.database import Database
from app.i18n import tr, trn
from app.security.secure_storage import SecureStorage
from app.ui.main_window import MainWindow


async def _wait_until(predicate, timeout=5.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition not reached"
        await asyncio.sleep(0.02)


async def _demo_window(tmp_path: Path) -> MainWindow:
    window = MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))
    window._enter_demo_mode()
    await _wait_until(lambda: window._recipient_widget._pick_chats_button.isEnabled())
    return window


async def _fill_cache(window: MainWindow) -> None:
    window._recipient_widget._pick_chats_button.click()
    await _wait_until(lambda: window._chat_picker is not None and window._chat_picker._loaded)
    window._chat_picker.reject()
    await _wait_until(lambda: window._chat_picker is None)


def _pills(widget):
    widget.flush()
    QApplication.processEvents()
    return {key: pill.text() for key, pill in widget._pills.items() if not pill.isHidden()}


async def test_channel_by_username_counts_once_the_cache_knows_it(qapp, tmp_path):
    window = await _demo_window(tmp_path)
    window._recipient_widget.set_text("@demo_news\n-1001900000002")
    before = _pills(window._recipient_widget)
    assert before["chats"] == tr("recipient_widget.pill_chats", count=1)
    assert before["unknown"] == tr("recipient_widget.pill_unknown", count=1)
    assert window._recipient_widget._pills["unknown"].toolTip() == tr("recipient_widget.pill_unknown_tooltip")

    await _fill_cache(window)  # the cache filling up re-counts by itself
    after = _pills(window._recipient_widget)
    assert after["chats"] == tr("recipient_widget.pill_chats", count=2)
    assert "unknown" not in after
    assert window._campaign_controls._chats_value.text() == "2"


async def test_person_and_bot_by_username(qapp, tmp_path):
    window = await _demo_window(tmp_path)
    await _fill_cache(window)
    window._recipient_widget.set_text("@demo_friend\n@demo_weather_bot")
    pills = _pills(window._recipient_widget)
    assert pills["valid"] == trn("recipient_widget.recipient_count", 2)
    assert pills["bots"] == tr("recipient_widget.pill_bots", count=1)
    assert "chats" not in pills and "unknown" not in pills


async def test_unknown_username_keeps_its_own_pill(qapp, tmp_path):
    window = await _demo_window(tmp_path)
    await _fill_cache(window)
    window._recipient_widget.set_text("@nobody_in_my_dialogs")
    pills = _pills(window._recipient_widget)
    assert pills["unknown"] == tr("recipient_widget.pill_unknown", count=1)
    assert "chats" not in pills


async def test_mixed_list(qapp, tmp_path):
    window = await _demo_window(tmp_path)
    await _fill_cache(window)
    window._recipient_widget.set_text(
        "@demo_news\n-900000003\n@demo_friend\n700000002\n@demo_weather_bot\n@someone_new\n+4917612345678\nnot valid!"
    )
    pills = _pills(window._recipient_widget)
    assert pills["valid"] == trn("recipient_widget.recipient_count", 7)
    assert pills["chats"] == tr("recipient_widget.pill_chats", count=2)
    assert pills["bots"] == tr("recipient_widget.pill_bots", count=1)
    assert pills["unknown"] == tr("recipient_widget.pill_unknown", count=1)
    assert pills["invalid"] == tr("recipient_widget.summary_invalid_count", count=1)
    breakdown = window._recipient_widget.recipient_breakdown()
    assert (breakdown.people, breakdown.bots, breakdown.chats, breakdown.unknown) == (3, 1, 2, 1)


async def test_account_change_forgets_what_the_cache_knew(qapp, tmp_path):
    window = await _demo_window(tmp_path)
    await _fill_cache(window)
    window._recipient_widget.set_text("@demo_news")
    assert "chats" in _pills(window._recipient_widget)
    with patch.object(window._service, "exit_demo_mode"), patch.object(window, "_spawn"), patch.object(
        window, "_refresh_accounts", new=MagicMock()
    ):
        window._transition_demo_mode(enter=False)
    pills = _pills(window._recipient_widget)
    assert "chats" not in pills
    assert pills["unknown"] == tr("recipient_widget.pill_unknown", count=1)


async def test_wizard_counts_with_the_same_cache(qapp, tmp_path):
    window = await _demo_window(tmp_path)
    await _fill_cache(window)
    wizard = window._build_campaign_wizard()
    wizard.recipient_widget.set_text("@demo_news\n@demo_weather_bot")
    pills = _pills(wizard.recipient_widget)
    assert pills["chats"] == tr("recipient_widget.pill_chats", count=1)
    assert pills["bots"] == tr("recipient_widget.pill_bots", count=1)
    wizard.reject()
