"""Media attachment handling: validation, grouping into albums vs
individual documents, and caption-length overflow logic (spec items
18-20, 48-50).

Telegram only allows albums (media groups) of homogeneous photo/video,
up to 10 items; anything else (documents, mixed types) must be sent as
separate messages. This module groups a user's attachment list
accordingly and decides how the caption text is attached, without ever
silently dropping either an attachment or the message text. The actual
per-item MIME/streaming-attribute detection is left to Telethon's
client.send_file, which already does this correctly from the file path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from telethon import TelegramClient
from telethon import utils as telethon_utils
from telethon.tl.functions.messages import SendMultiMediaRequest, UploadMediaRequest
from telethon.tl.types import (
    InputMediaPhotoExternal,
    InputMediaUploadedDocument,
    InputMediaUploadedPhoto,
    InputSingleMedia,
    TypeMessageEntity,
)

from app.logging.logger import get_logger
from app.telegram.exceptions import AttachmentNotFoundError

logger = get_logger()

CAPTION_MAX_LENGTH = 1024
TEXT_MESSAGE_MAX_LENGTH = 4096
MAX_ALBUM_SIZE = 10

# Photo/video are the only types Telegram will group into an album; every
# other extension (pdf/doc/docx/xls/xlsx/ppt/pptx/txt/zip/gif/anything
# else) is sent individually as its own message -- spec item 18 asks not
# to restrict the extension list without a technical reason, so anything
# not in these two sets simply falls through to "sent individually",
# never rejected.
_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi"}
_ALBUM_ELIGIBLE_EXTENSIONS = _PHOTO_EXTENSIONS | _VIDEO_EXTENSIONS


class AttachmentCategory(Enum):
    ALBUM_ELIGIBLE = "album_eligible"
    SINGLE = "single"


@dataclass(frozen=True)
class Attachment:
    path: Path

    @property
    def file_name(self) -> str:
        return self.path.name

    @property
    def category(self) -> AttachmentCategory:
        if self.path.suffix.lower() in _ALBUM_ELIGIBLE_EXTENSIONS:
            return AttachmentCategory.ALBUM_ELIGIBLE
        return AttachmentCategory.SINGLE

    def validate_exists(self) -> None:
        if not self.path.is_file():
            raise AttachmentNotFoundError(f"Файл не найден: {self.path.name}")

    def size_bytes(self) -> int:
        return self.path.stat().st_size


@dataclass
class SendGroup:
    attachments: List[Attachment]
    is_album: bool


def build_send_groups(attachments: List[Attachment]) -> List[SendGroup]:
    """Group consecutive album-eligible attachments (chunked to Telegram's
    10-item album limit); everything else becomes its own single-item
    group. Order is preserved and nothing is dropped."""
    groups: List[SendGroup] = []
    pending: List[Attachment] = []

    def flush() -> None:
        nonlocal pending
        for i in range(0, len(pending), MAX_ALBUM_SIZE):
            chunk = pending[i : i + MAX_ALBUM_SIZE]
            groups.append(SendGroup(attachments=chunk, is_album=len(chunk) > 1))
        pending = []

    for attachment in attachments:
        if attachment.category == AttachmentCategory.ALBUM_ELIGIBLE:
            pending.append(attachment)
        else:
            flush()
            groups.append(SendGroup(attachments=[attachment], is_album=False))

    flush()
    return groups


@dataclass
class MediaSendPlan:
    groups: List[SendGroup] = field(default_factory=list)
    # (text, entities) sent as its own message before any attachment
    # groups -- used when there is no media at all, or when the message
    # text is too long to fit as a caption.
    leading_text: Optional[Tuple[str, List[TypeMessageEntity]]] = None
    # group index -> (caption text, entities) attached to that group's send_file call.
    group_captions: Dict[int, Tuple[str, List[TypeMessageEntity]]] = field(default_factory=dict)


def build_media_send_plan(
    attachments: List[Attachment],
    message_text: str,
    message_entities: List[TypeMessageEntity],
) -> MediaSendPlan:
    for attachment in attachments:
        attachment.validate_exists()

    groups = build_send_groups(attachments)
    message_text = message_text or ""
    message_entities = message_entities or []

    if not groups:
        leading = (message_text, message_entities) if message_text else None
        return MediaSendPlan(groups=[], leading_text=leading, group_captions={})

    if not message_text:
        return MediaSendPlan(groups=groups, leading_text=None, group_captions={})

    if len(message_text) <= CAPTION_MAX_LENGTH:
        return MediaSendPlan(
            groups=groups,
            leading_text=None,
            group_captions={0: (message_text, message_entities)},
        )

    # Too long for a caption: the text is sent as its own message first,
    # so it is never silently dropped (spec item 20); the media follows
    # without a caption.
    logger.info(
        "Текст сообщения (%d симв.) превышает лимит подписи (%d) -- "
        "отправляется отдельным сообщением",
        len(message_text),
        CAPTION_MAX_LENGTH,
    )
    return MediaSendPlan(groups=groups, leading_text=(message_text, message_entities), group_captions={})


async def _send_album_with_entities(
    client: TelegramClient,
    entity,
    files: List[str],
    caption: str,
    entities: List[TypeMessageEntity],
) -> None:
    """Send multiple files as one Telegram album, with the caption's
    formatting entities intact.

    Telethon 1.36.0's own client.send_file() silently drops
    formatting_entities whenever `file` is list-like: that branch returns
    straight into client._send_album(), which only knows how to derive a
    caption's entities via `parse_mode`-parsing a plain string -- it has
    no parameter for already-built raw entities at all. Converting our
    entities to HTML/Markdown just to round-trip them back through
    parse_mode would be lossy and is explicitly out of scope here.

    InputSingleMedia (what an album is actually made of at the MTProto
    level) *does* carry a raw `entities` field directly. This function
    mirrors exactly what client._send_album() does to upload each file --
    same helper methods, same upload-then-convert steps for freshly
    uploaded photos/documents -- but attaches our own entities to the
    first item instead of losing them, then sends the album with
    SendMultiMediaRequest directly.
    """
    resolved_entity = await client.get_input_entity(entity)
    media_items = []
    for index, file_path in enumerate(files):
        _handle, input_media, _image = await client._file_to_media(file_path, nosound_video=True)

        # A freshly uploaded (not yet cached) photo/document must first be
        # turned into a "real" media reference before it can be attached
        # to an album -- identical to what client._send_album() does.
        if isinstance(input_media, (InputMediaUploadedPhoto, InputMediaPhotoExternal)):
            uploaded = await client(UploadMediaRequest(resolved_entity, media=input_media))
            input_media = telethon_utils.get_input_media(uploaded.photo)
        elif isinstance(input_media, InputMediaUploadedDocument):
            uploaded = await client(UploadMediaRequest(resolved_entity, media=input_media))
            input_media = telethon_utils.get_input_media(uploaded.document)

        if index == 0:
            item_caption, item_entities = caption, (entities or None)
        else:
            item_caption, item_entities = "", None
        media_items.append(InputSingleMedia(input_media, message=item_caption, entities=item_entities))

    request = SendMultiMediaRequest(resolved_entity, multi_media=media_items)
    await client(request)


@dataclass
class SendProgress:
    """Mutable out-parameter: how many delivery steps of a MediaSendPlan a
    call to send_media_plan()/send_to_recipient() completed, updated
    incrementally as each step returns -- including when a *later* step
    then raises, so the caller can see exactly how far execution got
    before failing, and resume from there on retry instead of repeating
    an already-delivered step."""

    completed_steps: int = 0


SendStep = Callable[[], Awaitable[None]]


def build_send_steps(client: TelegramClient, entity, plan: MediaSendPlan) -> List[SendStep]:
    """Flatten a MediaSendPlan into an ordered list of steps. Each step is
    exactly one delivery-causing Telegram RPC (client.send_message,
    client.send_file, or the album's SendMultiMediaRequest) -- the unit a
    retry must never repeat once it has already returned successfully.
    Read-only/upload helper calls inside a group (get_input_entity,
    _file_to_media, UploadMediaRequest) are not separate steps: they are
    entirely internal to that group's single step and safe to redo."""
    steps: List[SendStep] = []

    if plan.leading_text is not None:
        text, entities = plan.leading_text

        async def _send_leading_text(text=text, entities=entities) -> None:
            await client.send_message(entity, text, formatting_entities=entities or None)

        steps.append(_send_leading_text)

    for index, group in enumerate(plan.groups):
        caption_text, caption_entities = plan.group_captions.get(index, ("", []))
        files = [str(a.path) for a in group.attachments]

        if len(files) > 1:

            async def _send_group(
                files=files, caption_text=caption_text, caption_entities=caption_entities
            ) -> None:
                await _send_album_with_entities(client, entity, files, caption_text, caption_entities)

        else:

            async def _send_group(
                files=files, caption_text=caption_text, caption_entities=caption_entities
            ) -> None:
                await client.send_file(
                    entity,
                    files[0],
                    caption=caption_text or None,
                    formatting_entities=caption_entities or None,
                )

        steps.append(_send_group)

    return steps


async def send_media_plan(
    client: TelegramClient,
    entity,
    plan: MediaSendPlan,
    start_step: int = 0,
    progress: Optional[SendProgress] = None,
) -> None:
    """Execute plan's delivery steps in order, starting at `start_step` (0
    executes the whole plan, matching prior behaviour exactly). Each step
    that returns successfully increments `progress.completed_steps` before
    the next step is attempted, so a step that later raises never erases
    the record of what already went out."""
    steps = build_send_steps(client, entity, plan)
    for step in steps[start_step:]:
        await step()
        if progress is not None:
            progress.completed_steps += 1
