"""Demo Mode with group/channel targets: DemoTelegramClient's simulated
chats produce each realistic outcome (posted, no admin rights, members
can't write, no media, slow mode) through the unmodified CampaignManager,
and the "From my chats…" listing shows the demo account's people, bots,
archive and folders, offering only what it can write to."""
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
        "Demo Old Project",
    ]
    assert "Demo Partner Channel" not in titles and "Demo Read-Only Group" not in titles


# ---- "From my chats…" against the demo account's dialogs ---------------------------


async def test_demo_dialogs_have_people_bots_archive_and_folders():
    result = await list_dialogs(DemoTelegramClient())
    by_title = {d.title: d for d in result.dialogs}
    # Saved Messages, the deleted account and 777000 are never offered.
    assert not any(d.peer_id in (700000000, 700000099, 777000) for d in result.dialogs)
    people = [d.title for d in result.dialogs if d.category.value == "people"]
    bots = [d.title for d in result.dialogs if d.category.value == "bots"]
    assert people == ["Anna Smirnova", "Ivan Petrov", "Maria Orlova", "Pavel Kuznetsov", "Olga Sokolova"]
    assert bots == ["Weather Bot", "Shop Bot"]
    assert by_title["Ivan Petrov"].recipient_line == "700000002"  # no @username: by ID
    assert {d.title for d in result.dialogs if d.archived} == {"Pavel Kuznetsov", "Shop Bot", "Demo Old Project"}
    assert [f.title for f in result.folders] == ["Work", "Family", "Bots"]
    assert 2 in by_title["Demo Team Chat"].folder_ids and 2 in by_title["Ivan Petrov"].folder_ids
    assert 3 in by_title["Demo Family"].folder_ids and 3 in by_title["Anna Smirnova"].folder_ids
    assert 3 not in by_title["Maria Orlova"].folder_ids  # not a contact
    assert 4 in by_title["Weather Bot"].folder_ids
    assert not by_title["Demo Partner Channel"].writable
    assert by_title["Demo Partner Channel"].unavailable_reason_key == "chat_targets.reason.channel_admin_required"
    assert all(d.last_message_date is not None for d in result.dialogs)


async def test_demo_mixed_campaign_to_picked_people_and_chats(qapp, monkeypatch):
    monkeypatch.setattr(demo_client_module, "FAILURE_RATE", 0.0)
    client = DemoTelegramClient()
    picked = [d for d in (await list_dialogs(client)).dialogs if d.writable and not d.archived]
    lines = [d.recipient_line for d in picked if d.title in (
        "Anna Smirnova", "Ivan Petrov", "Weather Bot", "Demo News", "Demo Family", "Demo Forum",
    )]
    assert lines == ["@demo_news", "@demo_friend", "700000002", "-900000003", "@demo_forum", "@demo_weather_bot"]
    manager, status = await run_campaign(client, lines)
    assert status == CampaignStatus.COMPLETED.value
    assert [item.status for item in manager.items] == [SendItemStatus.SENT] * 6
    greetings = {record[2] for record in client.sent_messages}
    assert {"Hello Anna", "Hello Ivan", "Hello Demo News", "Hello Demo Family"} <= greetings


async def test_demo_pick_people_and_chats_then_run_the_campaign(qapp, tmp_path, monkeypatch):
    """The whole path in the window: open the picker, tick a person with a
    @username, a person without one (added by ID), a bot and two chats,
    add them, start -- every one is delivered."""
    from PySide6.QtCore import Qt

    import app.ui.main_window as main_window_module
    from app.database.database import Database
    from app.security.secure_storage import SecureStorage

    class QuickRateLimiter:
        min_delay_seconds = max_delay_seconds = 5

        def __init__(self, *_a, **_k):
            pass

        def next_delay(self):
            return 0.01

    monkeypatch.setattr(main_window_module, "RateLimiter", QuickRateLimiter)
    monkeypatch.setattr(demo_client_module, "FAILURE_RATE", 0.0)
    window = main_window_module.MainWindow(
        database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat")
    )
    settings = window._service.settings_repository.load_app_settings()
    settings.confirm_before_start = False
    window._service.settings_repository.save_app_settings(settings)

    async def wait_until(predicate, timeout=10.0):
        deadline = asyncio.get_event_loop().time() + timeout
        while not predicate():
            assert asyncio.get_event_loop().time() < deadline, "condition not reached"
            await asyncio.sleep(0.02)

    window._enter_demo_mode()
    await wait_until(lambda: window._recipient_widget._pick_chats_button.isEnabled())
    window._recipient_widget._pick_chats_button.click()
    await wait_until(lambda: window._chat_picker is not None and window._chat_picker._loaded)
    picker = window._chat_picker
    model = picker._model
    for row in range(model.rowCount()):
        if model.dialog(row).title in ("Anna Smirnova", "Ivan Petrov", "Weather Bot", "Demo News", "Demo Family"):
            model.setData(model.index(row), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert picker._selection_label.text() == tr("chat_picker.selected_summary", count=5, parts=", ".join([
        tr("chat_picker.selected_people", count=2),
        tr("chat_picker.selected_bots", count=1),
        tr("chat_picker.selected_chats", count=2),
    ]))
    picker._add_button.click()
    await wait_until(lambda: window._chat_picker is None)
    assert window._recipient_widget.get_text().splitlines() == [
        "@demo_news", "@demo_friend", "700000002", "-900000003", "@demo_weather_bot",
    ]

    window._message_text = "Hello {name}"
    window._on_form_state_changed()
    window._on_start_requested()
    await wait_until(lambda: window._current_campaign is not None)
    campaign = window._current_campaign
    await wait_until(lambda: not campaign.is_active, timeout=20)
    assert [item.status for item in campaign.items] == [SendItemStatus.SENT] * 5
