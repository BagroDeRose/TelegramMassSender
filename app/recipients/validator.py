"""Pure, offline format validation helpers for recipient identifiers.

For full validation against Telegram (does the user exist, can they be
messaged) see app.telegram.recipient_resolver -- that requires a live
connection and must not be conflated with the cheap, offline format
checks here, which are what the UI runs on every keystroke/paste.
"""
from __future__ import annotations

from app.recipients.parser import ParsedRecipient, parse_recipient_line


def is_valid_format(raw_line: str) -> bool:
    return parse_recipient_line(raw_line).is_valid


def validate_single_recipient(raw_line: str) -> ParsedRecipient:
    """Used by the test-send input field: parse and format-validate one
    recipient without touching the network."""
    return parse_recipient_line(raw_line)
