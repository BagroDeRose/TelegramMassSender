"""Recipient resolver tests (spec item 58) using MockTelegramClient --
covers found/not-found/invalid-id/group-rejection/cache reuse without
ever touching the real Telegram network.
"""
from __future__ import annotations

import pytest
from telethon.errors import FloodWaitError

from app.recipients.parser import parse_recipient_line
from app.telegram.recipient_resolver import RecipientResolver, ResolveStatus
from tests.mocks.mock_telegram_client import MockTelegramClient, make_flood_wait


async def test_resolve_ready():
    client = MockTelegramClient(entity_behavior={"gooduser": "found"})
    resolver = RecipientResolver(client)
    result = await resolver.resolve(parse_recipient_line("@gooduser"))
    assert result.status == ResolveStatus.READY
    assert result.entity is not None


async def test_resolve_not_found():
    client = MockTelegramClient(entity_behavior={"ghost": "not_found"})
    resolver = RecipientResolver(client)
    result = await resolver.resolve(parse_recipient_line("@ghost"))
    assert result.status == ResolveStatus.NOT_FOUND


async def test_resolve_invalid_id():
    client = MockTelegramClient(entity_behavior={999999999: "invalid_id"})
    resolver = RecipientResolver(client)
    result = await resolver.resolve(parse_recipient_line("999999999"))
    assert result.status == ResolveStatus.INVALID_ID


async def test_resolve_group_rejected():
    client = MockTelegramClient(entity_behavior={"groupchat": "not_a_user"})
    resolver = RecipientResolver(client)
    result = await resolver.resolve(parse_recipient_line("@groupchat"))
    assert result.status == ResolveStatus.NOT_A_USER


async def test_resolve_invalid_format_never_hits_network():
    client = MockTelegramClient()
    resolver = RecipientResolver(client)
    result = await resolver.resolve(parse_recipient_line("###bad###"))
    assert result.status == ResolveStatus.INVALID_FORMAT


async def test_resolve_cache_reuse():
    client = MockTelegramClient(entity_behavior={"gooduser": "found"})
    resolver = RecipientResolver(client)
    parsed = parse_recipient_line("@gooduser")

    first = await resolver.resolve(parsed)
    second = await resolver.resolve(parsed)
    assert first.status == second.status == ResolveStatus.READY
    assert client.get_entity_calls == 1, "cache must avoid a redundant get_entity call"


# ---- phone-number recipients (Feature 3) ------------------------------------


async def test_resolve_phone_found():
    client = MockTelegramClient(phone_behavior={"+4917612345678": "found"})
    resolver = RecipientResolver(client)
    result = await resolver.resolve(parse_recipient_line("+4917612345678"))
    assert result.status == ResolveStatus.READY
    assert result.entity is not None


async def test_resolve_phone_not_found():
    client = MockTelegramClient(phone_behavior={"+4917612345678": "not_found"})
    resolver = RecipientResolver(client)
    result = await resolver.resolve(parse_recipient_line("+4917612345678"))
    assert result.status == ResolveStatus.PHONE_NOT_FOUND
    assert result.error


async def test_resolve_phone_privacy_restricted_empty_result():
    # Telegram deliberately does not distinguish "not registered" from
    # "registered but hidden by privacy settings" -- both surface as an
    # empty users list here, and both must produce the same friendly error.
    client = MockTelegramClient(phone_behavior={"+4917612345678": "empty"})
    resolver = RecipientResolver(client)
    result = await resolver.resolve(parse_recipient_line("+4917612345678"))
    assert result.status == ResolveStatus.PHONE_NOT_FOUND


async def test_resolve_phone_caches_within_campaign():
    client = MockTelegramClient(phone_behavior={"+4917612345678": "found"})
    resolver = RecipientResolver(client)
    parsed = parse_recipient_line("+4917612345678")

    first = await resolver.resolve(parsed)
    second = await resolver.resolve(parsed)
    assert first.status == second.status == ResolveStatus.READY
    assert len(client.raw_requests) == 1, "cache must avoid a redundant ResolvePhoneRequest"


async def test_resolve_phone_flood_wait_propagates():
    client = MockTelegramClient(phone_behavior={"+4917612345678": make_flood_wait(30)})
    resolver = RecipientResolver(client)
    with pytest.raises(FloodWaitError):
        await resolver.resolve(parse_recipient_line("+4917612345678"))


async def test_resolve_username_flood_wait_propagates():
    # Regression test: resolve() previously swallowed FloodWaitError from
    # get_entity into a generic UNAVAILABLE per-item failure, bypassing the
    # campaign's centralized FloodWait pause/resume entirely.
    client = MockTelegramClient()

    async def raise_flood(identifier):
        raise make_flood_wait(15)

    client.get_entity = raise_flood  # type: ignore[method-assign]
    resolver = RecipientResolver(client)
    with pytest.raises(FloodWaitError):
        await resolver.resolve(parse_recipient_line("@someuser"))
