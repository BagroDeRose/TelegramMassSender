"""The one send plan: which messages go out, in what order, what is a
caption, what is a separate text, and where a link preview goes. The
sender executes it and the preview draws it -- nothing else decides.

Synthetic texts only (lengths chosen around the caption limits); links
point at t.me/example."""
from __future__ import annotations

from pathlib import Path

import pytest
from telethon.tl.types import MessageEntityBold, MessageEntityTextUrl

from app.telegram.media_sender import Attachment, build_media_send_plan
from app.telegram.message_options import (
    DEFAULT_CAPTION_LIMIT,
    LinkPreviewOptions,
    MediaTextOrder,
    MessageOptions,
    PreviewSize,
    find_links,
    utf16_len,
)


def _photo(tmp_path: Path, name: str = "photo.jpg") -> Attachment:
    path = tmp_path / name
    path.write_bytes(b"x")
    return Attachment(path)


def _text(length: int, link: str = "") -> str:
    body = "Синтетический текст для проверки длины. "
    text = (link + " " if link else "") + body * (length // len(body) + 1)
    return text[:length]


def _kinds(plan):
    return [(m.kind, bool(m.text)) for m in plan.messages()]


def test_utf16_length_counts_surrogate_pairs():
    assert utf16_len("abc") == 3
    assert utf16_len("😀") == 2  # one emoji, two UTF-16 units -- how Telegram counts
    assert utf16_len("") == 0


def test_short_text_and_photo_is_one_message_with_caption(tmp_path):
    plan = build_media_send_plan([_photo(tmp_path)], _text(500), [], caption_limit=1024)
    assert _kinds(plan) == [("media", True)]
    assert plan.caption_overflow is False


def test_long_text_and_photo_is_two_messages_text_first_by_default(tmp_path):
    text = _text(1500)
    plan = build_media_send_plan([_photo(tmp_path)], text, [], caption_limit=1024)
    assert _kinds(plan) == [("text", True), ("media", False)]
    assert plan.caption_overflow is True
    assert plan.text_length == 1500 and plan.caption_limit == 1024


def test_long_text_and_photo_media_first_when_chosen(tmp_path):
    options = MessageOptions(order=MediaTextOrder.MEDIA_FIRST)
    plan = build_media_send_plan([_photo(tmp_path)], _text(1500), [], options=options, caption_limit=1024)
    assert _kinds(plan) == [("media", False), ("text", True)]


def test_premium_caption_limit_keeps_one_message(tmp_path):
    plan = build_media_send_plan([_photo(tmp_path)], _text(1500), [], caption_limit=4096)
    assert _kinds(plan) == [("media", True)]


def test_caption_limit_is_measured_in_utf16_units(tmp_path):
    # 600 emoji = 600 characters for Python but 1200 UTF-16 units for Telegram.
    plan = build_media_send_plan([_photo(tmp_path)], "😀" * 600, [], caption_limit=1024)
    assert plan.caption_overflow is True


def test_default_caption_limit_is_telegrams_1024():
    assert DEFAULT_CAPTION_LIMIT == 1024


def test_text_only_message_has_no_link_preview_by_default():
    plan = build_media_send_plan([], "Смотрите t.me/example", [])
    (message,) = plan.messages()
    assert message.kind == "text" and message.link_preview is None


def test_one_link_preview_switched_on():
    options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example"))
    plan = build_media_send_plan([], "Смотрите t.me/example", [], options=options)
    (message,) = plan.messages()
    assert message.link_preview is not None and message.link_preview.url == "https://t.me/example"


def test_several_links_including_text_url_the_chosen_one_is_used():
    text = "Первая https://example.org и Алсу"
    label_offset = utf16_len("Первая https://example.org и ")
    entities = [MessageEntityTextUrl(offset=label_offset, length=4, url="https://t.me/example")]
    links = find_links(text, entities)
    assert [link.url for link in links] == ["https://example.org", "https://t.me/example"]
    assert links[1].label == "Алсу" and links[1].domain == "t.me"
    options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example"))
    (message,) = build_media_send_plan([], text, entities, options=options).messages()
    assert message.link_preview.url == "https://t.me/example"


def test_a_chosen_link_no_longer_in_the_text_means_no_preview():
    options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/gone"))
    (message,) = build_media_send_plan([], "Смотрите t.me/example", [], options=options).messages()
    assert message.link_preview is None


@pytest.mark.parametrize("above", [False, True])
@pytest.mark.parametrize("size", [PreviewSize.AUTO, PreviewSize.LARGE, PreviewSize.SMALL])
def test_preview_position_and_size_are_carried(above, size):
    preview = LinkPreviewOptions(url="https://t.me/example", above_text=above, size=size)
    (message,) = build_media_send_plan([], "t.me/example", [], options=MessageOptions(link_preview=preview)).messages()
    assert message.link_preview == preview


def test_no_link_preview_in_a_caption(tmp_path):
    options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example"))
    plan = build_media_send_plan([_photo(tmp_path)], "Смотрите t.me/example", [], options=options)
    (message,) = plan.messages()
    assert message.kind == "media" and message.link_preview is None
    assert plan.link_preview_possible is False


def test_link_preview_kept_on_the_separate_text_when_it_overflows(tmp_path):
    options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example"))
    plan = build_media_send_plan([_photo(tmp_path)], _text(1500, "t.me/example"), [], options=options)
    text_message = next(m for m in plan.messages() if m.kind == "text")
    assert text_message.link_preview.url == "https://t.me/example"
    assert plan.link_preview_possible is True


def test_explicit_urls_are_found_with_and_without_scheme():
    links = find_links("a https://example.org/path, b www.example.com c t.me/example. Версия 2.1.1", [])
    assert [link.url for link in links] == ["https://example.org/path", "https://www.example.com", "https://t.me/example"]
    assert [link.domain for link in links] == ["example.org", "example.com", "t.me"]


def test_the_same_link_twice_is_listed_once():
    assert len(find_links("t.me/example и ещё раз https://t.me/example", [])) == 1


def test_options_round_trip_and_old_data_means_no_preview():
    options = MessageOptions(
        order=MediaTextOrder.MEDIA_FIRST,
        link_preview=LinkPreviewOptions(url="https://t.me/example", above_text=True, size=PreviewSize.LARGE),
    )
    assert MessageOptions.from_json(options.to_json()) == options
    assert MessageOptions.from_json(None) == MessageOptions()
    assert MessageOptions.from_json("") == MessageOptions()
    assert MessageOptions.from_json("{not json") == MessageOptions()
    assert MessageOptions().link_preview.url is None  # preview off by default


def test_formatting_survives_in_the_caption(tmp_path):
    entities = [MessageEntityBold(offset=0, length=5)]
    (message,) = build_media_send_plan([_photo(tmp_path)], "Hello world", entities).messages()
    assert list(message.entities) == entities


# ---- what actually reaches Telegram ---------------------------------------------------

from telethon.tl.functions.messages import SendMediaRequest  # noqa: E402
from telethon.tl.types import InputMediaWebPage  # noqa: E402

from app.telegram.sender import send_to_recipient  # noqa: E402
from app.telegram.template import expand_name_placeholder  # noqa: E402
from tests.mocks.mock_telegram_client import MockTelegramClient  # noqa: E402


def _webpage_requests(client):
    return [r for r in client.raw_requests if isinstance(r, SendMediaRequest) and isinstance(r.media, InputMediaWebPage)]


async def test_text_is_sent_without_a_preview_by_default():
    client = MockTelegramClient()
    await send_to_recipient(client, "peer", "Смотрите t.me/example", [])
    assert [m[0] for m in client.sent_messages] == ["message"]
    assert client.link_preview_flags == [False]


async def test_chosen_link_is_sent_with_its_preview_below_by_default():
    client = MockTelegramClient()
    options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example"))
    await send_to_recipient(client, "peer", "Смотрите t.me/example", [], options=options)
    (request,) = _webpage_requests(client)
    assert request.media.url == "https://t.me/example" and request.media.optional is True
    assert not request.invert_media
    assert not request.media.force_large_media and not request.media.force_small_media
    assert request.message == "Смотрите t.me/example"


@pytest.mark.parametrize("size, large, small", [(PreviewSize.LARGE, True, None), (PreviewSize.SMALL, None, True)])
async def test_preview_above_and_size(size, large, small):
    client = MockTelegramClient()
    preview = LinkPreviewOptions(url="https://t.me/example", above_text=True, size=size)
    await send_to_recipient(client, "peer", "t.me/example", [], options=MessageOptions(link_preview=preview))
    (request,) = _webpage_requests(client)
    assert request.invert_media is True
    assert request.media.force_large_media == large and request.media.force_small_media == small


async def test_second_link_under_text_is_the_one_previewed():
    client = MockTelegramClient()
    text = "Сайт https://example.org и Алсу"
    entities = [MessageEntityTextUrl(offset=utf16_len("Сайт https://example.org и "), length=4, url="https://t.me/example")]
    options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example"))
    await send_to_recipient(client, "peer", text, entities, options=options)
    (request,) = _webpage_requests(client)
    assert request.media.url == "https://t.me/example"
    assert request.entities == entities


async def test_long_text_and_photo_two_messages_in_the_chosen_order(tmp_path):
    for order, expected in ((MediaTextOrder.TEXT_FIRST, ["message", "file"]), (MediaTextOrder.MEDIA_FIRST, ["file", "message"])):
        client = MockTelegramClient()
        await send_to_recipient(
            client, "peer", _text(1500), [], [_photo(tmp_path)], options=MessageOptions(order=order), caption_limit=1024
        )
        assert [m[0] for m in client.sent_messages] == expected
        assert next(m for m in client.sent_messages if m[0] == "file")[3] is None  # no caption


async def test_premium_limit_sends_one_photo_with_caption(tmp_path):
    client = MockTelegramClient()
    text = _text(1500)
    await send_to_recipient(client, "peer", text, [], [_photo(tmp_path)], caption_limit=4096)
    assert [(m[0], m[3]) for m in client.sent_messages] == [("file", text)]


async def test_caption_gets_no_preview_even_if_one_was_chosen(tmp_path):
    client = MockTelegramClient()
    options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example"))
    await send_to_recipient(client, "peer", "t.me/example", [], [_photo(tmp_path)], options=options)
    assert [m[0] for m in client.sent_messages] == ["file"]
    assert _webpage_requests(client) == []


async def test_name_formatting_and_preview_together():
    client = MockTelegramClient()
    template = "Привет, {name}! Смотрите t.me/example"
    entities = [MessageEntityBold(offset=0, length=utf16_len("Привет, {name}!"))]
    text, expanded = expand_name_placeholder(template, entities, "Александра")
    options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example"))
    await send_to_recipient(client, "peer", text, expanded, options=options)
    (request,) = _webpage_requests(client)
    assert request.message == "Привет, Александра! Смотрите t.me/example"
    (bold,) = request.entities
    assert (bold.offset, bold.length) == (0, utf16_len("Привет, Александра!"))
