"""Recipient parser tests (spec item 58): @username, numeric ID, t.me
URLs, duplicates, empty lines, invalid values."""
from __future__ import annotations

import pytest

from app.recipients.parser import RecipientKind, parse_recipient_line, parse_recipient_lines
from app.recipients.validator import is_valid_format


@pytest.mark.parametrize(
    "raw,expected_kind,expected_value",
    [
        ("@ivan_petrov", RecipientKind.USERNAME, "ivan_petrov"),
        ("123456789", RecipientKind.USER_ID, "123456789"),
        ("https://t.me/username3", RecipientKind.USERNAME, "username3"),
        ("http://t.me/username4", RecipientKind.USERNAME, "username4"),
        ("t.me/username5", RecipientKind.USERNAME, "username5"),
        ("  @spaced_user  ", RecipientKind.USERNAME, "spaced_user"),
        ("+4917612345678", RecipientKind.PHONE, "4917612345678"),
        ("+14155552671", RecipientKind.PHONE, "14155552671"),
        ("  +4917612345678  ", RecipientKind.PHONE, "4917612345678"),
    ],
)
def test_valid_formats(raw, expected_kind, expected_value):
    result = parse_recipient_line(raw)
    assert result.is_valid
    assert result.kind == expected_kind
    assert result.value == expected_value


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not valid!!",
        "@ab",
        "###bad###",
        "bareword",
        # Note: a local-format number with no '+' (e.g. "017612345678") is
        # NOT rejected at parse time -- it's an all-digit string, so it's
        # classified as RecipientKind.USER_ID (pre-existing behavior,
        # unrelated to phone parsing) and simply fails at resolution time
        # as an invalid/unknown ID, never guessed as a phone number.
        "123-456-789",  # separators, no '+'
        "+0491761234",  # leading zero after '+' is not a valid country code
        "+123",  # too short to be a real E.164 number
        "+1234567890123456",  # too long (>15 digits)
        "+49176abcde",  # non-digit characters
    ],
)
def test_invalid_formats(raw):
    result = parse_recipient_line(raw)
    assert not result.is_valid
    assert result.error


def test_phone_display_label_and_normalized_key():
    result = parse_recipient_line("+4917612345678")
    assert result.display_label == "+4917612345678"
    assert result.normalized_key == "phone:4917612345678"


def test_mixed_recipient_list_all_kinds_recognized():
    summary = parse_recipient_lines(
        [
            "@alice",
            "123456789",
            "+4917612345678",
            "https://t.me/bobby",
        ]
    )
    kinds = [p.kind for p in summary.valid_recipients]
    assert kinds == [
        RecipientKind.USERNAME,
        RecipientKind.USER_ID,
        RecipientKind.PHONE,
        RecipientKind.USERNAME,
    ]
    assert summary.invalid_count == 0


def test_dedup_and_counts():
    lines = [
        "@user1",
        "@user2",
        "123456789",
        "https://t.me/user3",
        "t.me/user4",
        "@user1",  # duplicate
        "",
        "   ",
        "###invalid###",
        "@ab",  # too short
    ]
    summary = parse_recipient_lines(lines)
    assert summary.duplicates_removed == 1
    assert summary.invalid_count == 2
    assert len(summary.valid_recipients) == 5
    assert summary.total_lines == 8  # blank lines excluded


def test_validator_matches_parser():
    assert is_valid_format("@ok_user") is True
    assert is_valid_format("garbage!!!") is False
