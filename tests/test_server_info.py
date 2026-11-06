"""The caption limit comes from the account's own Telegram config
(help.getAppConfig: caption_length_limit_default / _premium, chosen by
the account's Premium flag), cached for the session, 1024 when it can't
be read. Link-preview cards come from messages.getWebPagePreview, also
cached -- title/description only, no images downloaded."""
from __future__ import annotations

from types import SimpleNamespace

from telethon.errors import FloodWaitError
from telethon.tl.functions.help import GetAppConfigRequest
from telethon.tl.functions.messages import GetWebPagePreviewRequest
from telethon.tl.types import (
    JsonNumber,
    JsonObject,
    JsonObjectValue,
    MessageMediaEmpty,
    MessageMediaWebPage,
    WebPage,
    WebPagePending,
)
from telethon.tl.types.help import AppConfig

from app.telegram.server_info import ServerInfoCache, fetch_caption_limit, fetch_link_preview
from tests.mocks.mock_telegram_client import MockTelegramClient


def _config(default=1024, premium=4096):
    values = [
        JsonObjectValue("caption_length_limit_default", JsonNumber(default)),
        JsonObjectValue("caption_length_limit_premium", JsonNumber(premium)),
    ]
    return AppConfig(hash=1, config=JsonObject(values))


async def test_regular_account_gets_the_default_limit():
    client = MockTelegramClient(app_config=_config(), me=SimpleNamespace(premium=False))
    assert await fetch_caption_limit(client) == 1024


async def test_premium_account_gets_the_premium_limit():
    client = MockTelegramClient(app_config=_config(), me=SimpleNamespace(premium=True))
    assert await fetch_caption_limit(client) == 4096


async def test_limits_follow_the_server_config():
    client = MockTelegramClient(app_config=_config(default=2000, premium=8000), me=SimpleNamespace(premium=False))
    assert await fetch_caption_limit(client) == 2000


async def test_any_failure_falls_back_to_1024():
    for config in (FloodWaitError(request=None, capture=5), None, AppConfig(hash=1, config=JsonObject([]))):
        client = MockTelegramClient(app_config=config, me=SimpleNamespace(premium=True))
        assert await fetch_caption_limit(client) == 1024


async def test_cache_asks_telegram_once_per_account():
    cache = ServerInfoCache()
    client = MockTelegramClient(app_config=_config(), me=SimpleNamespace(premium=True))
    assert await cache.caption_limit("account-1", client) == 4096
    assert await cache.caption_limit("account-1", client) == 4096
    assert sum(isinstance(r, GetAppConfigRequest) for r in client.raw_requests) == 1
    assert cache.known_caption_limit("account-1") == 4096
    assert cache.known_caption_limit("account-2") is None


class _PreviewClient(MockTelegramClient):
    def __init__(self, media):
        super().__init__()
        self._media = media

    async def __call__(self, request):
        self.raw_requests.append(request)
        if isinstance(request, GetWebPagePreviewRequest):
            if isinstance(self._media, BaseException):
                raise self._media
            return self._media
        return await super().__call__(request)


def _page(**kw):
    return WebPage(id=1, url="https://t.me/example", display_url="t.me/example", hash=0, **kw)


async def test_link_preview_reads_title_description_and_large_media():
    client = _PreviewClient(
        MessageMediaWebPage(webpage=_page(site_name="Telegram", title="Example", description="Канал", has_large_media=True))
    )
    info = await fetch_link_preview(client, "https://t.me/example")
    assert (info.site_name, info.title, info.description, info.has_large_media) == ("Telegram", "Example", "Канал", True)
    request = next(r for r in client.raw_requests if isinstance(r, GetWebPagePreviewRequest))
    assert request.message == "https://t.me/example"


async def test_no_card_when_telegram_has_none_or_fails():
    for media in (MessageMediaEmpty(), MessageMediaWebPage(webpage=WebPagePending(id=1, date=0)), FloodWaitError(request=None, capture=3)):
        assert await fetch_link_preview(_PreviewClient(media), "https://t.me/example") is None


async def test_link_preview_cache_is_per_url():
    cache = ServerInfoCache()
    client = _PreviewClient(MessageMediaWebPage(webpage=_page(title="Example")))
    assert (await cache.link_preview(client, "https://t.me/example")).title == "Example"
    await cache.link_preview(client, "https://t.me/example")
    assert sum(isinstance(r, GetWebPagePreviewRequest) for r in client.raw_requests) == 1
    assert cache.known_link_preview("https://t.me/example").title == "Example"
