"""CSV recipient import (ROADMAP: Smart Recipient Import).

Column detection is content-based, not header-based: for each row, every
cell is tried against parse_recipient_line, and the first cell that
parses as a valid username/ID/phone becomes that row's recipient
identifier. This works regardless of column order or header names, and
reuses the exact same recipient-format recognition the manual paste box
and TXT import already use (app.recipients.parser) -- there is still only
one definition of "what a recipient identifier looks like."

Any other non-empty cell in the same row that does NOT itself parse as a
recipient identifier becomes that row's display name (the first such cell,
by column order, wins) -- used to override the {name} placeholder for
that specific recipient at send time (app.campaign.campaign_manager),
distinct from the single example name used for the on-screen preview
(app.ui.main_window/app.ui.campaign_wizard).

A header row (e.g. "username,name") contributes no valid identifier
itself -- plain words don't parse as a username/ID/phone/t.me link -- so
it is naturally reported as an invalid row rather than becoming a
phantom recipient. No separate header detection is needed.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app.i18n import tr
from app.recipients.parser import ParsedRecipient, dedupe_recipients, parse_recipient_line


class CsvImportError(Exception):
    """Raised when the file can't be read/decoded/parsed as CSV at all."""


@dataclass
class CsvImportResult:
    parsed: List[ParsedRecipient] = field(default_factory=list)
    names: Dict[str, str] = field(default_factory=dict)  # normalized_key -> display name
    total_rows: int = 0
    duplicates_removed: int = 0
    invalid_count: int = 0

    @property
    def valid_recipients(self) -> List[ParsedRecipient]:
        return [p for p in self.parsed if p.is_valid]


def _sniff_dialect(sample: str):
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel  # comma-delimited fallback -- the common case when sniffing is inconclusive


def import_recipients_from_csv(file_path: Path) -> CsvImportResult:
    try:
        with open(file_path, "r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            dialect = _sniff_dialect(sample)
            rows = list(csv.reader(handle, dialect))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise CsvImportError(str(exc)) from exc

    parsed: List[ParsedRecipient] = []
    names: Dict[str, str] = {}
    total_rows = 0
    invalid_count = 0

    for row in rows:
        cells = [c.strip() for c in row if c.strip()]
        if not cells:
            continue  # fully blank row
        total_rows += 1

        identifier: Optional[ParsedRecipient] = None
        name: Optional[str] = None
        for cell in cells:
            candidate = parse_recipient_line(cell)
            if candidate.is_valid:
                if identifier is None:
                    identifier = candidate
            elif name is None:
                name = cell

        if identifier is None:
            invalid_count += 1
            parsed.append(
                ParsedRecipient(
                    raw=", ".join(cells),
                    kind=None,
                    value=None,
                    is_valid=False,
                    error=tr("csv_importer.error.no_identifier_in_row"),
                )
            )
            continue

        parsed.append(identifier)
        if name:
            names[identifier.normalized_key] = name

    deduped, duplicates_removed = dedupe_recipients(parsed)
    surviving_keys = {p.normalized_key for p in deduped if p.is_valid}
    names = {key: value for key, value in names.items() if key in surviving_keys}

    return CsvImportResult(
        parsed=deduped,
        names=names,
        total_rows=total_rows,
        duplicates_removed=duplicates_removed,
        invalid_count=invalid_count,
    )
