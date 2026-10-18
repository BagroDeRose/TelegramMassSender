"""A person picked by ID in "From my chats…" (no @username) must still be
reachable when the campaign starts, even if the session has no
access_hash for that ID: the resolver reads the dialogs once -- the same
warm-up chat IDs already use -- and takes the user from there."""
from __future__ import annotations

import asyncio

import pytest
from telethon.errors import FloodWaitError

from app.campaign.campaign_manager import CampaignManager
from app.campaign.send_queue import SendItemStatus
from app.recipients.parser import parse_recipient_line
from app.telegram.recipient_resolver import RecipientResolver, ResolveStatus
from tests.mocks.mock_telegram_client import (
    MockTelegramClient,
    make_fake_channel,
    make_flood_wait,
    make_user,
)

BORIS = make_user(102, "Boris")
OLGA = make_user(103, "Olga")
TEAM = make_fake_channel(203, "Team")


def _client(**kwargs) -> MockTelegramClient:
    return MockTelegramClient(dialogs=[BORIS, OLGA, TEAM], uncached_user_ids={102, 103, 999}, **kwargs)


async def test_uncached_user_id_resolves_through_the_dialogs():
    client = _client()
    resolver = RecipientResolver(client)
    result = await resolver.resolve(parse_recipient_line("102"))
    assert result.status == ResolveStatus.READY
    assert result.entity is BORIS
    assert client.dialogs_calls == 1


async def test_dialogs_are_read_once_for_many_uncached_ids():
    client = _client()
    resolver = RecipientResolver(client)
    first = await resolver.resolve(parse_recipient_line("102"))
    second = await resolver.resolve(parse_recipient_line("103"))
    unknown = await resolver.resolve(parse_recipient_line("999"))
    assert (first.entity, second.entity) == (BORIS, OLGA)
    assert unknown.status == ResolveStatus.NOT_FOUND
    assert client.dialogs_calls == 1


async def test_cached_user_id_needs_no_dialogs():
    client = MockTelegramClient(dialogs=[BORIS])
    result = await RecipientResolver(client).resolve(parse_recipient_line("555"))
    assert result.status == ResolveStatus.READY
    assert client.dialogs_calls == 0


async def test_user_from_already_loaded_dialogs_needs_no_lookup():
    client = _client()
    resolver = RecipientResolver(client)
    await resolver.resolve(parse_recipient_line("-1000000000203"))  # warms the dialogs
    calls = client.get_entity_calls
    result = await resolver.resolve(parse_recipient_line("103"))
    assert result.entity is OLGA
    assert client.get_entity_calls == calls
    assert client.dialogs_calls == 1


async def test_flood_wait_during_the_warm_up_propagates_and_is_retried_later():
    client = _client(dialogs_errors=[make_flood_wait(30)])
    resolver = RecipientResolver(client)
    with pytest.raises(FloodWaitError):
        await resolver.resolve(parse_recipient_line("102"))
    assert not resolver.dialogs_loaded
    result = await resolver.resolve(parse_recipient_line("102"))
    assert result.entity is BORIS


async def test_campaign_reaches_a_person_added_by_id():
    client = _client()

    class Instant:
        def next_delay(self):
            return 0.01

    campaign = CampaignManager(
        client=client,
        recipients=[parse_recipient_line("102"), parse_recipient_line("-1000000000203")],
        message_text="Hello, {name}!",
        message_entities=[],
        attachments=[],
        rate_limiter=Instant(),
        max_retries=1,
    )
    done = asyncio.get_event_loop().create_future()
    campaign.finished.connect(lambda s: done.done() or done.set_result(s))
    campaign.start()
    await asyncio.wait_for(done, timeout=5)
    assert [item.status for item in campaign.items] == [SendItemStatus.SENT, SendItemStatus.SENT]
    sent_to = [record[1] for record in client.sent_messages]
    assert sent_to == [BORIS, TEAM]
    assert client.sent_messages[0][2] == "Hello, Boris!"
    assert client.dialogs_calls == 1
