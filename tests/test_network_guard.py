"""The suite-wide network guard (tests/conftest.py::_block_network) refuses
real connections at every layer the app could open one through, and still
lets loopback-only machinery (asyncio's self-pipe socketpair) work.

Each test clears the recorded attempts after asserting on them -- otherwise
the guard's own teardown would (correctly) fail it.
"""
from __future__ import annotations

import asyncio
import socket

import pytest
from telethon import TelegramClient
from telethon.sessions import MemorySession

from tests.conftest import NetworkAccessError

TEST_NET_ADDRESS = ("203.0.113.10", 443)  # RFC 5737 documentation range


def test_plain_socket_connect_is_refused(_block_network):
    with socket.socket() as sock, pytest.raises(NetworkAccessError):
        sock.connect(TEST_NET_ADDRESS)
    assert len(_block_network) == 1
    _block_network.clear()


def test_create_connection_is_refused(_block_network):
    with pytest.raises(NetworkAccessError):
        socket.create_connection(TEST_NET_ADDRESS, timeout=1)
    _block_network.clear()


async def test_asyncio_open_connection_is_refused(_block_network):
    with pytest.raises(NetworkAccessError):
        await asyncio.open_connection(*TEST_NET_ADDRESS)
    _block_network.clear()


async def test_real_telethon_connect_is_refused(_block_network):
    client = TelegramClient(MemorySession(), 1, "0" * 32)
    with pytest.raises(NetworkAccessError):
        await client.connect()
    assert "TelegramClient.connect" in _block_network[0]
    _block_network.clear()


def test_a_swallowed_attempt_is_still_recorded(_block_network):
    # Production code often turns a failed connect into a status/log line;
    # the attempt must still be visible to the guard's teardown.
    try:
        socket.create_connection(TEST_NET_ADDRESS, timeout=1)
    except Exception:  # noqa: BLE001 - deliberately swallowed, like app code does
        pass
    assert _block_network, "the guard must record the attempt even when it is swallowed"
    _block_network.clear()


def test_loopback_is_allowed():
    a, b = socket.socketpair()
    try:
        a.sendall(b"x")
        assert b.recv(1) == b"x"
    finally:
        a.close()
        b.close()
