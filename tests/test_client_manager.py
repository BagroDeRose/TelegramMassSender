"""Tests for app.telegram.client_manager.ClientManager (ROADMAP: Reliability
Tests -- "Network disconnect" / "Reconnect"). This module had no dedicated
tests before now; TelegramClient itself is mocked (constructor patched)
so nothing here touches the real Telegram network.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.telegram.client_manager import ClientManager


def _fake_client_factory():
    """A fresh MagicMock standing in for one TelegramClient instance,
    with the async methods ClientManager actually calls."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=True)
    client.is_connected = MagicMock(return_value=False)
    return client


async def test_get_or_create_returns_the_same_client_for_the_same_session():
    with patch("app.telegram.client_manager.TelegramClient", side_effect=lambda *a, **k: _fake_client_factory()):
        manager = ClientManager(api_id=1, api_hash="x")
        first = manager.get_or_create("session_a")
        second = manager.get_or_create("session_a")
        assert first is second


async def test_get_or_create_gives_different_sessions_different_clients():
    # Spec item 7: sessions are never shared/mixed between accounts.
    with patch("app.telegram.client_manager.TelegramClient", side_effect=lambda *a, **k: _fake_client_factory()):
        manager = ClientManager(api_id=1, api_hash="x")
        client_a = manager.get_or_create("session_a")
        client_b = manager.get_or_create("session_b")
        assert client_a is not client_b


async def test_connect_calls_client_connect_when_not_already_connected():
    fake_client = _fake_client_factory()
    fake_client.is_connected.return_value = False
    with patch("app.telegram.client_manager.TelegramClient", return_value=fake_client):
        manager = ClientManager(api_id=1, api_hash="x")
        await manager.connect("session_a")
    fake_client.connect.assert_awaited_once()


async def test_connect_skips_redundant_connect_when_already_connected():
    fake_client = _fake_client_factory()
    fake_client.is_connected.return_value = True
    with patch("app.telegram.client_manager.TelegramClient", return_value=fake_client):
        manager = ClientManager(api_id=1, api_hash="x")
        await manager.connect("session_a")
    fake_client.connect.assert_not_awaited()


async def test_reconnect_after_a_simulated_network_drop():
    # Simulates the "Network disconnect" -> "Reconnect" reliability
    # scenario: is_connected() flips to False (as it would after a real
    # drop), and the next connect() call must actually reconnect, not
    # silently no-op because a client object already exists.
    fake_client = _fake_client_factory()
    connected_state = {"value": True}
    fake_client.is_connected.side_effect = lambda: connected_state["value"]
    with patch("app.telegram.client_manager.TelegramClient", return_value=fake_client):
        manager = ClientManager(api_id=1, api_hash="x")
        await manager.connect("session_a")  # already "connected" -- no connect() call
        fake_client.connect.assert_not_awaited()

        connected_state["value"] = False  # the drop
        await manager.connect("session_a")  # must reconnect
        fake_client.connect.assert_awaited_once()


async def test_disconnect_is_safe_when_never_connected():
    with patch("app.telegram.client_manager.TelegramClient", side_effect=lambda *a, **k: _fake_client_factory()):
        manager = ClientManager(api_id=1, api_hash="x")
        await manager.disconnect("never_created")  # must not raise


async def test_disconnect_calls_client_disconnect_for_a_tracked_session():
    fake_client = _fake_client_factory()
    with patch("app.telegram.client_manager.TelegramClient", return_value=fake_client):
        manager = ClientManager(api_id=1, api_hash="x")
        manager.get_or_create("session_a")
        await manager.disconnect("session_a")
    fake_client.disconnect.assert_awaited_once()


async def test_disconnect_all_disconnects_every_tracked_client():
    clients = {}

    def factory(*args, **kwargs):
        c = _fake_client_factory()
        clients[len(clients)] = c
        return c

    with patch("app.telegram.client_manager.TelegramClient", side_effect=factory):
        manager = ClientManager(api_id=1, api_hash="x")
        manager.get_or_create("session_a")
        manager.get_or_create("session_b")
        await manager.disconnect_all()

    for client in clients.values():
        client.disconnect.assert_awaited_once()


async def test_get_active_client_returns_none_before_creation():
    manager = ClientManager(api_id=1, api_hash="x")
    assert manager.get_active_client("never_created") is None


async def test_get_active_client_returns_the_created_client():
    with patch("app.telegram.client_manager.TelegramClient", side_effect=lambda *a, **k: _fake_client_factory()):
        manager = ClientManager(api_id=1, api_hash="x")
        created = manager.get_or_create("session_a")
        assert manager.get_active_client("session_a") is created


async def test_remove_stops_tracking_the_session():
    with patch("app.telegram.client_manager.TelegramClient", side_effect=lambda *a, **k: _fake_client_factory()):
        manager = ClientManager(api_id=1, api_hash="x")
        manager.get_or_create("session_a")
        manager.remove("session_a")
        assert manager.get_active_client("session_a") is None


async def test_is_authorized_connects_first_then_checks():
    fake_client = _fake_client_factory()
    fake_client.is_connected.return_value = False
    fake_client.is_user_authorized.return_value = True
    with patch("app.telegram.client_manager.TelegramClient", return_value=fake_client):
        manager = ClientManager(api_id=1, api_hash="x")
        result = await manager.is_authorized("session_a")
    assert result is True
    fake_client.connect.assert_awaited_once()
    fake_client.is_user_authorized.assert_awaited_once()
