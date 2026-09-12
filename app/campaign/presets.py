"""Named message presets: explicit save/load of a message's text,
formatting, attachments, and (optionally) the campaign interval -- never
automatic message history (spec: presets must be a deliberate, named
save/load action, not a log of everything ever typed).

A preset row only exists because the user clicked "Save as preset";
nothing here writes to the presets table on its own. The actual entity
objects (rich Telethon TL types) and attachment Path objects are never
stored directly -- SQLite only holds JSON-serializable data -- so this
module owns the round-trip between the two, plus the missing-attachment
handling a preset needs: a file referenced by a saved preset may have been
moved or deleted since it was saved, and loading a preset must surface
that clearly rather than silently building a campaign around a
nonexistent file.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

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

from app.database.models import Preset
from app.database.repositories import PresetRepository
from app.i18n import tr

# Exactly the entity types app.ui.message_editor.extract_message_content
# ever produces -- an entity type outside this set could only reach here
# from data this app itself never wrote (or a future editor feature that
# forgot to register its entity type here too).
_ENTITY_CLASSES_BY_NAME = {
    "MessageEntityBold": MessageEntityBold,
    "MessageEntityItalic": MessageEntityItalic,
    "MessageEntityUnderline": MessageEntityUnderline,
    "MessageEntityStrike": MessageEntityStrike,
    "MessageEntityCode": MessageEntityCode,
    "MessageEntityPre": MessageEntityPre,
    "MessageEntitySpoiler": MessageEntitySpoiler,
    "MessageEntityTextUrl": MessageEntityTextUrl,
}


class PresetError(Exception):
    """Raised for a preset row whose stored data can't be decoded -- a
    corrupted/hand-edited DB row, not an expected runtime condition."""


def _serialize_entities(entities: List[TypeMessageEntity]) -> str:
    return json.dumps([e.to_dict() for e in entities])


def _deserialize_entities(raw: str) -> List[TypeMessageEntity]:
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PresetError(tr("presets.error.corrupted")) from exc

    entities: List[TypeMessageEntity] = []
    for item in items:
        kind = item.get("_")
        cls = _ENTITY_CLASSES_BY_NAME.get(kind)
        if cls is None:
            continue  # forward-compat: skip an entity type this version doesn't know, don't crash
        kwargs = {k: v for k, v in item.items() if k != "_"}
        entities.append(cls(**kwargs))
    return entities


def _serialize_paths(paths: List[Path]) -> str:
    return json.dumps([str(p) for p in paths])


def _deserialize_paths(raw: str) -> List[Path]:
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PresetError(tr("presets.error.corrupted")) from exc
    return [Path(p) for p in items]


@dataclass
class LoadedPreset:
    """A preset's stored data, decoded back into real objects and checked
    against the current filesystem -- attachment_paths only ever contains
    files that still exist; missing_attachment_names lists what didn't, by
    filename, so the caller can warn the user instead of silently building
    a campaign around a file that's gone."""

    message_text: str
    message_entities: List[TypeMessageEntity]
    attachment_paths: List[Path]
    missing_attachment_names: List[str] = field(default_factory=list)
    min_delay_seconds: Optional[int] = None
    max_delay_seconds: Optional[int] = None


def save_preset(
    repo: PresetRepository,
    name: str,
    message_text: str,
    message_entities: List[TypeMessageEntity],
    attachment_paths: List[Path],
    min_delay_seconds: Optional[int] = None,
    max_delay_seconds: Optional[int] = None,
) -> Preset:
    display_name = name.strip() or tr("presets.untitled_name")
    return repo.create(
        display_name,
        message_text,
        _serialize_entities(message_entities),
        _serialize_paths(attachment_paths),
        min_delay_seconds,
        max_delay_seconds,
    )


def list_presets(repo: PresetRepository) -> List[Preset]:
    return repo.list_all()


def rename_preset(repo: PresetRepository, preset_id: int, new_name: str) -> None:
    repo.rename(preset_id, new_name.strip() or tr("presets.untitled_name"))


def delete_preset(repo: PresetRepository, preset_id: int) -> None:
    repo.delete(preset_id)


def load_preset(preset: Preset) -> LoadedPreset:
    entities = _deserialize_entities(preset.message_entities)
    all_paths = _deserialize_paths(preset.attachment_paths)
    existing = [p for p in all_paths if p.is_file()]
    missing = [p.name for p in all_paths if not p.is_file()]
    return LoadedPreset(
        message_text=preset.message_text,
        message_entities=entities,
        attachment_paths=existing,
        missing_attachment_names=missing,
        min_delay_seconds=preset.min_delay_seconds,
        max_delay_seconds=preset.max_delay_seconds,
    )
