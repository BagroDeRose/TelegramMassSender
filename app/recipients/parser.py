"""Parsing of raw recipient identifiers into a normalized form.

Supports exactly the formats from spec items 12-14: @username, a numeric
Telegram ID, and t.me URLs (https://t.me/x, http://t.me/x, t.me/x).
Resolving a parsed identifier into an actual Telegram entity (and
rejecting groups/channels) is a separate, network-bound concern -- see
app.telegram.recipient_resolver.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional, Tuple

from app.i18n import tr

_USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{3,31}$")
_TME_URL_RE = re.compile(r"^(?:https?://)?t\.me/([a-zA-Z0-9_]{4,32})/?$", re.IGNORECASE)
# E.164: leading '+', 8-15 digits total, first digit non-zero. Deliberately
# strict -- a local-format number (no '+') is rejected rather than guessed,
# since guessing a country code would silently target the wrong person.
_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class RecipientKind(Enum):
    USERNAME = "username"
    USER_ID = "user_id"
    PHONE = "phone"


@dataclass(frozen=True)
class ParsedRecipient:
    raw: str
    kind: Optional[RecipientKind]
    value: Optional[str]  # normalized username (no '@') or numeric id as string
    is_valid: bool
    error: Optional[str] = None

    @property
    def normalized_key(self) -> Optional[str]:
        """Key used for de-duplication and resolver caching; None if invalid."""
        if not self.is_valid:
            return None
        if self.kind == RecipientKind.USERNAME:
            return f"username:{self.value.lower()}"
        if self.kind == RecipientKind.PHONE:
            return f"phone:{self.value}"
        return f"id:{self.value}"

    @property
    def display_label(self) -> str:
        if self.kind == RecipientKind.USERNAME:
            return f"@{self.value}"
        if self.kind == RecipientKind.USER_ID:
            return str(self.value)
        if self.kind == RecipientKind.PHONE:
            return f"+{self.value}"
        return self.raw.strip()


def parse_recipient_line(raw_line: str) -> ParsedRecipient:
    text = raw_line.strip()
    if not text:
        return ParsedRecipient(raw=raw_line, kind=None, value=None, is_valid=False, error=tr("recipients.parser.error.empty_line"))

    if text.startswith("+"):
        if _PHONE_RE.match(text):
            return ParsedRecipient(raw=raw_line, kind=RecipientKind.PHONE, value=text[1:], is_valid=True)
        return ParsedRecipient(
            raw=raw_line,
            kind=None,
            value=None,
            is_valid=False,
            error=tr("recipients.parser.error.invalid_phone"),
        )

    if text.isdigit():
        return ParsedRecipient(raw=raw_line, kind=RecipientKind.USER_ID, value=text, is_valid=True)

    match = _TME_URL_RE.match(text)
    if match:
        username = match.group(1)
        if _USERNAME_RE.match(username):
            return ParsedRecipient(raw=raw_line, kind=RecipientKind.USERNAME, value=username, is_valid=True)
        return ParsedRecipient(
            raw=raw_line, kind=None, value=None, is_valid=False, error=tr("recipients.parser.error.invalid_tme_link")
        )

    if text.startswith("@"):
        candidate = text[1:]
        if _USERNAME_RE.match(candidate):
            return ParsedRecipient(raw=raw_line, kind=RecipientKind.USERNAME, value=candidate, is_valid=True)
        return ParsedRecipient(
            raw=raw_line, kind=None, value=None, is_valid=False, error=tr("recipients.parser.error.invalid_username")
        )

    return ParsedRecipient(
        raw=raw_line, kind=None, value=None, is_valid=False, error=tr("recipients.parser.error.unknown_format")
    )


@dataclass
class ParseSummary:
    parsed: List[ParsedRecipient] = field(default_factory=list)
    total_lines: int = 0
    duplicates_removed: int = 0
    invalid_count: int = 0

    @property
    def valid_recipients(self) -> List[ParsedRecipient]:
        return [p for p in self.parsed if p.is_valid]

    @property
    def total_recipients(self) -> int:
        return len(self.parsed)


def dedupe_recipients(parsed: List[ParsedRecipient]) -> Tuple[List[ParsedRecipient], int]:
    """Drop recipients that duplicate an earlier *valid* entry's
    normalized_key, keeping the first occurrence and every invalid entry
    unchanged (an invalid entry has no normalized_key, so it can never be
    a duplicate of anything). Shared by parse_recipient_lines below and
    app.recipients.csv_importer, so there is exactly one definition of
    "duplicate" for both import paths."""
    seen_keys: set[str] = set()
    deduped: List[ParsedRecipient] = []
    duplicates_removed = 0
    for item in parsed:
        if item.is_valid:
            key = item.normalized_key
            if key in seen_keys:
                duplicates_removed += 1
                continue
            seen_keys.add(key)
        deduped.append(item)
    return deduped, duplicates_removed


def parse_recipient_lines(lines: Iterable[str]) -> ParseSummary:
    """Parse an iterable of raw lines (e.g. an open file, or text.splitlines()).

    Blank lines are silently skipped (not counted, not reported as errors).
    Whitespace around each line is stripped. Duplicates (by normalized
    identity) are dropped, keeping the first occurrence.
    """
    parsed: List[ParsedRecipient] = []
    invalid_count = 0
    total_lines = 0

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        total_lines += 1
        result = parse_recipient_line(raw_line)
        if not result.is_valid:
            invalid_count += 1
        parsed.append(result)

    deduped, duplicates_removed = dedupe_recipients(parsed)
    return ParseSummary(
        parsed=deduped,
        total_lines=total_lines,
        duplicates_removed=duplicates_removed,
        invalid_count=invalid_count,
    )
