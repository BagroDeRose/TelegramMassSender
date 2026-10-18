"""Shared pytest fixtures.

QT_QPA_PLATFORM=offscreen is set before any Qt import so the suite runs
headlessly -- no real display required, matching how this runs on a
build machine / CI.

No test may reach the network: `_block_network` (autouse) refuses every
outbound connection that isn't loopback -- at the socket level, at the
asyncio level (Windows' proactor loop connects through ConnectEx and never
calls socket.connect), and at Telethon's own TelegramBaseClient.connect --
and fails the test even if the code under test swallowed the error, since
production code here routinely turns a connection failure into a status
or a log line rather than letting it propagate.
"""
from __future__ import annotations

import asyncio
import os
import socket
from typing import List

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from telethon.client.telegrambaseclient import TelegramBaseClient

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"}


class NetworkAccessError(AssertionError):
    """A test tried to open a real network connection."""


def _is_loopback(address) -> bool:
    if isinstance(address, tuple) and address:
        host = address[0]
    else:
        host = address
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    return isinstance(host, str) and (host in _LOOPBACK_HOSTS or host.startswith("127."))


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _dispose_top_level_widgets():
    """Destroy every top-level widget a test left behind.

    Tests build MainWindows, dialogs and parentless widgets and never close
    them. They used to live for the rest of the session, and every later
    QApplication.setStyleSheet() (each MainWindow applies its theme on
    construction) re-polished all of them -- so each test got slower than
    the one before, and the full suite in one process took hours.

    Widgets are hidden and deleteLater()'d rather than close()'d:
    MainWindow.closeEvent starts the app's async shutdown sequence, which
    is not what a test teardown wants. The DeferredDelete events are then
    flushed so the deletion happens now, not at some later processEvents.
    """
    yield
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.hide()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    attempts: List[str] = []

    def deny(what: str, target) -> NetworkAccessError:
        message = f"test tried to open a network connection: {what} {target!r}"
        attempts.append(message)
        return NetworkAccessError(message)

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(self, address):
        if not _is_loopback(address):
            raise deny("socket.connect", address)
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        if not _is_loopback(address):
            raise deny("socket.connect_ex", address)
        return real_connect_ex(self, address)

    real_create_connection = asyncio.BaseEventLoop.create_connection

    async def guarded_create_connection(self, protocol_factory, host=None, port=None, *args, **kwargs):
        if host is not None and not _is_loopback(host):
            raise deny("loop.create_connection", (host, port))
        return await real_create_connection(self, protocol_factory, host, port, *args, **kwargs)

    async def refuse_telethon_connect(self, *args, **kwargs):
        raise deny("TelegramClient.connect", type(self).__name__)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(asyncio.BaseEventLoop, "create_connection", guarded_create_connection)
    monkeypatch.setattr(TelegramBaseClient, "connect", refuse_telethon_connect)

    yield attempts

    if attempts:
        pytest.fail("Network access attempted during the test:\n" + "\n".join(attempts), pytrace=False)
