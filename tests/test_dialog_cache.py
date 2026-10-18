"""Session cache of the active account's dialogs: the picker reads them
once and reopens from memory; Refresh and any account change drop them;
a campaign's dialogs warm-up starts from them and reads the dialogs from
Telegram again only for an ID that isn't there."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.campaign.campaign_manager import CampaignManager
from app.campaign.send_queue import SendItemStatus
from app.database.database import Database
from app.recipients.parser import parse_recipient_line
from app.security.secure_storage import SecureStorage
from app.telegram import chat_targets
from app.telegram.chat_targets import DialogCache, list_dialogs, load_dialog_snapshot
from app.telegram.demo_client import DemoTelegramClient
from app.telegram.recipient_resolver import RecipientResolver, ResolveStatus
from app.ui.main_window import MainWindow
from tests.mocks.mock_telegram_client import (
    MockTelegramClient,
    make_fake_channel,
    make_fake_group,
    make_user,
)

BORIS = make_user(102, "Boris")
SELF = make_user(100, "Me", is_self=True)
TEAM = make_fake_channel(203, "Team")
FAMILY = make_fake_group(205, "Family")


def _client(**kwargs) -> MockTelegramClient:
    return MockTelegramClient(dialogs=[BORIS, SELF, TEAM, FAMILY], uncached_user_ids={102, 999}, **kwargs)


class Instant:
    def next_delay(self):
        return 0.01


# ---- the snapshot and the cache ------------------------------------------------------


async def test_snapshot_carries_the_entities_of_every_dialog():
    snapshot = await load_dialog_snapshot(_client())
    assert [d.title for d in snapshot.dialogs.dialogs] == ["Boris", "Team", "Family"]
    assert snapshot.users[102] is BORIS and snapshot.users[100] is SELF  # left out of the list only
    assert snapshot.chats[-1000000000203] is TEAM and snapshot.chats[-205] is FAMILY
    assert await list_dialogs(_client()) == snapshot.dialogs


def test_cache_answers_only_for_the_account_it_was_filled_for():
    cache = DialogCache()
    snapshot = object()
    assert cache.get((1, "a")) is None
    cache.put((1, "a"), snapshot)
    assert cache.get((1, "a")) is snapshot
    assert cache.get((2, "b")) is None
    cache.clear()
    assert cache.get((1, "a")) is None


# ---- the resolver warm-up starts from the cache ----------------------------------------


async def test_ids_in_the_cache_need_no_dialogs_read():
    snapshot = await load_dialog_snapshot(_client())
    client = _client()
    resolver = RecipientResolver(client, snapshot)
    chat = await resolver.resolve(parse_recipient_line("-1000000000203"))
    group = await resolver.resolve(parse_recipient_line("-205"))
    person = await resolver.resolve(parse_recipient_line("102"))  # unknown to the session itself
    assert (chat.entity, group.entity, person.entity) == (TEAM, FAMILY, BORIS)
    assert client.dialogs_calls == 0
    assert client.get_entity_calls == 0


async def test_chat_missing_from_the_cache_reads_the_dialogs_once():
    old = await load_dialog_snapshot(MockTelegramClient(dialogs=[TEAM]))
    client = _client()
    resolver = RecipientResolver(client, old)
    family = await resolver.resolve(parse_recipient_line("-205"))  # joined since the picker read
    assert family.entity is FAMILY
    assert client.dialogs_calls == 1
    gone = await resolver.resolve(parse_recipient_line("-1000000000777"))
    assert gone.status == ResolveStatus.NOT_MEMBER
    assert client.dialogs_calls == 1  # never more than once per campaign


async def test_person_missing_from_the_cache_reads_the_dialogs_once():
    old = await load_dialog_snapshot(MockTelegramClient(dialogs=[TEAM]))
    client = _client()
    resolver = RecipientResolver(client, old)
    boris = await resolver.resolve(parse_recipient_line("102"))
    unknown = await resolver.resolve(parse_recipient_line("999"))
    assert boris.entity is BORIS
    assert unknown.status == ResolveStatus.NOT_FOUND
    assert client.dialogs_calls == 1


async def test_without_a_cache_nothing_changes():
    client = _client()
    resolver = RecipientResolver(client)
    assert not resolver.dialogs_loaded
    assert (await resolver.resolve(parse_recipient_line("-205"))).entity is FAMILY
    assert client.dialogs_calls == 1


async def test_campaign_with_the_cached_dialogs_reads_nothing_again():
    snapshot = await load_dialog_snapshot(_client())
    client = _client()
    campaign = CampaignManager(
        client=client,
        recipients=[parse_recipient_line(line) for line in ("102", "-1000000000203", "-205")],
        message_text="Hi {name}",
        message_entities=[],
        attachments=[],
        rate_limiter=Instant(),
        max_retries=1,
        dialog_snapshot=snapshot,
    )
    done = asyncio.get_event_loop().create_future()
    campaign.finished.connect(lambda s: done.done() or done.set_result(s))
    campaign.start()
    await asyncio.wait_for(done, timeout=5)
    assert [item.status for item in campaign.items] == [SendItemStatus.SENT] * 3
    assert client.dialogs_calls == 0


# ---- MainWindow ------------------------------------------------------------------------


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


async def _open_and_close(window: MainWindow) -> None:
    window._recipient_widget._pick_chats_button.click()
    await _wait_until(lambda: window._chat_picker is not None and window._chat_picker._loaded)
    window._chat_picker.reject()
    await _wait_until(lambda: window._chat_picker is None)


def _counting_loader():
    calls = []
    real = chat_targets.load_dialog_snapshot

    async def counting(client, now=None):
        calls.append(client)
        return await real(client, now)

    return calls, counting


async def test_picker_reads_once_per_session_and_refresh_reads_again(qapp, tmp_path):
    window = await _demo_window(tmp_path)
    calls, counting = _counting_loader()
    with patch("app.ui.main_window.load_dialog_snapshot", new=counting):
        await _open_and_close(window)
        await _open_and_close(window)
        assert len(calls) == 1  # the second open came from the cache

        window._recipient_widget._pick_chats_button.click()
        picker = window._chat_picker
        assert picker._loaded  # shown at once, no loading state
        picker._refresh_button.click()
        assert window._dialog_cache.get(window._dialog_cache_key(window._active_account())) is None
        await _wait_until(lambda: len(calls) == 2 and picker._loaded and picker._pages.currentWidget() is picker._list)
        picker.reject()
        await _wait_until(lambda: window._chat_picker is None)
        await _open_and_close(window)
    assert len(calls) == 2
    assert window._dialog_cache.get(window._dialog_cache_key(window._active_account())) is not None


async def test_demo_mode_transition_drops_the_cache(qapp, tmp_path):
    window = await _demo_window(tmp_path)
    calls, counting = _counting_loader()
    with patch("app.ui.main_window.load_dialog_snapshot", new=counting):
        await _open_and_close(window)
        key = window._dialog_cache_key(window._active_account())
        assert window._dialog_cache.get(key) is not None
        # Leaving Demo Mode (the service swap itself is mocked out: with no
        # real account the app would go on to ask for one).
        with patch.object(window._service, "exit_demo_mode"), patch.object(window, "_spawn"), patch.object(
            window, "_refresh_accounts", new=MagicMock()
        ):
            window._transition_demo_mode(enter=False)
        assert window._dialog_cache.get(key) is None
        await _open_and_close(window)  # reads again
    assert len(calls) == 2


async def test_switching_accounts_drops_the_cache(qapp, tmp_path):
    window = await _demo_window(tmp_path)
    await _open_and_close(window)
    account = window._active_account()
    window._dialog_cache.put(window._dialog_cache_key(account), object())
    manager = window._service.account_manager
    with patch.object(manager, "switch_active_account"), patch.object(
        type(manager), "active_account_id", new_callable=lambda: property(lambda self: account.id)
    ):
        await window._switch_account(account.id + 1)
    assert window._dialog_cache.get(window._dialog_cache_key(account)) is None


async def test_campaign_started_after_picking_uses_the_cache(qapp, tmp_path, monkeypatch):
    import app.telegram.demo_client as demo_client_module
    import app.ui.main_window as main_window_module

    class QuickRateLimiter:
        min_delay_seconds = max_delay_seconds = 5

        def __init__(self, *_a, **_k):
            pass

        def next_delay(self):
            return 0.01

    monkeypatch.setattr(main_window_module, "RateLimiter", QuickRateLimiter)
    monkeypatch.setattr(demo_client_module, "FAILURE_RATE", 0.0)
    reads = []
    real_iter = DemoTelegramClient.iter_dialogs

    def counting_iter(self, *args, **kwargs):
        reads.append(1)
        return real_iter(self, *args, **kwargs)

    monkeypatch.setattr(DemoTelegramClient, "iter_dialogs", counting_iter)
    window = await _demo_window(tmp_path)
    await _open_and_close(window)
    assert len(reads) == 1

    window._recipient_widget.set_text("700000002\n-900000003\n-1001900000002")
    window._message_text = "Hello {name}"
    window._on_start_requested()
    await _wait_until(lambda: window._current_campaign is not None)
    campaign = window._current_campaign
    await _wait_until(lambda: not campaign.is_active, timeout=10)
    assert [item.status for item in campaign.items] == [SendItemStatus.SENT] * 3
    assert len(reads) == 1  # the warm-up found everything in the cache


async def test_large_campaign_breakdown_knows_bots_from_the_cache(qapp, tmp_path):
    window = await _demo_window(tmp_path)
    recipients = [parse_recipient_line(line) for line in ("@demo_weather_bot", "@demo_friend", "@demo_news", "@who_knows")]
    before = window._recipient_breakdown(recipients)
    assert (before.people, before.bots, before.chats, before.unknown) == (0, 0, 0, 4)
    await _open_and_close(window)
    after = window._recipient_breakdown(recipients)
    assert (after.people, after.bots, after.chats, after.unknown) == (1, 1, 1, 1)
