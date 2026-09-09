"""Per-recipient `{name}` placeholder expansion.

Message templates may contain the literal token `{name}`, which must be
replaced with each recipient's Telegram first_name immediately before that
recipient's message is sent (never once, globally, before the campaign
starts -- app.campaign.campaign_manager calls expand_name_placeholder once
per recipient, using the same template text/entities every time).

Because Telegram message entity offsets are UTF-16 code units (see
app.ui.message_editor's module docstring), a naive str.replace() after
entities have already been computed would silently corrupt every entity
that starts at or after the first replacement whenever the resolved name's
UTF-16 length differs from len("{name}"). This module instead remaps each
entity's offset/length through the exact set of replacements performed.
"""
from __future__ import annotations

import copy
from typing import List, Optional, Tuple

from telethon.helpers import add_surrogate, del_surrogate
from telethon.tl.types import TypeMessageEntity

PLACEHOLDER = "{name}"
_PLACEHOLDER_LEN = len(PLACEHOLDER)  # ASCII-only token, UTF-16 length == len()


def expand_name_placeholder(
    text: str,
    entities: List[TypeMessageEntity],
    first_name: Optional[str],
) -> Tuple[str, List[TypeMessageEntity]]:
    """Replace every `{name}` occurrence in `text` with `first_name` (or an
    empty string if unavailable), returning a new (text, entities) pair with
    offsets/lengths correctly remapped. Never mutates the inputs -- the same
    template is reused for every recipient in a campaign."""
    if PLACEHOLDER not in text:
        return text, entities

    surrogate_text = add_surrogate(text)
    name_surrogate = add_surrogate(first_name or "")

    occurrences: List[Tuple[int, int, int]] = []  # (start, end, delta)
    delta = len(name_surrogate) - _PLACEHOLDER_LEN
    search_from = 0
    while True:
        start = surrogate_text.find(PLACEHOLDER, search_from)
        if start == -1:
            break
        end = start + _PLACEHOLDER_LEN
        occurrences.append((start, end, delta))
        search_from = end

    if not occurrences:
        return text, entities

    def map_position(pos: int) -> int:
        shift = 0
        for start, end, occ_delta in occurrences:
            if pos <= start:
                return pos + shift
            if pos < end:
                if pos - start <= end - pos:
                    return start + shift
                return start + shift + len(name_surrogate)
            shift += occ_delta
        return pos + shift

    parts: List[str] = []
    cursor = 0
    for start, end, _ in occurrences:
        parts.append(surrogate_text[cursor:start])
        parts.append(name_surrogate)
        cursor = end
    parts.append(surrogate_text[cursor:])
    new_surrogate_text = "".join(parts)

    new_entities: List[TypeMessageEntity] = []
    for entity in entities:
        new_offset = map_position(entity.offset)
        new_end = map_position(entity.offset + entity.length)
        new_length = max(0, new_end - new_offset)
        if new_length == 0:
            continue
        new_entity = copy.copy(entity)
        new_entity.offset = new_offset
        new_entity.length = new_length
        new_entities.append(new_entity)

    return del_surrogate(new_surrogate_text), new_entities
