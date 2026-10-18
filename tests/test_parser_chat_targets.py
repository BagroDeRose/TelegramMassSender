"""Parser tests for group/supergroup/channel target formats: marked chat
IDs (-100XXXXXXXXXX / -XXXXXXXXX), t.me/c/<id>[/<msg_id>] links, and
invite links (t.me/+hash, t.me/joinchat/hash) -- plus the CSV importer
picking them up through the very same recognizer, and mixed lists.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.recipients.csv_importer import import_recipients_from_csv
from app.recipients.importer import import_recipients_from_txt
from app.recipients.parser import RecipientKind, parse_recipient_line, parse_recipient_lines


@pytest.mark.parametrize(
    "raw,expected_kind,expected_value",
    [
        # Marked channel/supergroup ID (Bot API style, -100 prefix).
        ("-1001234567890", RecipientKind.CHAT_ID, "-1001234567890"),
        ("  -1001234567890  ", RecipientKind.CHAT_ID, "-1001234567890"),
        # Basic (legacy) group ID.
        ("-123456789", RecipientKind.CHAT_ID, "-123456789"),
        # t.me/c/<channel id> and t.me/c/<channel id>/<message id> both
        # point at the channel itself, -100<id>.
        ("https://t.me/c/1234567890", RecipientKind.CHAT_ID, "-1001234567890"),
        ("https://t.me/c/1234567890/42", RecipientKind.CHAT_ID, "-1001234567890"),
        ("t.me/c/1234567890/42/", RecipientKind.CHAT_ID, "-1001234567890"),
        ("http://t.me/c/1234567890?thread=7", RecipientKind.CHAT_ID, "-1001234567890"),
        # Invite links -- the hash is case-sensitive and kept verbatim.
        ("https://t.me/+AbCdEf_12-xyz", RecipientKind.INVITE_LINK, "AbCdEf_12-xyz"),
        ("t.me/+AbCdEf12xyz", RecipientKind.INVITE_LINK, "AbCdEf12xyz"),
        ("https://t.me/joinchat/AbCdEf12xyz", RecipientKind.INVITE_LINK, "AbCdEf12xyz"),
        ("http://t.me/joinchat/AbCdEf12xyz/", RecipientKind.INVITE_LINK, "AbCdEf12xyz"),
    ],
)
def test_chat_target_formats(raw, expected_kind, expected_value):
    result = parse_recipient_line(raw)
    assert result.is_valid, result.error
    assert result.kind == expected_kind
    assert result.value == expected_value
    assert result.is_chat_target


@pytest.mark.parametrize(
    "raw",
    [
        "-",
        "-0",
        "-000",
        "--100123",
        "-12a34",
        "- 100123",
        "https://t.me/c/",
        "https://t.me/c/abc",
        "https://t.me/c/0",
        "https://t.me/c/123/abc",
        "https://t.me/+",
        "https://t.me/joinchat/",
        "https://t.me/+abc def",
        "https://t.me/+abc$%",
    ],
)
def test_invalid_chat_target_formats(raw):
    result = parse_recipient_line(raw)
    assert not result.is_valid
    assert result.error


def test_positive_number_is_still_a_user_id():
    result = parse_recipient_line("1234567890")
    assert result.kind == RecipientKind.USER_ID
    assert result.value == "1234567890"
    assert not result.is_chat_target


def test_username_and_public_link_are_not_classified_as_chat_at_parse_time():
    # @username / t.me/username may be a user *or* a chat -- only
    # resolving it tells which, so the parser must not pre-classify it.
    for raw in ("@some_channel", "https://t.me/some_channel"):
        result = parse_recipient_line(raw)
        assert result.kind == RecipientKind.USERNAME
        assert not result.is_chat_target


def test_chat_keys_never_collide_with_user_keys():
    user = parse_recipient_line("123456789")
    group = parse_recipient_line("-123456789")
    assert user.normalized_key != group.normalized_key


def test_tme_c_link_and_marked_id_dedupe_to_one_target():
    summary = parse_recipient_lines(
        ["-1001234567890", "https://t.me/c/1234567890/5", "t.me/c/1234567890"]
    )
    assert len(summary.valid_recipients) == 1
    assert summary.duplicates_removed == 2


def test_invite_hash_dedupe_is_case_sensitive_and_format_independent():
    summary = parse_recipient_lines(
        ["https://t.me/+AbCdEf12xyz", "https://t.me/joinchat/AbCdEf12xyz", "https://t.me/+abcdef12xyz"]
    )
    # joinchat/<hash> and +<hash> are the same invite; a different-case
    # hash is a different invite.
    assert len(summary.valid_recipients) == 2
    assert summary.duplicates_removed == 1


def test_display_labels():
    assert parse_recipient_line("-1001234567890").display_label == "-1001234567890"
    assert parse_recipient_line("https://t.me/c/1234567890/9").display_label == "-1001234567890"
    assert parse_recipient_line("https://t.me/joinchat/AbC123").display_label == "t.me/+AbC123"


def test_mixed_list_of_people_and_chats():
    summary = parse_recipient_lines(
        [
            "@ivan_petrov",
            "123456789",
            "+4917612345678",
            "-1001234567890",
            "-987654321",
            "https://t.me/c/2222222222/1",
            "https://t.me/+InviteHash1",
            "https://t.me/news_channel",
            "garbage!!",
        ]
    )
    kinds = [p.kind for p in summary.valid_recipients]
    assert kinds == [
        RecipientKind.USERNAME,
        RecipientKind.USER_ID,
        RecipientKind.PHONE,
        RecipientKind.CHAT_ID,
        RecipientKind.CHAT_ID,
        RecipientKind.CHAT_ID,
        RecipientKind.INVITE_LINK,
        RecipientKind.USERNAME,
    ]
    assert summary.invalid_count == 1
    assert sum(p.is_chat_target for p in summary.valid_recipients) == 4


def test_txt_import_accepts_chat_targets(tmp_path: Path):
    path = tmp_path / "list.txt"
    path.write_text("@ivan_petrov\n-1001234567890\nhttps://t.me/+InviteHash1\n", encoding="utf-8")
    summary = import_recipients_from_txt(path)
    assert [p.kind for p in summary.valid_recipients] == [
        RecipientKind.USERNAME,
        RecipientKind.CHAT_ID,
        RecipientKind.INVITE_LINK,
    ]


def test_csv_import_detects_chat_targets_through_the_same_recognizer(tmp_path: Path):
    path = tmp_path / "list.csv"
    path.write_text(
        "Team chat,-1001234567890\n"
        "https://t.me/c/2222222222/7,Announcements\n"
        "Ivan,@ivan_petrov\n"
        "Club,https://t.me/+InviteHash1\n",
        encoding="utf-8-sig",
    )
    result = import_recipients_from_csv(path)
    assert [p.kind for p in result.valid_recipients] == [
        RecipientKind.CHAT_ID,
        RecipientKind.CHAT_ID,
        RecipientKind.USERNAME,
        RecipientKind.INVITE_LINK,
    ]
    assert result.names == {
        "id:-1001234567890": "Team chat",
        "id:-1002222222222": "Announcements",
        "username:ivan_petrov": "Ivan",
        "invite:InviteHash1": "Club",
    }
