"""What the app asks Telegram about, besides sending: the account's caption
limit and link-preview cards. Read-only, cached for the session, and never
fatal -- a failure (offline, FloodWait) only means the defaults.

- Caption limit: help.getAppConfig's caption_length_limit_default /
  caption_length_limit_premium, chosen by the account's Premium flag;
  DEFAULT_CAPTION_LIMIT (1024) when it can't be read.
- Link preview: messages.getWebPagePreview for one URL -- site name, title,
  description and whether the page has a large image. Nothing is
  downloaded (no photos).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Hashable, Optional

from telethon.tl.functions.help import GetAppConfigRequest
from telethon.tl.functions.messages import GetWebPagePreviewRequest
from telethon.tl.types import JsonObject, MessageMediaWebPage, WebPage

from app.logging.logger import get_logger
from app.telegram.message_options import DEFAULT_CAPTION_LIMIT

logger = get_logger()


def _config_number(config: Any, key: str) -> Optional[int]:
    if not isinstance(config, JsonObject):
        return None
    for item in config.value:
        if item.key == key:
            value = getattr(item.value, "value", None)
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
    return None


async def fetch_caption_limit(client) -> int:
    try:
        app_config = await client(GetAppConfigRequest(hash=0))
        config = getattr(app_config, "config", None)
        me = await client.get_me()
        key = "caption_length_limit_premium" if getattr(me, "premium", False) else "caption_length_limit_default"
        return _config_number(config, key) or DEFAULT_CAPTION_LIMIT
    except Exception as exc:  # noqa: BLE001 -- informational only: the default is always safe
        logger.info("Не удалось узнать лимит подписи, используется %d: %s", DEFAULT_CAPTION_LIMIT, exc)
        return DEFAULT_CAPTION_LIMIT


@dataclass(frozen=True)
class LinkPreviewInfo:
    url: str
    site_name: str = ""
    title: str = ""
    description: str = ""
    has_large_media: bool = False


async def fetch_link_preview(client, url: str) -> Optional[LinkPreviewInfo]:
    try:
        media = await client(GetWebPagePreviewRequest(message=url))
    except Exception as exc:  # noqa: BLE001 -- the preview falls back to a plain card
        logger.info("Не удалось получить превью ссылки: %s", exc)
        return None
    # Layer 181 answers with MessageMedia; later layers wrap it in
    # messages.WebPagePreview(media=...).
    media = getattr(media, "media", media)
    page = media.webpage if isinstance(media, MessageMediaWebPage) else None
    if not isinstance(page, WebPage):
        return None
    return LinkPreviewInfo(
        url=url,
        site_name=page.site_name or "",
        title=page.title or "",
        description=page.description or "",
        has_large_media=bool(page.has_large_media),
    )


class ServerInfoCache:
    """For one app session: caption limit per account, card per URL."""

    def __init__(self) -> None:
        self._caption_limits: Dict[Hashable, int] = {}
        self._previews: Dict[str, Optional[LinkPreviewInfo]] = {}

    async def caption_limit(self, account_key: Hashable, client) -> int:
        if account_key not in self._caption_limits:
            self._caption_limits[account_key] = await fetch_caption_limit(client)
        return self._caption_limits[account_key]

    def known_caption_limit(self, account_key: Hashable) -> Optional[int]:
        return self._caption_limits.get(account_key)

    async def link_preview(self, client, url: str) -> Optional[LinkPreviewInfo]:
        if url not in self._previews:
            self._previews[url] = await fetch_link_preview(client, url)
        return self._previews[url]

    def known_link_preview(self, url: str) -> Optional[LinkPreviewInfo]:
        return self._previews.get(url)

    def has_link_preview(self, url: str) -> bool:
        return url in self._previews

    def clear(self) -> None:
        self._caption_limits.clear()
        self._previews.clear()
