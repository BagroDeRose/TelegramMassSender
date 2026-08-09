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

from app.telegram.media_sender import Attachment, build_media_send_plan, send_media_plan


async def send_to_recipient(
    client: TelegramClient,
    entity,
    text: str,
    entities: List[TypeMessageEntity],
    attachments: Optional[List[Attachment]] = None,
) -> None:
    attachments = attachments or []
    if attachments:
        plan = build_media_send_plan(attachments, text, entities)
        await send_media_plan(client, entity, plan)
    else:
        await client.send_message(entity, text, formatting_entities=entities or None)
