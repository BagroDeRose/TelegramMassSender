"""Tests for {name} placeholder expansion (app.telegram.template).

Every case here must be resolvable per-recipient, without ever mutating
the template's original text/entities (the campaign engine reuses the same
template for every recipient in the queue).
"""
from __future__ import annotations

from telethon.tl.types import MessageEntityBold, MessageEntityTextUrl

from app.telegram.media_sender import build_media_send_plan
from app.telegram.template import expand_name_placeholder
from tests.mocks.mock_telegram_client import make_fake_user


def test_no_placeholder_returns_inputs_unchanged():
    text = "Привет всем!"
    entities = [MessageEntityBold(offset=0, length=6)]
    result_text, result_entities = expand_name_placeholder(text, entities, "Alex")
    assert result_text == text
    assert result_entities is entities


def test_single_placeholder_replaced():
    text = "Привет, {name}!"
    result_text, _ = expand_name_placeholder(text, [], "Alex")
    assert result_text == "Привет, Alex!"


def test_multiple_placeholders_all_replaced():
    text = "{name}, привет, {name}!"
    result_text, _ = expand_name_placeholder(text, [], "Alex")
    assert result_text == "Alex, привет, Alex!"


def test_missing_first_name_uses_empty_string():
    text = "Привет, {name}!"
    result_text, _ = expand_name_placeholder(text, [], None)
    assert result_text == "Привет, !"


def test_empty_first_name_uses_empty_string():
    text = "Привет, {name}!"
    result_text, _ = expand_name_placeholder(text, [], "")
    assert result_text == "Привет, !"


def test_unicode_first_name():
    text = "Привет, {name}!"
    result_text, _ = expand_name_placeholder(text, [], "Алекс")
    assert result_text == "Привет, Алекс!"


def test_emoji_adjacent_to_placeholder_preserves_offsets():
    # 🎉 is an astral-plane character (UTF-16 surrogate pair, i.e. 2 UTF-16
    # code units) -- an entity positioned after both the emoji and the
    # placeholder must remain correctly aligned once {name} is expanded.
    from telethon.helpers import add_surrogate

    text = "🎉 Привет, {name}! Конец"
    surrogate_text = add_surrogate(text)
    tail_start = surrogate_text.index("Конец")
    entities = [MessageEntityBold(offset=tail_start, length=len("Конец"))]

    result_text, result_entities = expand_name_placeholder(text, entities, "Alex")
    assert result_text == "🎉 Привет, Alex! Конец"
    tail_entity = result_entities[0]
    result_surrogate = add_surrogate(result_text)
    assert result_surrogate[tail_entity.offset : tail_entity.offset + tail_entity.length] == "Конец"


def test_formatted_text_around_placeholder_offsets_survive():
    # "Привет, {name}!" with "Привет" bolded -- expanding a shorter/longer
    # name must not shift the bold entity's start, and text after the
    # placeholder must still be covered correctly by any trailing entity.
    text = "Привет, {name}! Пока!"
    bold_start = 0
    bold_len = len("Привет")
    tail_start = text.index("Пока")
    tail_len = len("Пока")
    entities = [
        MessageEntityBold(offset=bold_start, length=bold_len),
        MessageEntityBold(offset=tail_start, length=tail_len),
    ]
    result_text, result_entities = expand_name_placeholder(text, entities, "Alexandra")
    assert result_text == "Привет, Alexandra! Пока!"
    bold_entity = next(e for e in result_entities if e.offset == 0)
    assert result_text[bold_entity.offset : bold_entity.offset + bold_entity.length] == "Привет"
    tail_entity = next(e for e in result_entities if e.offset != 0)
    assert result_text[tail_entity.offset : tail_entity.offset + tail_entity.length] == "Пока"


def test_link_entity_around_placeholder_offsets_survive():
    text = "Смотри {name} тут"
    link_start = text.index("тут")
    entities = [MessageEntityTextUrl(offset=link_start, length=len("тут"), url="https://example.com")]
    result_text, result_entities = expand_name_placeholder(text, entities, "Al")
    assert result_text == "Смотри Al тут"
    link = result_entities[0]
    assert result_text[link.offset : link.offset + link.length] == "тут"
    assert link.url == "https://example.com"


def test_entity_exactly_on_placeholder_shrinks_or_drops():
    text = "{name}"
    entities = [MessageEntityBold(offset=0, length=len("{name}"))]
    # Shorter name: entity shrinks but survives.
    result_text, result_entities = expand_name_placeholder(text, entities, "Al")
    assert result_text == "Al"
    assert len(result_entities) == 1
    assert result_entities[0].offset == 0
    assert result_entities[0].length == 2

    # Empty name: entity has zero length and is dropped entirely rather
    # than producing an invalid zero-length MessageEntity.
    result_text, result_entities = expand_name_placeholder(text, entities, "")
    assert result_text == ""
    assert result_entities == []


def test_original_entities_list_not_mutated():
    text = "Привет, {name}!"
    entities = [MessageEntityBold(offset=0, length=6)]
    original_offset = entities[0].offset
    expand_name_placeholder(text, entities, "Alexandra")
    assert entities[0].offset == original_offset


def test_media_caption_with_placeholder(tmp_path):
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"fake")
    from app.telegram.media_sender import Attachment

    text = "Привет, {name}! Смотри фото."
    expanded_text, expanded_entities = expand_name_placeholder(text, [], "Alex")
    plan = build_media_send_plan([Attachment(path=image_path)], expanded_text, expanded_entities)
    assert plan.group_captions[0][0] == "Привет, Alex! Смотри фото."


async def test_campaign_expands_name_per_recipient(qapp):
    from app.campaign.campaign_manager import CampaignManager
    from app.recipients.parser import parse_recipient_line

    class FakeRateLimiter:
        def next_delay(self) -> float:
            return 0.01

    from tests.mocks.mock_telegram_client import MockTelegramClient

    client = MockTelegramClient(first_name_behavior={"alice": "Alice", "bobby": "Bob"})
    recipients = [parse_recipient_line("@alice"), parse_recipient_line("@bobby")]
    manager = CampaignManager(
        client=client,
        recipients=recipients,
        message_text="Привет, {name}!",
        message_entities=[],
        attachments=[],
        rate_limiter=FakeRateLimiter(),
        max_retries=1,
    )

    import asyncio

    fut = asyncio.get_event_loop().create_future()
    manager.finished.connect(lambda status: fut.done() or fut.set_result(status))
    manager.start()
    await asyncio.wait_for(fut, timeout=10)

    sent_texts = {entity.username: text for (_, entity, text, _) in client.sent_messages}
    assert sent_texts["alice"] == "Привет, Alice!"
    assert sent_texts["bobby"] == "Привет, Bob!"


async def test_csv_supplied_name_overrides_telegrams_own_first_name(qapp):
    # Smart Recipient Import (v1.6): a name mapped from a CSV column is
    # the sender's own, deliberately supplied data for that recipient --
    # it must win over whatever Telegram itself reports as the resolved
    # user's first_name, not just be a fallback for when Telegram has none.
    from app.campaign.campaign_manager import CampaignManager
    from app.recipients.parser import parse_recipient_line

    class FakeRateLimiter:
        def next_delay(self) -> float:
            return 0.01

    from tests.mocks.mock_telegram_client import MockTelegramClient

    client = MockTelegramClient(first_name_behavior={"alice": "TelegramAlice"})
    recipients = [parse_recipient_line("@alice")]
    manager = CampaignManager(
        client=client,
        recipients=recipients,
        message_text="Привет, {name}!",
        message_entities=[],
        attachments=[],
        rate_limiter=FakeRateLimiter(),
        max_retries=1,
        recipient_names={"username:alice": "CsvAlice"},
    )

    import asyncio

    fut = asyncio.get_event_loop().create_future()
    manager.finished.connect(lambda status: fut.done() or fut.set_result(status))
    manager.start()
    await asyncio.wait_for(fut, timeout=10)

    sent_text = client.sent_messages[0][2]
    assert sent_text == "Привет, CsvAlice!"
