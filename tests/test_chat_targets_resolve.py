"""Resolving group/supergroup/channel targets (app.telegram.recipient_resolver)
and the pure permission preflight / error mapping (app.telegram.chat_targets),
all against MockTelegramClient's real Telethon Chat/Channel entities.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatSendMediaForbiddenError,
    ChatWriteForbiddenError,
    FloodWaitError,
    UserBannedInChannelError,
)
from telethon.errors import rpc_message_to_error
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
from telethon.tl.types import ChannelForbidden, ChatBannedRights

from app.recipients.parser import parse_recipient_line
from app.telegram.chat_targets import (
    SendRequirements,
    TargetType,
    chat_error_reason_key,
    check_send_rights,
    list_dialogs,
    send_requirements,
    target_type_of,
)
from app.telegram.media_sender import Attachment, AttachmentKind
from app.telegram.recipient_resolver import RecipientResolver, ResolveStatus
from tests.mocks.mock_telegram_client import (
    MockTelegramClient,
    admin_rights,
    banned_rights,
    make_fake_channel,
    make_fake_group,
    make_fake_user,
    make_flood_wait,
    make_user,
)

TEXT = SendRequirements(has_plain_text_message=True, message_count=1)
PHOTO = SendRequirements(media_kinds=frozenset({AttachmentKind.PHOTO}), message_count=1)


def _no_join_requests(client: MockTelegramClient) -> bool:
    return not any(isinstance(r, (ImportChatInviteRequest, JoinChannelRequest)) for r in client.raw_requests)


# ---- type detection --------------------------------------------------------------


def test_target_types():
    assert target_type_of(make_fake_user("ivan")) is TargetType.USER
    assert target_type_of(make_fake_group(5, "G")) is TargetType.GROUP
    assert target_type_of(make_fake_channel(6, "S")) is TargetType.SUPERGROUP
    assert target_type_of(make_fake_channel(7, "F", forum=True)) is TargetType.FORUM
    assert target_type_of(make_fake_channel(8, "C", broadcast=True)) is TargetType.CHANNEL
    assert target_type_of(object()) is None


# ---- resolving -------------------------------------------------------------------


async def test_username_resolving_to_channel_is_a_chat_target():
    channel = make_fake_channel(100, "News", username="news_channel", broadcast=True, creator=True)
    client = MockTelegramClient(chats={"news_channel": channel})
    result = await RecipientResolver(client).resolve(parse_recipient_line("@news_channel"))
    assert result.status == ResolveStatus.READY
    assert result.target_type is TargetType.CHANNEL
    assert result.entity is channel


async def test_username_resolving_to_user_is_unchanged():
    client = MockTelegramClient(entity_behavior={"ivan_petrov": "found"})
    result = await RecipientResolver(client).resolve(parse_recipient_line("@ivan_petrov"))
    assert result.status == ResolveStatus.READY
    assert result.target_type is TargetType.USER
    assert not result.is_chat
    assert client.dialogs_calls == 0, "a user-only resolve must never fetch dialogs"


async def test_chat_id_resolves_after_warming_dialogs_once():
    group = make_fake_channel(1234567890, "Team", default_banned=None)
    basic = make_fake_group(987654321, "Family")
    client = MockTelegramClient(
        chats={-1001234567890: group, -987654321: basic},
        dialogs=[make_fake_user("someone"), group, basic],
    )
    resolver = RecipientResolver(client)

    first = await resolver.resolve(parse_recipient_line("-1001234567890"))
    second = await resolver.resolve(parse_recipient_line("https://t.me/c/1234567890/77"))  # same chat, cached key
    third = await resolver.resolve(parse_recipient_line("-987654321"))

    assert first.status == ResolveStatus.READY and first.target_type is TargetType.SUPERGROUP
    assert second.entity is group
    assert third.status == ResolveStatus.READY and third.target_type is TargetType.GROUP
    assert client.dialogs_calls == 1, "dialogs must be fetched exactly once per campaign"


async def test_chat_id_without_dialog_warmup_would_not_resolve():
    # Demonstrates why the warm-up exists: Telethon can't turn a bare
    # marked id into an entity before it has seen the dialogs.
    group = make_fake_channel(1234567890, "Team")
    client = MockTelegramClient(chats={-1001234567890: group})
    with pytest.raises(ValueError):
        await client.get_entity(-1001234567890)


async def test_chat_id_not_in_dialogs_means_not_a_member():
    client = MockTelegramClient(dialogs=[make_fake_channel(1, "Other")])
    result = await RecipientResolver(client).resolve(parse_recipient_line("-1009999999999"))
    assert result.status == ResolveStatus.NOT_MEMBER
    assert result.error


async def test_dialog_warmup_flood_wait_propagates_and_is_retried():
    group = make_fake_channel(1234567890, "Team")
    client = MockTelegramClient(dialogs=[group], dialogs_errors=[make_flood_wait(42)])
    resolver = RecipientResolver(client)
    parsed = parse_recipient_line("-1001234567890")

    with pytest.raises(FloodWaitError):
        await resolver.resolve(parsed)
    assert not resolver.dialogs_loaded

    result = await resolver.resolve(parsed)
    assert result.status == ResolveStatus.READY
    assert client.dialogs_calls == 2


async def test_invite_link_for_chat_the_account_is_in():
    group = make_fake_channel(55, "Club")
    client = MockTelegramClient(invite_behavior={"InviteHash1": group})
    result = await RecipientResolver(client).resolve(parse_recipient_line("https://t.me/+InviteHash1"))
    assert result.status == ResolveStatus.READY
    assert result.entity is group
    assert any(isinstance(r, CheckChatInviteRequest) for r in client.raw_requests)
    assert _no_join_requests(client)


@pytest.mark.parametrize("behavior", ["not_member", "peek"])
async def test_invite_link_for_chat_the_account_is_not_in_fails_without_joining(behavior):
    client = MockTelegramClient(invite_behavior={"InviteHash1": behavior})
    result = await RecipientResolver(client).resolve(parse_recipient_line("https://t.me/joinchat/InviteHash1"))
    assert result.status == ResolveStatus.NOT_MEMBER
    assert result.error == "аккаунт не состоит в этом чате" or result.error == "the account is not a member of this chat"
    assert _no_join_requests(client), "an invite link must never be joined automatically"


@pytest.mark.parametrize("behavior", ["expired", "invalid"])
async def test_invalid_invite_link(behavior):
    client = MockTelegramClient(invite_behavior={"InviteHash1": behavior})
    result = await RecipientResolver(client).resolve(parse_recipient_line("https://t.me/+InviteHash1"))
    assert result.status == ResolveStatus.INVITE_INVALID


async def test_invite_flood_wait_propagates():
    client = MockTelegramClient(invite_behavior={"InviteHash1": make_flood_wait(10)})
    with pytest.raises(FloodWaitError):
        await RecipientResolver(client).resolve(parse_recipient_line("https://t.me/+InviteHash1"))


async def test_private_channel_error_on_resolve_is_a_readable_reason():
    client = MockTelegramClient()

    async def private(identifier):
        raise ChannelPrivateError(request=None)

    client.get_entity = private  # type: ignore[method-assign]
    result = await RecipientResolver(client).resolve(parse_recipient_line("@secret_channel"))
    assert result.status == ResolveStatus.NO_ACCESS
    assert "ChannelPrivate" not in (result.error or "")


async def test_channel_forbidden_entity_is_ready_but_preflight_refuses():
    forbidden = ChannelForbidden(id=77, access_hash=1, title="Gone", broadcast=True)
    client = MockTelegramClient(chats={"gone_channel": forbidden})
    result = await RecipientResolver(client).resolve(parse_recipient_line("@gone_channel"))
    assert result.status == ResolveStatus.READY
    assert check_send_rights(result.entity, TEXT) == "chat_targets.reason.no_access"


# ---- preflight -------------------------------------------------------------------


def test_channel_without_admin_rights_is_refused():
    channel = make_fake_channel(1, "News", broadcast=True)
    assert check_send_rights(channel, TEXT) == "chat_targets.reason.channel_admin_required"


def test_channel_admin_without_post_messages_is_refused():
    channel = make_fake_channel(1, "News", broadcast=True, admin=admin_rights(edit_messages=True))
    assert check_send_rights(channel, TEXT) == "chat_targets.reason.channel_admin_required"


def test_channel_creator_or_posting_admin_is_allowed():
    assert check_send_rights(make_fake_channel(1, "N", broadcast=True, creator=True), PHOTO) is None
    assert check_send_rights(make_fake_channel(1, "N", broadcast=True, admin=admin_rights(post_messages=True)), PHOTO) is None


def test_group_with_writing_disabled_for_members():
    group = make_fake_channel(1, "G", default_banned=banned_rights(send_messages=True))
    assert check_send_rights(group, TEXT) == "chat_targets.reason.write_forbidden"
    basic = make_fake_group(2, "B", default_banned=banned_rights(send_messages=True))
    assert check_send_rights(basic, TEXT) == "chat_targets.reason.write_forbidden"


def test_group_with_personal_restriction():
    group = make_fake_channel(1, "G", banned=banned_rights(send_messages=True))
    assert check_send_rights(group, TEXT) == "chat_targets.reason.write_forbidden_personal"
    banned = make_fake_channel(1, "G", banned=banned_rights(view_messages=True))
    assert check_send_rights(banned, TEXT) == "chat_targets.reason.banned"


def test_expired_personal_restriction_is_ignored():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    group = make_fake_channel(1, "G", banned=ChatBannedRights(until_date=past, send_messages=True))
    assert check_send_rights(group, TEXT) is None


def test_group_admin_is_not_bound_by_member_restrictions():
    group = make_fake_channel(
        1, "G", admin=admin_rights(delete_messages=True), default_banned=banned_rights(send_messages=True, send_media=True)
    )
    assert check_send_rights(group, PHOTO) is None


def test_media_forbidden_only_matters_with_attachments():
    group = make_fake_channel(1, "G", default_banned=banned_rights(send_media=True))
    assert check_send_rights(group, TEXT) is None
    assert check_send_rights(group, PHOTO) == "chat_targets.reason.media_forbidden"


@pytest.mark.parametrize(
    "flag,kind",
    [
        ("send_photos", AttachmentKind.PHOTO),
        ("send_videos", AttachmentKind.VIDEO),
        ("send_docs", AttachmentKind.DOCUMENT),
        ("send_audios", AttachmentKind.AUDIO),
        ("send_gifs", AttachmentKind.ANIMATION),
    ],
)
def test_granular_media_rights(flag, kind):
    group = make_fake_channel(1, "G", default_banned=banned_rights(**{flag: True}))
    req = SendRequirements(media_kinds=frozenset({kind}), message_count=1)
    assert check_send_rights(group, req) == "chat_targets.reason.media_forbidden"


def test_granular_media_right_only_blocks_its_own_kind():
    photos_banned = make_fake_channel(1, "G", default_banned=banned_rights(send_photos=True))
    document = SendRequirements(media_kinds=frozenset({AttachmentKind.DOCUMENT}), message_count=1)
    assert check_send_rights(photos_banned, document) is None


def test_plain_text_forbidden():
    group = make_fake_channel(1, "G", default_banned=banned_rights(send_plain=True))
    assert check_send_rights(group, TEXT) == "chat_targets.reason.plain_forbidden"
    # A short caption on media is not a standalone text message.
    assert check_send_rights(group, PHOTO) is None


def test_not_member_and_migrated():
    assert check_send_rights(make_fake_channel(1, "G", left=True), TEXT) == "chat_targets.reason.not_member"
    assert check_send_rights(make_fake_group(2, "B", deactivated=True), TEXT) == "chat_targets.reason.deactivated"


def test_slow_mode_blocks_multi_part_messages_up_front():
    group = make_fake_channel(1, "G", slowmode_enabled=True)
    assert check_send_rights(group, TEXT) is None
    two_parts = SendRequirements(has_plain_text_message=True, media_kinds=frozenset({AttachmentKind.PHOTO}), message_count=2)
    assert check_send_rights(group, two_parts) == "chat_targets.reason.slowmode_multi"


def test_users_are_never_preflighted():
    assert check_send_rights(make_fake_user("ivan"), PHOTO) is None


def test_send_requirements_mirror_the_send_plan(tmp_path):
    photo = tmp_path / "a.jpg"
    photo.write_bytes(b"x")
    doc = tmp_path / "b.pdf"
    doc.write_bytes(b"x")
    assert send_requirements("hi", []) == SendRequirements(has_plain_text_message=True, message_count=1)
    req = send_requirements("hi", [Attachment(photo), Attachment(doc)])
    assert req.has_plain_text_message is False  # becomes a caption
    assert req.media_kinds == frozenset({AttachmentKind.PHOTO, AttachmentKind.DOCUMENT})
    assert req.message_count == 2
    long_req = send_requirements("x" * 2000, [Attachment(photo)])
    assert long_req.has_plain_text_message is True and long_req.message_count == 2


# ---- error mapping ---------------------------------------------------------------


@pytest.mark.parametrize(
    "exc,key",
    [
        (ChatWriteForbiddenError(request=None), "chat_targets.reason.write_forbidden"),
        (ChatAdminRequiredError(request=None), "chat_targets.reason.channel_admin_required"),
        (ChannelPrivateError(request=None), "chat_targets.reason.private"),
        (UserBannedInChannelError(request=None), "chat_targets.reason.account_restricted"),
        (ChatSendMediaForbiddenError(request=None), "chat_targets.reason.media_forbidden"),
    ],
)
def test_error_mapping_by_type(exc, key):
    assert chat_error_reason_key(exc) == key


@pytest.mark.parametrize(
    "code,message,key",
    [
        (400, "TOPIC_CLOSED", "chat_targets.reason.forum_general_closed"),
        (403, "CHAT_SEND_PHOTOS_FORBIDDEN", "chat_targets.reason.media_forbidden"),
        (403, "CHAT_SEND_PLAIN_FORBIDDEN", "chat_targets.reason.plain_forbidden"),
        (403, "ALLOW_PAYMENT_REQUIRED_10", "chat_targets.reason.paid_messages"),
    ],
)
def test_error_mapping_by_message_code(code, message, key):
    rpc = type("RpcError", (), {"error_code": code, "error_message": message})()
    assert chat_error_reason_key(rpc_message_to_error(rpc, None)) == key


def test_unrelated_error_is_not_mapped():
    assert chat_error_reason_key(ValueError("boom")) is None


# ---- "From my chats…" ------------------------------------------------------------


async def test_list_dialogs_marks_unwritable_chats_and_keeps_users():
    client = MockTelegramClient(
        dialogs=[
            make_user(55, "Friend", username="friend"),
            make_fake_channel(1, "My channel", username="my_channel", broadcast=True, creator=True),
            make_fake_channel(2, "Read-only channel", broadcast=True),
            make_fake_channel(3, "Team", default_banned=None),
            make_fake_channel(4, "Muted group", default_banned=banned_rights(send_messages=True)),
            make_fake_group(5, "Family"),
            make_fake_channel(6, "Forum", forum=True),
        ]
    )
    dialogs = (await list_dialogs(client)).dialogs
    assert dialogs[0].target_type is TargetType.USER and dialogs[0].writable
    assert [(d.title, d.writable) for d in dialogs[1:]] == [
        ("My channel", True),
        ("Read-only channel", False),
        ("Team", True),
        ("Muted group", False),
        ("Family", True),
        ("Forum", True),
    ]
    chats = [d for d in dialogs if d.target_type.is_chat and d.writable]
    assert [c.target_type for c in chats] == [
        TargetType.CHANNEL, TargetType.SUPERGROUP, TargetType.GROUP, TargetType.FORUM,
    ]
    assert [c.recipient_line for c in chats] == ["@my_channel", "-1000000000003", "-5", "-1000000000006"]
    # Every line the picker writes back parses as a chat target again.
    for chat in chats[1:]:
        parsed = parse_recipient_line(chat.recipient_line)
        assert parsed.is_chat_target and int(parsed.value) == chat.peer_id
