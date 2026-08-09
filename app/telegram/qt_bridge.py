"""Bridge between the Qt event loop and asyncio, via qasync.

Telethon is fully asyncio-based while PySide6 runs its own event loop.
qasync merges the two into a single loop on the main thread, so Telegram
coroutines and Qt signal/slot dispatch never race against each other and
no blocking call can freeze the UI (no time.sleep is used anywhere in
this codebase -- only asyncio.sleep).
"""
from __future__ import annotations

import asyncio

import qasync
from PySide6.QtWidgets import QApplication


def install_event_loop(qt_app: QApplication) -> tuple[qasync.QEventLoop, asyncio.Event]:
    loop = qasync.QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    close_event = asyncio.Event()
    qt_app.aboutToQuit.connect(close_event.set)

    return loop, close_event


def run_event_loop(loop: qasync.QEventLoop, close_event: asyncio.Event) -> None:
    with loop:
        loop.run_until_complete(close_event.wait())
