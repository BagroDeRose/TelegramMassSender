"""Local recipient groups (ROADMAP: Recipient Groups) -- a named, saved
snapshot of the Recipients box's raw text plus any CSV-derived {name}
overrides (app.recipients.csv_importer), explicitly saved/loaded/renamed/
deleted by the user via app.ui.main_window.

Deliberately NOT a CRM: a group carries no tags, notes, contact history,
or per-recipient metadata beyond the {name} override recipient import
already produces. It is just "this exact recipient list, given a name so
it can be reloaded later." "Customers" / "Partners" / "Test accounts" /
"Imported lists" (from the spec) are example names a user might choose,
not built-in categories -- there is nothing in this module or its schema
that treats any group name specially.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List

from app.database.models import RecipientGroup
from app.database.repositories import RecipientGroupRepository
from app.i18n import tr


class RecipientGroupError(Exception):
    """Raised for a group row whose stored name_overrides can't be
    decoded -- a corrupted/hand-edited DB row, not an expected runtime
    condition."""


@dataclass
class LoadedRecipientGroup:
    recipients_text: str
    name_overrides: Dict[str, str]


def save_group(
    repo: RecipientGroupRepository, name: str, recipients_text: str, name_overrides: Dict[str, str]
) -> RecipientGroup:
    display_name = name.strip() or tr("recipient_groups.untitled_name")
    return repo.create(display_name, recipients_text, json.dumps(name_overrides))


def list_groups(repo: RecipientGroupRepository) -> List[RecipientGroup]:
    return repo.list_all()


def rename_group(repo: RecipientGroupRepository, group_id: int, new_name: str) -> None:
    repo.rename(group_id, new_name.strip() or tr("recipient_groups.untitled_name"))


def delete_group(repo: RecipientGroupRepository, group_id: int) -> None:
    repo.delete(group_id)


def load_group(group: RecipientGroup) -> LoadedRecipientGroup:
    try:
        overrides = json.loads(group.name_overrides)
    except json.JSONDecodeError as exc:
        raise RecipientGroupError(tr("recipient_groups.error.corrupted")) from exc
    return LoadedRecipientGroup(recipients_text=group.recipients_text, name_overrides=overrides)
