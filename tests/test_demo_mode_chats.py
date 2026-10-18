"""Demo Mode with group/channel targets: DemoTelegramClient's simulated
chats produce each realistic outcome (posted, no admin rights, members
can't write, no media, slow mode) through the unmodified CampaignManager,
and the "From my chats…" listing only offers chats the demo account can
post to."""
from __future__ import annotations

import asyncio

from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

import app.telegram.demo_client as demo_client_module
from app.campaign.campaign_manager import CampaignManager
from app.campaign.campaign_state import CampaignStatus
from app.campaign.send_queue import SendItemStatus
from app.i18n import tr
from app.recipients.parser import parse_recipient_line
from app.telegram.chat_targets import TargetType, list_dialogs
from app.telegram.demo_client import DEMO_INVITE_HASH, DemoTelegramClient
from app.telegram.media_sender import Attachment


class FakeRateLimiter:
    def next_delay(self) -> float:
        return 0.01


async def run_campaign(client, lines, attachments=None, text="Hello {name}"):
    manager = CampaignManager(
        client=client,
        recipients=[parse_recipient_line(line) for line in lines],
        message_text=text,
        message_entities=[],
        attachments=attachments or [],
        rate_limiter=FakeRateLimiter(),
        max_retries=1,
    )
    fut = asyncio.get_event_loop().create_future()
    manager.finished.connect(lambda status: fut.done() or fut.set_result(status))
    manager.start()
    status = await asyncio.wait_for(fut, timeout=15)
    return manager, status


def items_by_label(manager):
    return {item.recipient.display_label: item for item in manager.items}


async def test_mixed_demo_campaign_covers_every_chat_outcome(qapp, monkeypatch):
    monkeypatch.setattr(demo_client_module, "FAILURE_RATE", 0.0)  # users always succeed here
    client = DemoTelegramClient()
    manager, status = await run_campaign(
        client,
        [
            "@alice_demo",
            "@demo_news",  # own channel -> posted
            "-1001900000002",  # Demo Team Chat by marked id -> posted
            "-900000003",  # basic group -> posted
            "@demo_forum",  # forum -> posted to General
            "@demo_partner_channel",  # not a posting admin
            "@demo_readonly_group",  # members can't write
            "@demo_slow_chat",  # slow mode
            "https://t.me/+NotJoinedHash",  # account isn't in that chat
            f"https://t.me/+{DEMO_INVITE_HASH}",  # same chat as Team Chat -> duplicate, skipped
        ],
    )

    assert CampaignStatus(status) == CampaignStatus.COMPLETED
    items = items_by_label(manager)
    for label in ("@alice_demo", "@demo_news", "-1001900000002", "-900000003", "@demo_forum"):
        assert items[label].status == SendItemStatus.SENT, label
    assert items["@demo_news"].target_type == TargetType.CHANNEL.value
    assert items["-900000003"].target_type == TargetType.GROUP.value
    assert items["@demo_forum"].target_type == TargetType.FORUM.value
    assert items["@demo_partner_channel"].error == tr("chat_targets.reason.channel_admin_required")
    assert items["@demo_readonly_group"].error == tr("chat_targets.reason.write_forbidden")
    assert items["@demo_slow_chat"].status == SendItemStatus.FAILED
    slow_reasons = {tr("chat_targets.reason.slowmode_wait", seconds=n) for n in range(1, demo_client_module.DEMO_SLOWMODE_SECONDS + 1)}
    assert items["@demo_slow_chat"].error in slow_reasons
    assert items["t.me/+NotJoinedHash"].error == tr("chat_targets.reason.not_member")
    assert items[f"t.me/+{DEMO_INVITE_HASH}"].status == SendItemStatus.SKIPPED
    texts = [m[2] for m in client.sent_messages]
    assert "Hello Demo News" in texts and "Hello Demo Family" in texts


async def test_demo_text_only_group_refuses_attachments(qapp, tmp_path):
    photo = tmp_path / "demo.jpg"
    photo.write_bytes(b"jpg")
    client = DemoTelegramClient()
    manager, _ = await run_campaign(client, ["@demo_text_only"], attachments=[Attachment(photo)])
    assert manager.items[0].error == tr("chat_targets.reason.media_forbidden")
    text_manager, _ = await run_campaign(client, ["@demo_text_only"])
    assert text_manager.items[0].status == SendItemStatus.SENT


async def test_demo_slow_chat_accepts_a_post_once_slow_mode_has_passed(qapp, monkeypatch):
    client = DemoTelegramClient()
    first, _ = await run_campaign(client, ["@demo_slow_chat"])
    assert first.items[0].status == SendItemStatus.FAILED
    client.last_chat_post.clear()  # as if DEMO_SLOWMODE_SECONDS had elapsed
    retry, _ = await run_campaign(client, ["@demo_slow_chat"])
    assert retry.items[0].status == SendItemStatus.SENT


async def test_demo_never_joins_a_chat(qapp, monkeypatch):
    requests = []
    original_call = DemoTelegramClient.__call__

    async def recording_call(self, request):
        requests.append(request)
        return await original_call(self, request)

    # client(request) looks __call__ up on the type, so patch the class.
    monkeypatch.setattr(DemoTelegramClient, "__call__", recording_call)
    client = DemoTelegramClient()
    await run_campaign(client, ["https://t.me/+SomethingElse", f"https://t.me/+{DEMO_INVITE_HASH}"])
    assert len(requests) == 2  # the two invite checks, and nothing else
    assert not any(isinstance(r, (ImportChatInviteRequest, JoinChannelRequest)) for r in requests)


async def test_demo_chat_picker_offers_only_writable_chats():
    dialogs = (await list_dialogs(DemoTelegramClient())).dialogs
    titles = [d.title for d in dialogs if d.target_type.is_chat and d.writable]
    assert titles == [
        "Demo News",
        "Demo Team Chat",
        "Demo Family",
        "Demo Forum",
        "Demo Text-Only Group",
        "Demo Slow Chat",
    ]
    assert "Demo Partner Channel" not in titles and "Demo Read-Only Group" not in titles
