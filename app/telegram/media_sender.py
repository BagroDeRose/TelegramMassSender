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
from telethon.tl.functions.messages import SendMediaRequest, SendMultiMediaRequest, UploadMediaRequest
from telethon.tl.types import (
    InputMediaPhotoExternal,
    InputMediaUploadedDocument,
    InputMediaUploadedPhoto,
    InputMediaWebPage,
    InputSingleMedia,
    TypeMessageEntity,
)

from app.logging.logger import get_logger
from app.telegram.exceptions import AttachmentNotFoundError, AttachmentUnreadableError
from app.telegram.message_options import (
    DEFAULT_CAPTION_LIMIT,
    LinkPreviewOptions,
    MediaTextOrder,
    MessageOptions,
    PreviewSize,
    effective_link_preview,
    utf16_len,
)

logger = get_logger()

CAPTION_MAX_LENGTH = DEFAULT_CAPTION_LIMIT
TEXT_MESSAGE_MAX_LENGTH = 4096
MAX_ALBUM_SIZE = 10


class AttachmentKind(Enum):
    """Single source of truth for "what is this local file, for our
    purposes" -- both the send-side album decision (this module) and the
    UI-side thumbnail decision (app.ui.thumbnails) read from the same
    extension table below instead of each keeping an independent list that
    can silently drift out of sync.

    PHOTO/VIDEO are Telegram's own album-eligible types. ANIMATION (.gif)
    and IMAGE_OTHER (.bmp) are locally decodable as an image (so the UI can
    show a real thumbnail) but are deliberately NOT album-eligible:
    - .gif: Telegram has a distinct "animation" send mode (DocumentAttributeAnimated)
      that this app does not yet use -- sending it through the album path would
      be wrong, so it stays DOCUMENT-equivalent for sending until that's built
      as its own change.
    - .bmp: Telegram's own photo pipeline does not reliably accept BMP the way
      it does JPEG/PNG/WEBP -- treating it as an album photo risks a delivery
      failure the app can't safely predict, so it is intentionally kept out of
      the photo set even though Qt can decode it fine for a local thumbnail.
    AUDIO and ARCHIVE are purely descriptive -- added so the UI can show a
    distinct icon for common audio files and .zip archives (see
    app.ui.attachments_widget) -- they carry NO Telegram-sending-semantics
    change: like DOCUMENT, they are sent as a plain document, exactly as
    every audio/zip file already was before this kind existed. Native
    Telegram voice/audio-message semantics remain a separate deferred
    subtask, same as ANIMATION above.
    Everything else, including every unrecognized extension, is DOCUMENT --
    never rejected, matching the existing "don't restrict the extension list
    without a technical reason" behavior.
    """

    PHOTO = "photo"
    VIDEO = "video"
    ANIMATION = "animation"
    IMAGE_OTHER = "image_other"
    AUDIO = "audio"
    ARCHIVE = "archive"
    DOCUMENT = "document"


_EXTENSION_KINDS: Dict[str, AttachmentKind] = {
    ".jpg": AttachmentKind.PHOTO,
    ".jpeg": AttachmentKind.PHOTO,
    ".png": AttachmentKind.PHOTO,
    ".webp": AttachmentKind.PHOTO,
    ".mp4": AttachmentKind.VIDEO,
    ".mov": AttachmentKind.VIDEO,
    ".avi": AttachmentKind.VIDEO,
    ".gif": AttachmentKind.ANIMATION,
    ".bmp": AttachmentKind.IMAGE_OTHER,
    ".mp3": AttachmentKind.AUDIO,
    ".wav": AttachmentKind.AUDIO,
    ".ogg": AttachmentKind.AUDIO,
    ".m4a": AttachmentKind.AUDIO,
    ".flac": AttachmentKind.AUDIO,
    ".aac": AttachmentKind.AUDIO,
    ".zip": AttachmentKind.ARCHIVE,
}

# Telegram will only group PHOTO/VIDEO into an album; everything else
# (including ANIMATION/IMAGE_OTHER, which are locally thumbnailable but not
# Telegram-photo-eligible) is sent individually -- see AttachmentKind above.
_ALBUM_ELIGIBLE_KINDS = {AttachmentKind.PHOTO, AttachmentKind.VIDEO}

# Kinds Qt can decode a real visual thumbnail for locally, independent of
# whether Telegram would accept them as an album photo -- read by
# app.ui.thumbnails so it never needs its own separate extension list.
THUMBNAILABLE_KINDS = {AttachmentKind.PHOTO, AttachmentKind.ANIMATION, AttachmentKind.IMAGE_OTHER}


def kind_for_path(path: Path) -> AttachmentKind:
    return _EXTENSION_KINDS.get(path.suffix.lower(), AttachmentKind.DOCUMENT)


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
    def kind(self) -> AttachmentKind:
        return kind_for_path(self.path)

    @property
    def category(self) -> AttachmentCategory:
        if self.kind in _ALBUM_ELIGIBLE_KINDS:
            return AttachmentCategory.ALBUM_ELIGIBLE
        return AttachmentCategory.SINGLE

    def validate_exists(self) -> None:
        if not self.path.is_file():
            raise AttachmentNotFoundError(f"Файл не найден: {self.path.name}")

    def is_readable(self) -> bool:
        """Lightweight readability probe -- opens the file and reads a
        single byte rather than the whole thing, just enough to surface a
        locked/permission-denied file as distinct from a healthy one
        without the cost of a full read. Callers must check
        validate_exists()/is_file() first: a missing path is not
        "unreadable", it's AttachmentNotFoundError's own case."""
        try:
            with self.path.open("rb") as f:
                f.read(1)
        except OSError:
            return False
        return True

    def validate_readable(self) -> None:
        if not self.is_readable():
            raise AttachmentUnreadableError(
                f"Не удалось прочитать файл: {self.path.name} -- возможно, он "
                "занят другой программой или у вас нет прав на его чтение"
            )

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


@dataclass(frozen=True)
class PlannedMessage:
    """One Telegram message the plan sends: a text message ("text") or one
    attachment group ("media", with its caption if it carries the text)."""

    kind: str
    text: str = ""
    entities: Tuple[TypeMessageEntity, ...] = ()
    group: Optional[SendGroup] = None
    # Text messages only; None = sent without a preview.
    link_preview: Optional[LinkPreviewOptions] = None


@dataclass
class MediaSendPlan:
    groups: List[SendGroup] = field(default_factory=list)
    # (text, entities) sent as its own message before any attachment
    # groups -- used when there is no media at all, or when the message
    # text is too long to fit as a caption (MediaTextOrder.TEXT_FIRST).
    leading_text: Optional[Tuple[str, List[TypeMessageEntity]]] = None
    # group index -> (caption text, entities) attached to that group's send_file call.
    group_captions: Dict[int, Tuple[str, List[TypeMessageEntity]]] = field(default_factory=dict)
    # Too long for a caption and MediaTextOrder.MEDIA_FIRST: after the media.
    trailing_text: Optional[Tuple[str, List[TypeMessageEntity]]] = None
    # The preview the separate text message gets (None: none, or no such message).
    text_link_preview: Optional[LinkPreviewOptions] = None
    caption_limit: int = DEFAULT_CAPTION_LIMIT
    text_length: int = 0  # UTF-16 units, as Telegram counts
    caption_overflow: bool = False  # there is media and the text didn't fit as its caption
    # The text goes as a message of its own, so a link preview can be shown.
    link_preview_possible: bool = False

    def messages(self) -> List[PlannedMessage]:
        """Every message, in the order it is sent."""
        out: List[PlannedMessage] = []

        def text_message(pair) -> PlannedMessage:
            text, entities = pair
            return PlannedMessage("text", text, tuple(entities or ()), link_preview=self.text_link_preview)

        if self.leading_text is not None:
            out.append(text_message(self.leading_text))
        for index, group in enumerate(self.groups):
            caption, caption_entities = self.group_captions.get(index, ("", []))
            out.append(PlannedMessage("media", caption, tuple(caption_entities or ()), group=group))
        if self.trailing_text is not None:
            out.append(text_message(self.trailing_text))
        return out


def build_media_send_plan(
    attachments: List[Attachment],
    message_text: str,
    message_entities: List[TypeMessageEntity],
    options: Optional[MessageOptions] = None,
    caption_limit: int = DEFAULT_CAPTION_LIMIT,
    validate: bool = True,
) -> MediaSendPlan:
    """The send plan. `validate=False` is for the preview, which draws the
    plan even for files that have since moved -- the send itself always
    validates."""
    if validate:
        for attachment in attachments:
            attachment.validate_exists()
            attachment.validate_readable()

    options = options or MessageOptions()
    groups = build_send_groups(attachments)
    message_text = message_text or ""
    message_entities = message_entities or []
    length = utf16_len(message_text)
    plan = MediaSendPlan(groups=groups, caption_limit=caption_limit, text_length=length)

    if not message_text:
        return plan

    if not groups:
        plan.leading_text = (message_text, message_entities)
        plan.link_preview_possible = True
        plan.text_link_preview = effective_link_preview(message_text, message_entities, options)
        return plan

    if length <= caption_limit:
        # A caption: Telegram shows no link preview there.
        plan.group_captions = {0: (message_text, message_entities)}
        return plan

    # Too long for a caption: the text goes as its own message, never
    # silently dropped (spec item 20) -- before the media unless the user
    # chose the media first; the media then carries no caption.
    logger.info(
        "Текст сообщения (%d симв.) превышает лимит подписи (%d) -- "
        "отправляется отдельным сообщением",
        length,
        caption_limit,
    )
    plan.caption_overflow = True
    plan.link_preview_possible = True
    plan.text_link_preview = effective_link_preview(message_text, message_entities, options)
    if options.order == MediaTextOrder.MEDIA_FIRST:
        plan.trailing_text = (message_text, message_entities)
    else:
        plan.leading_text = (message_text, message_entities)
    return plan


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

    for message in plan.messages():
        if message.kind == "text":
            steps.append(_text_step(client, entity, message))
            continue
        caption_text, caption_entities = message.text, list(message.entities)
        files = [str(a.path) for a in message.group.attachments]

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


def _text_step(client: TelegramClient, entity, message: PlannedMessage) -> SendStep:
    text, entities, preview = message.text, list(message.entities), message.link_preview
    if preview is None:

        async def _send_text() -> None:
            # Explicitly without a preview: left to itself, Telegram would
            # pick the first link and show a preview nobody chose.
            await client.send_message(entity, text, formatting_entities=entities or None, link_preview=False)

        return _send_text

    async def _send_text_with_preview() -> None:
        # The chosen link's preview, wherever it is in the text: the text
        # is sent with an InputMediaWebPage (layer 167+). optional=True
        # still sends the text if Telegram can't build that page.
        peer = await client.get_input_entity(entity)
        media = InputMediaWebPage(
            url=preview.url,
            force_large_media=True if preview.size == PreviewSize.LARGE else None,
            force_small_media=True if preview.size == PreviewSize.SMALL else None,
            optional=True,
        )
        await client(
            SendMediaRequest(
                peer=peer,
                media=media,
                message=text,
                entities=entities or None,
                invert_media=True if preview.above_text else None,
            )
        )

    return _send_text_with_preview


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
