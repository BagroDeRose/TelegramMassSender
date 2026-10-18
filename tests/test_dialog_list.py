"""app.telegram.chat_targets.list_dialogs -- every dialog of the account
for the "From my chats…" picker (people, bots, groups, supergroups,
forums, channels), with archive flag, last-message date, writability and
folder membership. Against MockTelegramClient only.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import GetDialogFiltersRequest, ImportChatInviteRequest
from telethon.tl.types import (
    ChannelForbidden,
    DialogFilter,
    DialogFilterChatlist,
    DialogFilterDefault,
    InputPeerChannel,
    InputPeerChat,
    InputPeerUser,
)

from app.recipients.parser import RecipientKind, parse_recipient_line
from app.telegram.chat_targets import DialogCategory, TargetType, list_dialogs
from tests.mocks.mock_telegram_client import (
    FakeDialog,
    MockTelegramClient,
    banned_rights,
    make_fake_channel,
    make_fake_group,
    make_flood_wait,
    make_user,
)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

ANNA = make_user(101, "Anna", "Petrova", username="anna_p", contact=True)
BORIS = make_user(102, "Boris", contact=False)
HELPER_BOT = make_user(103, "Helper", username="helper_bot", bot=True)
SELF = make_user(100, "Me", is_self=True)
DELETED = make_user(104, deleted=True)
SERVICE = make_user(777000, "Telegram")
NEWS = make_fake_channel(201, "News", username="news", broadcast=True, creator=True)
READ_ONLY = make_fake_channel(202, "Read-only channel", broadcast=True)
TEAM = make_fake_channel(203, "Team")
MUTED_GROUP = make_fake_channel(204, "Members can't write", default_banned=banned_rights(send_messages=True))
FAMILY = make_fake_group(205, "Family")
FORUM = make_fake_channel(206, "Forum", forum=True)


def _client(**kwargs) -> MockTelegramClient:
    dialogs = kwargs.pop(
        "dialogs",
        [
            FakeDialog(ANNA, date=NOW, unread_count=2),
            FakeDialog(SELF, date=NOW),
            FakeDialog(BORIS, date=NOW - timedelta(days=1), archived=True),
            FakeDialog(SERVICE, date=NOW),
            FakeDialog(HELPER_BOT, date=NOW - timedelta(days=2), muted=True),
            FakeDialog(DELETED, date=NOW),
            FakeDialog(NEWS, date=NOW - timedelta(hours=1)),
            FakeDialog(READ_ONLY, date=NOW - timedelta(hours=2)),
            FakeDialog(TEAM, date=NOW - timedelta(hours=3), unread_count=5),
            FakeDialog(MUTED_GROUP, date=NOW - timedelta(hours=4)),
            FakeDialog(FAMILY, date=NOW - timedelta(hours=5), archived=True),
            FakeDialog(FORUM, date=None),
        ],
    )
    return MockTelegramClient(dialogs=dialogs, **kwargs)


def _by_title(result):
    return {d.title: d for d in result.dialogs}


async def test_saved_messages_deleted_accounts_and_service_notifications_are_excluded():
    result = await list_dialogs(_client())
    titles = [d.title for d in result.dialogs]
    assert "Me" not in titles
    assert "Telegram" not in titles
    assert all(d.peer_id not in (100, 104, 777000) for d in result.dialogs)
    assert titles == [
        "Anna Petrova", "Boris", "Helper", "News", "Read-only channel", "Team",
        "Members can't write", "Family", "Forum",
    ]


async def test_types_categories_and_recipient_lines():
    dialogs = _by_title(await list_dialogs(_client()))
    anna, boris, bot = dialogs["Anna Petrova"], dialogs["Boris"], dialogs["Helper"]
    assert (anna.target_type, anna.is_bot, anna.category) == (TargetType.USER, False, DialogCategory.PEOPLE)
    assert (bot.target_type, bot.is_bot, bot.category) == (TargetType.USER, True, DialogCategory.BOTS)
    assert dialogs["News"].category is DialogCategory.CHANNELS
    for title in ("Team", "Family", "Forum"):
        assert dialogs[title].category is DialogCategory.GROUPS
    assert dialogs["Forum"].target_type is TargetType.FORUM
    assert dialogs["Family"].target_type is TargetType.GROUP

    # Users keep their positive id; chats the marked one.
    assert anna.peer_id == 101 and boris.peer_id == 102
    assert dialogs["Team"].peer_id == -1000000000203 and dialogs["Family"].peer_id == -205
    assert anna.recipient_line == "@anna_p"
    assert boris.recipient_line == "102"
    assert dialogs["Team"].recipient_line == "-1000000000203"
    # Whatever the picker writes back parses as the same addressee again.
    assert parse_recipient_line(boris.recipient_line).kind is RecipientKind.USER_ID
    assert parse_recipient_line(dialogs["Family"].recipient_line).is_chat_target


async def test_people_and_bots_are_writable_chats_go_through_preflight():
    dialogs = _by_title(await list_dialogs(_client()))
    for title in ("Anna Petrova", "Boris", "Helper", "News", "Team", "Family", "Forum"):
        assert dialogs[title].writable, title
        assert dialogs[title].unavailable_reason_key is None
    assert not dialogs["Read-only channel"].writable
    assert dialogs["Read-only channel"].unavailable_reason_key == "chat_targets.reason.channel_admin_required"
    assert dialogs["Members can't write"].unavailable_reason_key == "chat_targets.reason.write_forbidden"


async def test_forbidden_chat_is_listed_as_unavailable():
    gone = ChannelForbidden(id=300, access_hash=1, title="Gone channel", broadcast=True)
    result = await list_dialogs(_client(dialogs=[FakeDialog(gone, date=NOW)]))
    (dialog,) = result.dialogs
    assert dialog.unavailable_reason_key == "chat_targets.reason.no_access"


async def test_archive_flag_and_last_message_date():
    dialogs = _by_title(await list_dialogs(_client()))
    assert dialogs["Boris"].archived and dialogs["Family"].archived
    assert not dialogs["Anna Petrova"].archived
    assert dialogs["Anna Petrova"].last_message_date == NOW
    assert dialogs["Forum"].last_message_date is None


async def test_migrated_basic_group_is_left_out():
    old = make_fake_group(400, "Old group")
    old.migrated_to = InputPeerChannel(channel_id=203, access_hash=1)
    result = await list_dialogs(_client(dialogs=[FakeDialog(old), FakeDialog(TEAM)]))
    assert [d.title for d in result.dialogs] == ["Team"]


async def test_duplicate_dialogs_are_listed_once():
    result = await list_dialogs(_client(dialogs=[FakeDialog(TEAM), FakeDialog(TEAM)]))
    assert len(result.dialogs) == 1


# ---- folders ---------------------------------------------------------------------


def _folder(folder_id, title, **kwargs):
    return DialogFilter(
        id=folder_id,
        title=title,
        pinned_peers=kwargs.pop("pinned", []),
        include_peers=kwargs.pop("include", []),
        exclude_peers=kwargs.pop("exclude", []),
        **kwargs,
    )


def _members(result, folder_id):
    return sorted(d.title for d in result.dialogs if folder_id in d.folder_ids)


async def test_folders_are_listed_in_telegram_order_and_default_is_skipped():
    client = _client(dialog_filters=[DialogFilterDefault(), _folder(2, "Work"), _folder(5, "Home")])
    result = await list_dialogs(client)
    assert [(f.folder_id, f.title) for f in result.folders] == [(2, "Work"), (5, "Home")]


async def test_folder_explicit_peers():
    folder = _folder(
        2,
        "Work",
        pinned=[InputPeerChannel(channel_id=203, access_hash=1)],
        include=[InputPeerUser(user_id=102, access_hash=1), InputPeerChat(chat_id=205)],
    )
    result = await list_dialogs(_client(dialog_filters=[folder]))
    assert _members(result, 2) == ["Boris", "Family", "Team"]


async def test_folder_category_flags_and_exclusions():
    folders = [
        _folder(1, "Contacts", contacts=True),
        _folder(2, "Non-contacts", non_contacts=True),
        _folder(3, "Bots", bots=True),
        _folder(4, "Groups", groups=True, exclude=[InputPeerChannel(channel_id=206, access_hash=1)]),
        _folder(5, "Channels", broadcasts=True),
    ]
    result = await list_dialogs(_client(dialog_filters=folders))
    assert _members(result, 1) == ["Anna Petrova"]
    assert _members(result, 2) == ["Boris"]
    assert _members(result, 3) == ["Helper"]
    assert _members(result, 4) == ["Family", "Members can't write", "Team"]
    assert _members(result, 5) == ["News", "Read-only channel"]


async def test_folder_exclude_archived_read_and_muted():
    folders = [
        _folder(1, "Not archived", contacts=True, non_contacts=True, groups=True, exclude_archived=True),
        _folder(2, "Unread", contacts=True, groups=True, exclude_read=True),
        _folder(3, "Not muted", bots=True, non_contacts=True, exclude_muted=True),
        # An explicitly included chat stays in, whatever the exclusion flags say.
        _folder(4, "Pinned archive", exclude_archived=True, include=[InputPeerChat(chat_id=205)]),
    ]
    result = await list_dialogs(_client(dialog_filters=folders))
    assert "Boris" not in _members(result, 1) and "Family" not in _members(result, 1)
    assert "Anna Petrova" in _members(result, 1)
    assert _members(result, 2) == ["Anna Petrova", "Team"]
    assert _members(result, 3) == ["Boris"]
    assert _members(result, 4) == ["Family"]


async def test_shared_chatlist_folder_uses_its_peers():
    chatlist = DialogFilterChatlist(
        id=7, title="Shared", pinned_peers=[], include_peers=[InputPeerChannel(channel_id=201, access_hash=1)]
    )
    result = await list_dialogs(_client(dialog_filters=[chatlist]))
    assert [f.title for f in result.folders] == ["Shared"]
    assert _members(result, 7) == ["News"]


@pytest.mark.parametrize(
    "failure",
    [RPCError(request=None, message="FILTERS_UNAVAILABLE", code=400), make_flood_wait(60), ConnectionError("down")],
)
async def test_folder_failure_only_hides_folders(failure):
    client = _client(dialog_filters=failure)
    result = await list_dialogs(client)
    assert result.folders == ()
    assert all(not d.folder_ids for d in result.dialogs)
    assert len(result.dialogs) == 9
    # Asked once, never retried.
    assert sum(isinstance(r, GetDialogFiltersRequest) for r in client.raw_requests) == 1


async def test_flood_wait_on_dialogs_propagates():
    client = _client(dialogs_errors=[make_flood_wait(42)])
    with pytest.raises(FloodWaitError) as info:
        await list_dialogs(client)
    assert info.value.seconds == 42


async def test_only_dialogs_and_folders_are_read():
    client = _client(dialog_filters=[_folder(2, "Work", contacts=True)])
    await list_dialogs(client)
    assert client.dialogs_calls == 1
    assert all(isinstance(r, GetDialogFiltersRequest) for r in client.raw_requests)
    assert not any(isinstance(r, (ImportChatInviteRequest, JoinChannelRequest)) for r in client.raw_requests)
    assert client.get_entity_calls == 0


async def test_thousands_of_dialogs():
    dialogs = []
    for index in range(5000):
        if index % 3 == 0:
            entity = make_user(10_000 + index, f"Person {index}", username=f"person{index}")
        elif index % 3 == 1:
            entity = make_fake_channel(20_000 + index, f"Group {index}")
        else:
            entity = make_fake_channel(20_000 + index, f"Channel {index}", broadcast=True, creator=index % 2 == 0)
        dialogs.append(FakeDialog(entity, date=NOW - timedelta(minutes=index), archived=index % 10 == 0))
    folders = [_folder(1, "People", contacts=True, non_contacts=True), _folder(2, "Groups", groups=True)]
    started = time.perf_counter()
    result = await list_dialogs(MockTelegramClient(dialogs=dialogs, dialog_filters=folders))
    elapsed = time.perf_counter() - started
    assert len(result.dialogs) == 5000
    assert sum(1 for d in result.dialogs if 1 in d.folder_ids) == 1667
    assert elapsed < 2.0, elapsed
