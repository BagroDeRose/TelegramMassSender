"""Streaming TXT import of recipient lists (spec item 13).

A plain Python file iterator already reads lazily line-by-line, so this
scales to large files without loading the whole file into memory --
no need for extra streaming machinery on top of it.
"""
from __future__ import annotations

from pathlib import Path

from app.recipients.parser import ParseSummary, parse_recipient_lines


def import_recipients_from_txt(file_path: Path) -> ParseSummary:
    # utf-8-sig transparently strips a BOM (common when files are saved by
    # Notepad); errors="replace" ensures a stray bad byte cannot abort the
    # whole import (spec: malformed lines must not break the import).
    with open(file_path, "r", encoding="utf-8-sig", errors="replace") as handle:
        return parse_recipient_lines(handle)
