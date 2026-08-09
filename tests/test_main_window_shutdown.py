"""Regression tests for the critical "X button does not close the app" bug.

Root cause: MainWindow.closeEvent() always ignores the QCloseEvent (it
must run async cleanup -- stop campaign, disconnect Telegram clients,
close the DB -- before the process may actually exit), and
_perform_shutdown() used to rely solely on QApplication.quit() ->
aboutToQuit -> close_event.set() to unblock main.py's
loop.run_until_complete(close_event.wait()).

That chain was proven unreliable, specifically in the case where the
window's close event is never accepted through Qt's normal path (which
is exactly what always happens here, by design): reproduced against a
real, running process driven by an actual WM_CLOSE message (the same
message Windows sends when the user clicks the title-bar X). The process
hung forever even though _perform_shutdown() had fully completed and
called QApplication.quit().

The fix: MainWindow now holds a direct reference to the same
asyncio.Event that main.py's run_until_complete() awaits, and
_perform_shutdown() sets it directly -- independent of whether
quit()/aboutToQuit ever fires. These tests guard that mechanism so it
cannot silently regress back to depending on quit() alone.
"""
from __future__ import annotations

import asyncio

from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.database.database import Database
from app.ui.main_window import MainWindow


def _isolated_window(tmp_path: Path, close_event=None) -> MainWindow:
    # Never touch the real %APPDATA% database from the permanent test suite.
    database = Database(tmp_path / "app.db")
    return MainWindow(close_event=close_event, database=database)


async def test_shutdown_sets_close_event_even_if_app_quit_is_a_noop(qapp, tmp_path):
    close_event = asyncio.Event()
    window = _isolated_window(tmp_path, close_event=close_event)
    window._current_campaign = None

    # Neuter QApplication.quit() completely. This proves close_event is
    # not set merely as a downstream side effect of quit()/aboutToQuit --
    # which is precisely the assumption that caused the original hang.
    real_quit = QApplication.instance().quit
    QApplication.instance().quit = lambda: None
    try:
        await window._perform_shutdown()
        assert close_event.is_set(), (
            "MainWindow._perform_shutdown() must set close_event directly; "
            "it must never depend solely on QApplication.quit()/aboutToQuit "
            "to unblock the main event loop"
        )
    finally:
        QApplication.instance().quit = real_quit
        window._database.close()


async def test_shutdown_without_close_event_does_not_crash(qapp, tmp_path):
    # Backward-compatible default: close_event=None must not raise.
    window = _isolated_window(tmp_path, close_event=None)
    window._current_campaign = None
    await window._perform_shutdown()
    window._database.close()


async def test_close_event_is_always_ignored_by_qt(qapp, tmp_path):
    """closeEvent() must never let Qt's normal close/accept path run --
    async cleanup always has to happen first. This is a structural
    precondition of the fix above: since the window is never accepted-
    closed through Qt, anything that depends on quit()/aboutToQuit firing
    as a result of the window closing cannot be relied upon."""
    from unittest.mock import MagicMock

    from PySide6.QtGui import QCloseEvent

    close_event = asyncio.Event()
    window = _isolated_window(tmp_path, close_event=close_event)
    window._current_campaign = None

    real_quit = QApplication.instance().quit
    QApplication.instance().quit = lambda: None
    try:
        event = QCloseEvent()
        event.ignore = MagicMock()
        window.closeEvent(event)
        event.ignore.assert_called_once()

        # closeEvent() schedules _perform_shutdown() via ensure_future;
        # let it actually run to completion so no task is left dangling.
        await asyncio.wait_for(close_event.wait(), timeout=5)
    finally:
        QApplication.instance().quit = real_quit
        window._database.close()
