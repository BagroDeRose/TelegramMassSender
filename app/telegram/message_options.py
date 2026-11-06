"""How one message is sent, beyond its text and files: the order of text
and media when the text can't be a caption, and the link preview.

Saved with a template (app.campaign.presets) and in a campaign's snapshot
(the same snapshot Retry reuses). Pure data, no Qt and no network --
app.telegram.media_sender turns it into the send plan that both the
sender and the preview use.

Lengths are counted the way Telegram counts them: in UTF-16 code units
(an emoji outside the BMP is two), the same units as entity offsets.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

from telethon.helpers import add_surrogate, del_surrogate
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl, TypeMessageEntity

# Telegram's caption limit for a non-Premium account (help.getAppConfig
# "caption_length_limit_default"); used whenever the account's own limit
# isn't known.
DEFAULT_CAPTION_LIMIT = 1024


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class MediaTextOrder(Enum):
    """When the text is too long for a caption and goes as its own message."""

    TEXT_FIRST = "text_first"  # the behaviour before this option existed
    MEDIA_FIRST = "media_first"


class PreviewSize(Enum):
    AUTO = "auto"  # whatever Telegram picks for the page
    LARGE = "large"
    SMALL = "small"


@dataclass(frozen=True)
class LinkPreviewOptions:
    """`url` None means no preview at all (the default: in a mass send the
    message should look the same for everyone, not depend on which link
    Telegram happens to pick)."""

    url: Optional[str] = None
    above_text: bool = False
    size: PreviewSize = PreviewSize.AUTO

    @property
    def enabled(self) -> bool:
        return self.url is not None


@dataclass(frozen=True)
class MessageOptions:
    order: MediaTextOrder = MediaTextOrder.TEXT_FIRST
    link_preview: LinkPreviewOptions = field(default_factory=LinkPreviewOptions)

    def to_json(self) -> str:
        return json.dumps(
            {
                "order": self.order.value,
                "link_preview": {
                    "url": self.link_preview.url,
                    "above_text": self.link_preview.above_text,
                    "size": self.link_preview.size.value,
                },
            }
        )

    @classmethod
    def from_json(cls, raw: Optional[str]) -> "MessageOptions":
        """Tolerant: missing, empty or unreadable data (a template saved
        before these options existed) is the defaults -- no preview."""
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        preview = data.get("link_preview") if isinstance(data.get("link_preview"), dict) else {}
        url = preview.get("url")
        return cls(
            order=_enum(MediaTextOrder, data.get("order"), MediaTextOrder.TEXT_FIRST),
            link_preview=LinkPreviewOptions(
                url=url if isinstance(url, str) and url else None,
                above_text=bool(preview.get("above_text", False)),
                size=_enum(PreviewSize, preview.get("size"), PreviewSize.AUTO),
            ),
        )


def _enum(enum_type, value, default):
    try:
        return enum_type(value)
    except ValueError:
        return default


# ---- links -------------------------------------------------------------------------

@dataclass(frozen=True)
class MessageLink:
    url: str  # normalized: always with a scheme
    label: str  # what the reader sees: the URL itself, or the linked text
    domain: str


# A URL with a scheme, a "www." address, or a bare domain with a path or a
# known Telegram host. Bare "name.ext" without a path is left out: file
# names and version numbers ("report.txt", "2.1.1") aren't links.
_URL_RE = re.compile(
    r"(?<![\w@.])("
    r"https?://[^\s<>\"']+"
    r"|www\.[^\s<>\"']+"
    r"|(?:t\.me|telegram\.me|telegram\.dog)/[^\s<>\"']+"
    r"|(?:[a-z0-9-]+\.)+[a-z]{2,24}/[^\s<>\"']*"
    r")",
    re.IGNORECASE,
)
_TRAILING_PUNCTUATION = ".,;:!?)]}»\"'"


def normalize_url(raw: str) -> str:
    url = raw.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE):
        url = "https://" + url
    parts = urlsplit(url)
    return parts._replace(scheme=parts.scheme.lower(), netloc=parts.netloc.lower()).geturl()


def link_domain(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def find_links(text: str, entities: Iterable[TypeMessageEntity]) -> List[MessageLink]:
    """Every link in the message, in the order it appears: links under
    text ("Алсу" -> t.me/...), URL entities and URLs written in the text
    itself. The same address twice is listed once."""
    surrogate = add_surrogate(text or "")
    found = []  # (position, MessageLink)
    for entity in entities or ():
        if isinstance(entity, MessageEntityTextUrl) and entity.url:
            label = del_surrogate(surrogate[entity.offset : entity.offset + entity.length])
            found.append((entity.offset, entity.url, label))
        elif isinstance(entity, MessageEntityUrl):
            raw = del_surrogate(surrogate[entity.offset : entity.offset + entity.length])
            found.append((entity.offset, raw, raw))
    for match in _URL_RE.finditer(text or ""):
        raw = match.group(1).rstrip(_TRAILING_PUNCTUATION)
        if not raw:
            continue
        position = utf16_len((text or "")[: match.start(1)])
        found.append((position, raw, raw))

    links: List[MessageLink] = []
    seen = set()
    for _position, raw, label in sorted(found, key=lambda item: item[0]):
        url = normalize_url(raw)
        if url in seen:
            continue
        seen.add(url)
        links.append(MessageLink(url=url, label=label, domain=link_domain(url)))
    return links


def effective_link_preview(
    text: str, entities: Iterable[TypeMessageEntity], options: Optional[MessageOptions]
) -> Optional[LinkPreviewOptions]:
    """The preview a text message actually gets: none unless one was
    chosen and that link is still in the text."""
    preview = (options or MessageOptions()).link_preview
    if not preview.enabled:
        return None
    if preview.url not in {link.url for link in find_links(text, entities)}:
        return None
    return preview
