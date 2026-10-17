"""Campaign engine with group/supergroup/channel targets: mixed lists,
permission preflight, chat-specific error reasons, slow mode (fails the
target, never pauses), FloodWait (unchanged: pause + manual resume),
invite links that are never joined, {name} = chat title, runtime
duplicate-chat protection and the Retry carry-over parameters.
"""
from __future__ import annotations

import asyncio

from telethon.errors import ChatWriteForbiddenError, SlowModeWaitError, rpc_message_to_error
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from app.campaign.campaign_manager import CampaignManager
from app.campaign.campaign_state import CampaignStatus
from app.campaign.send_queue import SendItemStatus
from app.i18n import tr
from app.recipients.parser import parse_recipient_line
from app.telegram.chat_targets import TargetType
from app.telegram.media_sender import Attachment
from tests.mocks.mock_telegram_client import (
    MockTelegramClient,
    admin_rights,
    banned_rights,
    make_fake_channel,
    make_fake_group,
    make_flood_wait,
)


class FakeRateLimiter:
    def next_delay(self) -> float:
        return 0.01


def make_manager(client, lines, text="hello", attachments=None, names=None, **kwargs):
    return CampaignManager(
        client=client,
        recipients=[parse_recipient_line(line) for line in lines],
        message_text=text,
        message_entities=[],
        attachments=attachments or [],
        rate_limiter=FakeRateLimiter(),
        max_retries=2,
        recipient_names=names,
        **kwargs,
    )


async def run_to_finish(manager, timeout=10):
    fut = asyncio.get_event_loop().create_future()
    manager.finished.connect(lambda status: fut.done() or fut.set_result(status))
    manager.start()
    return await asyncio.wait_for(fut, timeout=timeout)


async def run_until_paused(manager, timeout=10):
    paused = asyncio.get_event_loop().create_future()
    manager.state_changed.connect(
        lambda s: paused.done() or (s == CampaignStatus.PAUSED.value and paused.set_result(True))
    )
    manager.start()
    await asyncio.wait_for(paused, timeout=timeout)


async def resume_to_finish(manager, timeout=10):
    finished = asyncio.get_event_loop().create_future()
    manager.finished.connect(lambda s: finished.done() or finished.set_result(s))
    manager.resume()
    return await asyncio.wait_for(finished, timeout=timeout)


def sent_to(client, entity):
    return [m for m in client.sent_messages if m[1] is entity]


def by_label(manager):
    return {item.recipient.display_label: item for item in manager.items}


def no_join_requests(client):
    return not any(isinstance(r, (ImportChatInviteRequest, JoinChannelRequest)) for r in client.raw_requests)


# ---- mixed list ---------------------------------------------------------------


async def test_mixed_list_of_users_and_chats(qapp):
    channel = make_fake_channel(100, "Daily News", username="daily_news", broadcast=True, creator=True)
    supergroup = make_fake_channel(1234567890, "Team Room")
    basic = make_fake_group(987654321, "Family")
    client = MockTelegramClient(
        first_name_behavior={"ivan_petrov": "Ivan"},
        chats={"daily_news": channel, -1001234567890: supergroup, -987654321: basic},
        dialogs=[channel, supergroup, basic],
    )
    manager = make_manager(
        client,
        ["@ivan_petrov", "@daily_news", "-1001234567890", "-987654321", "+4917612345678"],
        text="Hi {name}!",
    )

    status = await run_to_finish(manager)

    assert status == CampaignStatus.COMPLETED.value
    assert manager.snapshot().sent == 5
    texts = [m[2] for m in client.sent_messages]
    assert texts == ["Hi Ivan!", "Hi Daily News!", "Hi Team Room!", "Hi Family!", "Hi !"]
    items = by_label(manager)
    assert items["@ivan_petrov"].target_type == TargetType.USER.value
    assert items["@daily_news"].target_type == TargetType.CHANNEL.value
    assert items["-1001234567890"].target_type == TargetType.SUPERGROUP.value
    assert items["-987654321"].target_type == TargetType.GROUP.value
    # Chats record their marked id, so it can be re-entered as a target.
    assert items["-1001234567890"].resolved_id == -1001234567890
    assert items["@daily_news"].resolved_username == "daily_news"
    assert client.dialogs_calls == 1


async def test_user_only_campaign_never_fetches_dialogs(qapp):
    client = MockTelegramClient()
    manager = make_manager(client, ["@alice_one", "123456789", "+4917612345678"])
    await run_to_finish(manager)
    assert manager.snapshot().sent == 3
    assert client.dialogs_calls == 0


# ---- {name} --------------------------------------------------------------------


async def test_name_placeholder_is_chat_title_and_csv_name_wins(qapp):
    one = make_fake_channel(1, "Chat One", username="chat_one")
    two = make_fake_channel(2, "Chat Two", username="chat_two")
    client = MockTelegramClient(chats={"chat_one": one, "chat_two": two})
    manager = make_manager(
        client, ["@chat_one", "@chat_two"], text="Dear {name}", names={"username:chat_two": "Team from CSV"}
    )
    await run_to_finish(manager)
    assert [m[2] for m in client.sent_messages] == ["Dear Chat One", "Dear Team from CSV"]


# ---- preflight ------------------------------------------------------------------


async def test_channel_without_admin_rights_fails_and_campaign_continues(qapp):
    channel = make_fake_channel(1, "Someone's channel", username="their_channel", broadcast=True)
    client = MockTelegramClient(chats={"their_channel": channel})
    manager = make_manager(client, ["@their_channel", "@alice_one"])

    status = await run_to_finish(manager)

    assert status == CampaignStatus.COMPLETED.value
    item = by_label(manager)["@their_channel"]
    assert item.status == SendItemStatus.FAILED
    assert item.error == tr("chat_targets.reason.channel_admin_required")
    assert sent_to(client, channel) == []
    assert by_label(manager)["@alice_one"].status == SendItemStatus.SENT


async def test_group_where_writing_is_disabled(qapp):
    group = make_fake_channel(7, "Announcements only", username="ann_group", default_banned=banned_rights(send_messages=True))
    client = MockTelegramClient(chats={"ann_group": group})
    manager = make_manager(client, ["@ann_group"])
    await run_to_finish(manager)
    item = manager.items[0]
    assert item.status == SendItemStatus.FAILED
    assert item.error == tr("chat_targets.reason.write_forbidden")
    assert client.sent_messages == []


async def test_media_forbidden_when_campaign_has_attachments(qapp, tmp_path):
    photo = tmp_path / "pic.jpg"
    photo.write_bytes(b"jpg")
    group = make_fake_channel(8, "No media", username="no_media", default_banned=banned_rights(send_media=True))
    client = MockTelegramClient(chats={"no_media": group})
    manager = make_manager(client, ["@no_media", "@alice_one"], attachments=[Attachment(photo)])

    await run_to_finish(manager)

    item = by_label(manager)["@no_media"]
    assert item.status == SendItemStatus.FAILED
    assert item.error == tr("chat_targets.reason.media_forbidden")
    assert sent_to(client, group) == []
    assert by_label(manager)["@alice_one"].status == SendItemStatus.SENT


async def test_media_forbidden_does_not_block_a_text_only_campaign(qapp):
    group = make_fake_channel(8, "No media", username="no_media", default_banned=banned_rights(send_media=True))
    client = MockTelegramClient(chats={"no_media": group})
    manager = make_manager(client, ["@no_media"])
    await run_to_finish(manager)
    assert manager.items[0].status == SendItemStatus.SENT


# ---- send-time errors ----------------------------------------------------------


async def test_slow_mode_fails_the_target_without_pausing(qapp):
    slow = make_fake_channel(9, "Slow chat", username="slow_chat", slowmode_enabled=True)
    client = MockTelegramClient(
        chats={"slow_chat": slow},
        chat_send_behavior={-1000000000009: SlowModeWaitError(request=None, capture=37)},
    )
    manager = make_manager(client, ["@slow_chat", "@alice_one"])
    states = []
    manager.state_changed.connect(states.append)
    flood_waits = []
    manager.flood_wait_started.connect(flood_waits.append)

    status = await run_to_finish(manager)

    assert status == CampaignStatus.COMPLETED.value
    assert CampaignStatus.PAUSED.value not in states
    assert CampaignStatus.WAITING_FOR_FLOOD.value not in states
    assert flood_waits == []
    item = by_label(manager)["@slow_chat"]
    assert item.status == SendItemStatus.FAILED
    assert item.error == tr("chat_targets.reason.slowmode_wait", seconds=37)
    assert by_label(manager)["@alice_one"].status == SendItemStatus.SENT


async def test_flood_wait_in_a_chat_pauses_exactly_like_for_users(qapp):
    group = make_fake_channel(10, "Busy", username="busy_group")
    client = MockTelegramClient(
        chats={"busy_group": group},
        chat_send_behavior={-1000000000010: [make_flood_wait(1), None]},
    )
    manager = make_manager(client, ["@busy_group", "@alice_one"])

    await run_until_paused(manager)
    assert manager.status == CampaignStatus.PAUSED
    assert all(item.status == SendItemStatus.PENDING for item in manager.items)

    status = await resume_to_finish(manager)
    assert status == CampaignStatus.COMPLETED.value
    assert len(sent_to(client, group)) == 1
    assert manager.snapshot().sent == 2


async def test_flood_wait_while_warming_dialogs_pauses_and_resumes(qapp):
    group = make_fake_channel(1234567890, "Team")
    client = MockTelegramClient(chats={-1001234567890: group}, dialogs=[group], dialogs_errors=[make_flood_wait(1)])
    manager = make_manager(client, ["-1001234567890"])

    await run_until_paused(manager)
    assert manager.items[0].status == SendItemStatus.PENDING

    status = await resume_to_finish(manager)
    assert status == CampaignStatus.COMPLETED.value
    assert manager.items[0].status == SendItemStatus.SENT
    assert client.dialogs_calls == 2


async def test_write_forbidden_reason_differs_for_chats_and_users(qapp):
    group = make_fake_channel(11, "G", username="some_group")
    client = MockTelegramClient(chats={"some_group": group}, chat_send_behavior={-1000000000011: ChatWriteForbiddenError(request=None)})
    original_send = client.send_message

    async def users_forbidden_too(entity, text, formatting_entities=None):
        if entity is not group:
            raise ChatWriteForbiddenError(request=None)
        return await original_send(entity, text, formatting_entities)

    client.send_message = users_forbidden_too
    manager = make_manager(client, ["@some_group", "@alice_one"])
    await run_to_finish(manager)
    items = by_label(manager)
    assert items["@some_group"].error == tr("chat_targets.reason.write_forbidden")
    # Users keep exactly the reason they always had.
    assert items["@alice_one"].error == tr("campaign_manager.error.write_forbidden")


async def test_forum_general_topic_closed(qapp):
    forum = make_fake_channel(12, "Forum", username="forum_chat", forum=True)
    rpc = type("RpcError", (), {"error_code": 400, "error_message": "TOPIC_CLOSED"})()
    client = MockTelegramClient(chats={"forum_chat": forum}, chat_send_behavior={-1000000000012: rpc_message_to_error(rpc, None)})
    manager = make_manager(client, ["@forum_chat"])
    await run_to_finish(manager)
    item = manager.items[0]
    assert item.target_type == TargetType.FORUM.value
    assert item.error == tr("chat_targets.reason.forum_general_closed")


async def test_forum_general_send_goes_to_the_chat_itself(qapp):
    forum = make_fake_channel(13, "Forum", username="forum_ok", forum=True)
    client = MockTelegramClient(chats={"forum_ok": forum})
    manager = make_manager(client, ["@forum_ok"])
    await run_to_finish(manager)
    # No reply_to/topic id: Telegram delivers a plain send to "General".
    assert sent_to(client, forum) == [("message", forum, "hello", None)]


# ---- invite links -----------------------------------------------------------------


async def test_invite_link_to_chat_the_account_is_not_in(qapp):
    client = MockTelegramClient(invite_behavior={"InviteHash1": "not_member"})
    manager = make_manager(client, ["https://t.me/+InviteHash1", "@alice_one"])
    await run_to_finish(manager)
    item = by_label(manager)["t.me/+InviteHash1"]
    assert item.status == SendItemStatus.FAILED
    assert item.error == tr("chat_targets.reason.not_member")
    assert no_join_requests(client)
    assert by_label(manager)["@alice_one"].status == SendItemStatus.SENT


async def test_invite_link_to_chat_the_account_is_in(qapp):
    group = make_fake_channel(14, "Club")
    client = MockTelegramClient(invite_behavior={"InviteHash1": group})
    manager = make_manager(client, ["https://t.me/+InviteHash1"])
    await run_to_finish(manager)
    assert manager.items[0].status == SendItemStatus.SENT
    assert len(sent_to(client, group)) == 1
    assert no_join_requests(client)


# ---- duplicates / retry carry-over ---------------------------------------------


async def test_same_chat_by_username_and_id_is_delivered_once(qapp):
    group = make_fake_channel(1234567890, "Team", username="team_room")
    client = MockTelegramClient(chats={"team_room": group, -1001234567890: group}, dialogs=[group])
    manager = make_manager(client, ["@team_room", "-1001234567890"])
    await run_to_finish(manager)
    items = by_label(manager)
    assert items["@team_room"].status == SendItemStatus.SENT
    assert items["-1001234567890"].status == SendItemStatus.SKIPPED
    assert items["-1001234567890"].error == tr("chat_targets.reason.duplicate_chat")
    assert len(sent_to(client, group)) == 1


async def test_already_delivered_chat_ids_are_skipped(qapp):
    group = make_fake_channel(15, "Team", username="team_room")
    client = MockTelegramClient(chats={"team_room": group})
    manager = make_manager(client, ["@team_room"], delivered_chat_ids={-1000000000015})
    await run_to_finish(manager)
    assert manager.items[0].status == SendItemStatus.SKIPPED
    assert client.sent_messages == []


async def test_resume_steps_skip_already_delivered_parts(qapp, tmp_path):
    doc_a = tmp_path / "a.pdf"
    doc_a.write_bytes(b"a")
    doc_b = tmp_path / "b.pdf"
    doc_b.write_bytes(b"b")
    group = make_fake_channel(16, "Team", username="team_room", admin=admin_rights(post_messages=True))
    client = MockTelegramClient(chats={"team_room": group})
    manager = make_manager(
        client,
        ["@team_room"],
        text="",
        attachments=[Attachment(doc_a), Attachment(doc_b)],
        resume_steps={"username:team_room": 1},
    )
    await run_to_finish(manager)
    assert manager.items[0].status == SendItemStatus.SENT
    assert [m[2] for m in sent_to(client, group)] == [str(doc_b)]
