"""Tests for MainWindow's system tray integration (v1.8 Windows
Integration): tray icon setup, minimize-to-tray, restore, exit-from-tray,
and campaign-completion/critical-error notifications.

QSystemTrayIcon.isSystemTrayAvailable() is False under the offscreen
platform this suite runs on (confirmed directly), so a real tray icon
never actually appears anywhere during these tests -- the availability
check itself is monkeypatched where a test needs to exercise the
"tray is available" branch, matching how the app behaves on a real
Windows desktop with a taskbar.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app.database.database import Database
from app.ui.main_window import MainWindow


async def _make_window(tmp_path: Path) -> MainWindow:
    window = MainWindow(database=Database(tmp_path / "app.db"))
    # Drains MainWindow.__init__'s fire-and-forget _refresh_accounts()
    # task before it can race a test's own calls -- same pattern as
    # tests/test_account_switching.py's _make_window.
    await asyncio.sleep(0)
    return window


async def test_tray_icon_is_constructed(qapp, tmp_path):
    window = await _make_window(tmp_path)
    assert window._tray_icon is not None
    assert isinstance(window._tray_icon, QSystemTrayIcon)


async def test_tray_icon_not_actually_shown_when_platform_has_no_tray(qapp, tmp_path):
    # Confirms this suite's own environment (and thus every other test in
    # it) never leaks a real, visible tray icon.
    assert QSystemTrayIcon.isSystemTrayAvailable() is False
    window = await _make_window(tmp_path)
    assert window._tray_icon.isVisible() is False


async def test_tray_context_menu_has_show_and_exit_actions(qapp, tmp_path):
    window = await _make_window(tmp_path)
    actions = window._tray_menu.actions()
    texts = [a.text() for a in actions if not a.isSeparator()]
    assert len(texts) == 2


async def test_tray_show_action_restores_the_window(qapp, tmp_path):
    window = await _make_window(tmp_path)
    window.hide()
    assert window.isHidden() is True

    show_action = [a for a in window._tray_menu.actions() if not a.isSeparator()][0]
    show_action.trigger()

    assert window.isHidden() is False


async def test_tray_exit_action_triggers_the_normal_close_path(qapp, tmp_path):
    # "Exit" from the tray must go through the same closeEvent (and thus
    # the same mid-campaign confirmation, and the same async shutdown
    # sequence) as the window's own X button -- not a separate, unguarded
    # shutdown path. Patching window.close() itself doesn't work here:
    # the tray action's triggered signal was connected to the real,
    # already-bound close method at setup time, so replacing the
    # attribute afterward doesn't change what that connection calls --
    # this instead lets the real close path run (same pattern as
    # tests/test_main_window_shutdown.py) and checks its actual effect.
    close_event = asyncio.Event()
    window = MainWindow(close_event=close_event, database=Database(tmp_path / "app.db"))
    await asyncio.sleep(0)
    window._current_campaign = None

    real_quit = QApplication.instance().quit
    QApplication.instance().quit = lambda: None
    try:
        exit_action = [a for a in window._tray_menu.actions() if not a.isSeparator()][1]
        exit_action.trigger()
        assert window._shutdown_in_progress is True
        await asyncio.wait_for(close_event.wait(), timeout=5)
    finally:
        QApplication.instance().quit = real_quit
        window._database.close()


async def test_activating_tray_icon_by_click_restores_the_window(qapp, tmp_path):
    window = await _make_window(tmp_path)
    window.hide()

    window._on_tray_icon_activated(QSystemTrayIcon.ActivationReason.Trigger)

    assert window.isHidden() is False


async def test_activating_tray_icon_by_double_click_restores_the_window(qapp, tmp_path):
    window = await _make_window(tmp_path)
    window.hide()

    window._on_tray_icon_activated(QSystemTrayIcon.ActivationReason.DoubleClick)

    assert window.isHidden() is False


async def test_activating_tray_icon_by_context_menu_reason_does_not_restore(qapp, tmp_path):
    # The context-menu-open reason must not also trigger a restore --
    # only a left-click/double-click should.
    window = await _make_window(tmp_path)
    window.show()
    window.hide()

    window._on_tray_icon_activated(QSystemTrayIcon.ActivationReason.Context)

    assert window.isHidden() is True


async def test_minimizing_hides_to_tray_when_tray_is_available(qapp, tmp_path):
    window = await _make_window(tmp_path)
    window.show()
    with patch("app.ui.main_window.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
        window.showMinimized()
        # The actual hide() is deferred via QTimer.singleShot(0, ...) --
        # see changeEvent's docstring -- so it needs an extra event-loop
        # turn (a bare processEvents() isn't guaranteed to run a 0ms
        # timer queued during the event it's currently processing).
        await asyncio.sleep(0)
        qapp.processEvents()
        assert window.isHidden() is True


async def test_minimizing_does_not_hide_when_no_tray_is_available(qapp, tmp_path):
    # Without a real tray to restore from, hiding the window would make
    # it permanently unreachable -- must fall back to a normal minimize.
    window = await _make_window(tmp_path)
    window.show()
    assert QSystemTrayIcon.isSystemTrayAvailable() is False
    window.showMinimized()
    qapp.processEvents()
    assert window.isHidden() is False


async def test_restore_from_tray_remembers_maximized_state(qapp, tmp_path):
    window = await _make_window(tmp_path)
    window.showMaximized()
    qapp.processEvents()
    with patch("app.ui.main_window.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
        window.showMinimized()
        qapp.processEvents()
        assert window._restore_maximized_from_tray is True

        window._restore_from_tray()
        qapp.processEvents()
        assert window.isMaximized() is True


async def test_notify_is_a_safe_no_op_when_tray_is_not_visible(qapp, tmp_path):
    window = await _make_window(tmp_path)
    # Must not raise even though no real tray icon is showing.
    window._notify("Title", "Body", QSystemTrayIcon.MessageIcon.Information)


async def test_notify_calls_show_message_when_tray_is_visible(qapp, tmp_path):
    window = await _make_window(tmp_path)
    with patch.object(window._tray_icon, "isVisible", return_value=True), patch.object(
        window._tray_icon, "showMessage"
    ) as mock_show_message:
        window._notify("Title", "Body", QSystemTrayIcon.MessageIcon.Critical)
    mock_show_message.assert_called_once()
    args = mock_show_message.call_args[0]
    assert args[0] == "Title"
    assert args[1] == "Body"
    assert args[2] == QSystemTrayIcon.MessageIcon.Critical


async def test_campaign_completed_triggers_a_notification(qapp, tmp_path):
    window = await _make_window(tmp_path)
    with patch.object(window, "_notify") as mock_notify:
        window._on_campaign_finished("completed")
    assert mock_notify.called
    title = mock_notify.call_args[0][0]
    assert "Campaign completed" in title or "завершена" in title.lower() or "Рассылка" in title


async def test_campaign_error_triggers_a_critical_notification(qapp, tmp_path):
    window = await _make_window(tmp_path)
    with patch.object(window, "_notify") as mock_notify, patch("app.ui.main_window.show_error"):
        window._on_campaign_finished("error")
    assert mock_notify.called
    icon_arg = mock_notify.call_args[0][2]
    assert icon_arg == QSystemTrayIcon.MessageIcon.Critical


async def test_campaign_stopped_does_not_trigger_a_notification(qapp, tmp_path):
    # A user-initiated stop is not a "completion" or a "critical error" --
    # only COMPLETED and ERROR should notify.
    window = await _make_window(tmp_path)
    with patch.object(window, "_notify") as mock_notify:
        window._on_campaign_finished("stopped")
    assert not mock_notify.called
