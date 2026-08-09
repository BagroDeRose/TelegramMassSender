"""Deterministic send queue (spec item 45): default order is exactly the
order recipients were supplied in. Retries, double-clicking Start, or
resuming after a pause must never reorder or duplicate an item.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from app.recipients.parser import ParsedRecipient


class SendItemStatus(Enum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SendItem:
    recipient: ParsedRecipient
    status: SendItemStatus = SendItemStatus.PENDING
    error: Optional[str] = None
    attempts: int = 0


class SendQueue:
    def __init__(self, recipients: List[ParsedRecipient]) -> None:
        self._items: List[SendItem] = [SendItem(recipient=r) for r in recipients]

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    @property
    def items(self) -> List[SendItem]:
        return list(self._items)

    def next_pending(self) -> Optional[SendItem]:
        for item in self._items:
            if item.status == SendItemStatus.PENDING:
                return item
        return None

    def has_pending(self) -> bool:
        return self.next_pending() is not None

    def counts(self) -> Dict[SendItemStatus, int]:
        result = {status: 0 for status in SendItemStatus}
        for item in self._items:
            result[item.status] += 1
        return result
