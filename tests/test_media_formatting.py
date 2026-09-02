"""Regression tests for: formatting (bold/italic/.../entities) was lost
whenever a message was sent with 2+ attachments, but survived with a
single attachment.

Root cause: Telethon 1.36.0's own `TelegramClient.send_file()` has two
code paths. For a single file it correctly honours `formatting_entities`.
For a list of files (album) it takes an early-return branch straight into
`_send_album()`, which has no `formatting_entities` parameter at all --
only `parse_mode`. `formatting_entities` is silently dropped before our
carefully UTF-16-offset-computed entities ever reach the request. This is
a limitation of the installed Telethon version's public API, not a bug in
our own entity-construction code (see app.ui.message_editor, already
covered by tests/test_message_editor.py).

The fix (app/telegram/media_sender.py) sends albums via a small,
Telethon-mirroring routine that builds `InputSingleMedia` (which *does*
accept raw `entities` at the MTProto level) and calls
`SendMultiMediaRequest` directly, instead of going through
`client.send_file()`'s lossy list-like branch. Single-file sends are
untouched -- they already worked correctly.

`tests.mocks.mock_telegram_client.MockTelegramClient.send_file` is built
to faithfully reproduce the real Telethon bug (it drops
formatting_entities when given a list), so a regression here fails for
the right reason: because the code took the lossy path, not because the
mock is stricter than the real library.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest
from telethon.tl.functions.messages import SendMultiMediaRequest
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityCode,
    MessageEntityItalic,
    MessageEntityPre,
    MessageEntitySpoiler,
    MessageEntityStrike,
    MessageEntityTextUrl,
    MessageEntityUnderline,
    TypeMessageEntity,
)

from app.telegram.media_sender import (
    CAPTION_MAX_LENGTH,
    Attachment,
    SendProgress,
    build_media_send_plan,
    send_media_plan,
)
from app.telegram.sender import send_to_recipient
from tests.mocks.mock_telegram_client import MockTelegramClient

PEER = "test_peer"


def _make_attachments(tmp_path: Path, names: List[str]) -> List[Attachment]:
    attachments = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"fake binary content")
        attachments.append(Attachment(path))
    return attachments


def _file_sends(client: MockTelegramClient):
    return [m for m in client.sent_messages if m[0] == "file"]


def _multi_media_requests(client: MockTelegramClient):
    return [r for r in client.raw_requests if isinstance(r, SendMultiMediaRequest)]


# ---------------------------------------------------------------------------
# Test 1: single attachment -- must keep working exactly as before (proves
# the fix did not regress the already-correct single-file path).
# ---------------------------------------------------------------------------


async def test_single_attachment_preserves_formatting(tmp_path):
    attachments = _make_attachments(tmp_path, ["photo1.jpg"])
    entities: List[TypeMessageEntity] = [MessageEntityBold(offset=0, length=6)]
    plan = build_media_send_plan(attachments, "Привет мир", entities)

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)

    file_sends = _file_sends(client)
    assert len(file_sends) == 1
    _, entity, files, caption, sent_entities = file_sends[0]
    assert entity == PEER
    assert files == str(attachments[0].path)
    assert caption == "Привет мир"
    assert sent_entities == entities
    assert not _multi_media_requests(client), "single file must not use the album/multi-media path"


# ---------------------------------------------------------------------------
# Test 2/3: 2 and 3 attachments -- this is exactly the reported bug.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [2, 3])
async def test_multiple_attachments_preserve_formatting(tmp_path, count):
    attachments = _make_attachments(tmp_path, [f"photo{i}.jpg" for i in range(count)])
    entities: List[TypeMessageEntity] = [MessageEntityBold(offset=0, length=6)]
    plan = build_media_send_plan(attachments, "Привет мир", entities)

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)

    # Must NOT go through client.send_file() with a list -- that is the
    # exact path that silently drops formatting_entities in Telethon 1.36.0.
    assert not _file_sends(client), "album must not be sent through client.send_file()"

    requests = _multi_media_requests(client)
    assert len(requests) == 1
    media_items = requests[0].multi_media
    assert len(media_items) == count

    first, rest = media_items[0], media_items[1:]
    assert first.message == "Привет мир"
    assert first.entities == entities, "caption formatting must survive a multi-attachment send"
    for item in rest:
        assert item.message == ""
        assert not item.entities


# ---------------------------------------------------------------------------
# Test 4/5: album chunking at Telegram's 10-item limit must not lose
# formatting on the chunk that carries the caption.
# ---------------------------------------------------------------------------


async def test_ten_attachments_album_chunk_preserves_formatting(tmp_path):
    attachments = _make_attachments(tmp_path, [f"p{i}.jpg" for i in range(10)])
    entities: List[TypeMessageEntity] = [MessageEntityItalic(offset=0, length=6)]
    plan = build_media_send_plan(attachments, "Привет мир", entities)

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)

    requests = _multi_media_requests(client)
    assert len(requests) == 1
    assert len(requests[0].multi_media) == 10
    assert requests[0].multi_media[0].entities == entities


async def test_eleven_attachments_two_chunks_first_chunk_keeps_formatting(tmp_path):
    attachments = _make_attachments(tmp_path, [f"p{i}.jpg" for i in range(11)])
    entities: List[TypeMessageEntity] = [MessageEntityBold(offset=0, length=6)]
    plan = build_media_send_plan(attachments, "Привет мир", entities)

    # 11 album-eligible files -> chunked into a 10-item album + a lone
    # 11th file sent individually (spec: chunks of at most 10).
    assert len(plan.groups) == 2
    assert len(plan.groups[0].attachments) == 10
    assert len(plan.groups[1].attachments) == 1
    assert plan.group_captions == {0: ("Привет мир", entities)}

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)

    requests = _multi_media_requests(client)
    assert len(requests) == 1
    assert len(requests[0].multi_media) == 10
    assert requests[0].multi_media[0].entities == entities, "first chunk must keep the caption formatting"

    # the 11th (lone) file goes through the normal single-file path, with
    # no caption of its own (caption is only ever attached to the first
    # group overall -- unrelated to this bug, pre-existing behaviour).
    file_sends = _file_sends(client)
    assert len(file_sends) == 1
    assert file_sends[0][3] is None


# ---------------------------------------------------------------------------
# Test 6: every formatting type individually, through the album path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entity",
    [
        MessageEntityBold(offset=0, length=5),
        MessageEntityItalic(offset=0, length=5),
        MessageEntityUnderline(offset=0, length=5),
        MessageEntityStrike(offset=0, length=5),
        MessageEntitySpoiler(offset=0, length=5),
        MessageEntityCode(offset=0, length=5),
        MessageEntityPre(offset=0, length=5, language=""),
        MessageEntityTextUrl(offset=0, length=5, url="https://example.com"),
    ],
    ids=lambda e: type(e).__name__,
)
async def test_each_formatting_type_survives_album_send(tmp_path, entity):
    attachments = _make_attachments(tmp_path, ["a.jpg", "b.jpg"])
    plan = build_media_send_plan(attachments, "Hello world", [entity])

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)

    requests = _multi_media_requests(client)
    assert len(requests) == 1
    assert requests[0].multi_media[0].entities == [entity]


async def test_multiple_entity_types_combined_survive_album_send(tmp_path):
    attachments = _make_attachments(tmp_path, ["a.jpg", "b.jpg", "c.jpg"])
    entities: List[TypeMessageEntity] = [
        MessageEntityBold(offset=0, length=8),
        MessageEntityItalic(offset=9, length=6),
        MessageEntityTextUrl(offset=16, length=4, url="https://t.me/example"),
    ]
    plan = build_media_send_plan(attachments, "Обычный курсив тест", entities)

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)

    requests = _multi_media_requests(client)
    assert requests[0].multi_media[0].entities == entities


# ---------------------------------------------------------------------------
# Test 7: emoji + bold, correct UTF-16 offsets, through the album path.
# ---------------------------------------------------------------------------


async def test_emoji_utf16_offsets_survive_album_send(qapp, tmp_path):
    from telethon.helpers import add_surrogate

    from app.ui.message_editor import extract_message_content
    from PySide6.QtGui import QFont, QTextCharFormat, QTextCursor
    from PySide6.QtWidgets import QTextEdit

    text = "Привет 😀 жирный текст"
    te = QTextEdit()
    te.setPlainText(text)
    full = te.toPlainText()
    bold_start_utf16 = len(add_surrogate("Привет 😀 "))
    cursor = te.textCursor()
    cursor.setPosition(bold_start_utf16)
    cursor.setPosition(bold_start_utf16 + 6, QTextCursor.MoveMode.KeepAnchor)  # "жирный"
    fmt = QTextCharFormat()
    fmt.setFontWeight(QFont.Weight.Bold.value)
    cursor.mergeCharFormat(fmt)

    extracted_text, entities = extract_message_content(te.document())
    assert extracted_text == text
    assert len(entities) == 1
    assert entities[0].offset == 10  # "Привет "=7 units + emoji=2 units + " "=1 unit

    attachments = _make_attachments(tmp_path, ["a.jpg", "b.jpg"])
    plan = build_media_send_plan(attachments, extracted_text, entities)

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)

    requests = _multi_media_requests(client)
    assert requests[0].multi_media[0].message == text
    assert requests[0].multi_media[0].entities == entities
    assert requests[0].multi_media[0].entities[0].offset == 10


# ---------------------------------------------------------------------------
# Test 8: media type combinations.
# ---------------------------------------------------------------------------


async def test_photo_plus_photo_uses_album_path(tmp_path):
    attachments = _make_attachments(tmp_path, ["a.jpg", "b.png"])
    entities = [MessageEntityBold(offset=0, length=5)]
    plan = build_media_send_plan(attachments, "Hello", entities)
    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)
    assert len(_multi_media_requests(client)) == 1
    assert _multi_media_requests(client)[0].multi_media[0].entities == entities


async def test_photo_plus_video_uses_album_path(tmp_path):
    attachments = _make_attachments(tmp_path, ["a.jpg", "b.mp4"])
    entities = [MessageEntityBold(offset=0, length=5)]
    plan = build_media_send_plan(attachments, "Hello", entities)
    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)
    assert len(_multi_media_requests(client)) == 1
    assert _multi_media_requests(client)[0].multi_media[0].entities == entities


async def test_video_plus_video_uses_album_path(tmp_path):
    attachments = _make_attachments(tmp_path, ["a.mp4", "b.mov"])
    entities = [MessageEntityItalic(offset=0, length=5)]
    plan = build_media_send_plan(attachments, "Hello", entities)
    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)
    assert _multi_media_requests(client)[0].multi_media[0].entities == entities


async def test_photo_plus_document_does_not_album_but_keeps_caption(tmp_path):
    # A photo and a document can't be grouped into one Telegram album, so
    # this correctly produces two single-item groups; the fix must not
    # change that grouping, only make sure the caption's formatting
    # (attached to the first group) still comes through.
    attachments = _make_attachments(tmp_path, ["a.jpg", "b.pdf"])
    entities = [MessageEntityBold(offset=0, length=5)]
    plan = build_media_send_plan(attachments, "Hello", entities)

    assert len(plan.groups) == 2
    assert all(not g.is_album for g in plan.groups)

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)

    assert not _multi_media_requests(client), "photo+document must not be sent as an album"
    file_sends = _file_sends(client)
    assert len(file_sends) == 2
    assert file_sends[0][3] == "Hello"
    assert file_sends[0][4] == entities
    assert file_sends[1][3] is None


async def test_several_documents_each_single_send_first_keeps_caption(tmp_path):
    attachments = _make_attachments(tmp_path, ["a.pdf", "b.docx", "c.zip"])
    entities = [MessageEntityCode(offset=0, length=5)]
    plan = build_media_send_plan(attachments, "Hello", entities)

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)

    assert not _multi_media_requests(client)
    file_sends = _file_sends(client)
    assert len(file_sends) == 3
    assert file_sends[0][4] == entities
    assert file_sends[1][4] is None
    assert file_sends[2][4] is None


async def test_multiple_media_without_caption_sends_cleanly(tmp_path):
    attachments = _make_attachments(tmp_path, ["a.jpg", "b.jpg"])
    plan = build_media_send_plan(attachments, "", [])

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan)

    requests = _multi_media_requests(client)
    assert len(requests) == 1
    for item in requests[0].multi_media:
        assert item.message == ""
        assert not item.entities


# ---------------------------------------------------------------------------
# Higher-level: the real send path used by test-send and the campaign
# engine (app.telegram.sender.send_to_recipient), not just the media
# service in isolation.
# ---------------------------------------------------------------------------


async def test_send_to_recipient_preserves_formatting_with_multiple_attachments(tmp_path):
    attachments = _make_attachments(tmp_path, ["a.jpg", "b.jpg"])
    entities = [MessageEntityBold(offset=0, length=5)]

    client = MockTelegramClient()
    await send_to_recipient(client, PEER, "Hello world", entities, attachments)

    requests = _multi_media_requests(client)
    assert len(requests) == 1
    assert requests[0].multi_media[0].entities == entities


async def test_campaign_manager_end_to_end_preserves_formatting(qapp, tmp_path):
    """The real path: CampaignManager -> RecipientResolver -> sender ->
    media_sender, exactly as used when a campaign actually runs -- not
    just the media service tested in isolation (per audit request)."""
    from app.campaign.campaign_manager import CampaignManager
    from app.recipients.parser import parse_recipient_line

    class _FixedDelayRateLimiter:
        def next_delay(self) -> float:
            return 0.01

    attachments = _make_attachments(tmp_path, ["a.jpg", "b.jpg"])
    entities = [MessageEntityBold(offset=0, length=5)]
    client = MockTelegramClient(entity_behavior={"receiver": "found"})

    manager = CampaignManager(
        client=client,
        recipients=[parse_recipient_line("@receiver")],
        message_text="Hello world",
        message_entities=entities,
        attachments=attachments,
        rate_limiter=_FixedDelayRateLimiter(),
        max_retries=1,
        parent=None,
    )

    import asyncio

    finished = asyncio.get_event_loop().create_future()
    manager.finished.connect(lambda s: finished.done() or finished.set_result(s))
    manager.start()
    await asyncio.wait_for(finished, timeout=10)

    assert manager.snapshot().sent == 1
    requests = _multi_media_requests(client)
    assert len(requests) == 1
    assert requests[0].multi_media[0].entities == entities


# ---------------------------------------------------------------------------
# Resumable stepped send (P0 regression): a plan with more than one
# delivery-causing Telegram call must be resumable from a given step, so a
# retry after a partial failure never repeats an already-successful step.
# ---------------------------------------------------------------------------


async def test_send_media_plan_resumes_from_start_step(tmp_path):
    """A 3-step plan (leading text + 2 single-file groups) started at step 1
    must skip step 0 entirely and execute only steps 1 and 2."""
    attachments = _make_attachments(tmp_path, ["doc1.pdf", "doc2.pdf"])
    long_text = "x" * (CAPTION_MAX_LENGTH + 1)
    plan = build_media_send_plan(attachments, long_text, [])

    assert plan.leading_text is not None
    assert len(plan.groups) == 2

    client = MockTelegramClient()
    await send_media_plan(client, PEER, plan, start_step=1)

    message_sends = [m for m in client.sent_messages if m[0] == "message"]
    file_sends = _file_sends(client)
    assert not message_sends, "step 0 (leading text) must be skipped when starting at step 1"
    assert len(file_sends) == 2
    assert file_sends[0][2] == str(attachments[0].path)
    assert file_sends[1][2] == str(attachments[1].path)


@pytest.mark.parametrize(
    "attachment_names,text_length,expected_steps",
    [
        ([], 10, 1),
        (["a.jpg"], 10, 1),
        ([f"p{i}.jpg" for i in range(10)], 10, 1),
        ([f"p{i}.jpg" for i in range(11)], 10, 2),
        (["doc.pdf"], CAPTION_MAX_LENGTH + 1, 2),
    ],
    ids=[
        "text_only",
        "single_attachment",
        "ten_attachments",
        "eleven_attachments",
        "long_caption_plus_attachment",
    ],
)
async def test_send_to_recipient_step_count_matches_plan_shape(
    tmp_path, attachment_names, text_length, expected_steps
):
    attachments = _make_attachments(tmp_path, attachment_names)
    text = "x" * text_length
    client = MockTelegramClient()
    progress = SendProgress()

    await send_to_recipient(client, PEER, text, [], attachments, progress=progress)

    assert progress.completed_steps == expected_steps
