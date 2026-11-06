"""Send a single, fully-formed message (text + optional attachments) to
one already-resolved Telegram recipient.

Used by the campaign engine (app.campaign.campaign_manager) once per
recipient; retry/pause/FloodWait handling lives one layer up -- this
module only knows how to perform one send attempt and let exceptions
propagate for the caller to categorize.
"""
from __future__ import annotations

from typing import List, Optional

from telethon import TelegramClient
from telethon.tl.types import TypeMessageEntity

from app.telegram.media_sender import (
    Attachment,
    SendProgress,
    build_media_send_plan,
    send_media_plan,
)
from app.telegram.message_options import DEFAULT_CAPTION_LIMIT, MessageOptions


async def send_to_recipient(
    client: TelegramClient,
    entity,
    text: str,
    entities: List[TypeMessageEntity],
    attachments: Optional[List[Attachment]] = None,
    start_step: int = 0,
    progress: Optional[SendProgress] = None,
    options: Optional[MessageOptions] = None,
    caption_limit: int = DEFAULT_CAPTION_LIMIT,
) -> None:
    """Send one fully-formed message. `start_step`/`progress` support
    resuming a multi-step plan (message text + attachments can require more
    than one Telegram call) after a partial failure, without repeating any
    step that already completed -- see app.campaign.campaign_manager.

    The plan is the same one the preview draws (build_media_send_plan):
    caption or separate text, the order, the link preview."""
    plan = build_media_send_plan(attachments or [], text, entities, options=options, caption_limit=caption_limit)
    await send_media_plan(client, entity, plan, start_step=start_step, progress=progress)
