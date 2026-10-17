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
    # How many delivery steps of this item's send plan have already
    # completed (in-memory only, this run's lifetime -- see
    # app.campaign.campaign_manager and app.telegram.media_sender). A
    # retry or a FloodWait resume must start from here, never from 0, so an
    # already-delivered step (e.g. one attachment out of several) is never
    # sent again.
    next_step: int = 0
    # Populated once the recipient is successfully resolved to a Telegram
    # user or chat (app.campaign.campaign_manager); used only for the CSV
    # report (app.campaign.report) -- never logged. For a chat target
    # resolved_id is the marked id (-100.../-...), so it can be pasted back
    # as a recipient.
    resolved_id: Optional[int] = None
    resolved_username: Optional[str] = None
    # app.telegram.chat_targets.TargetType value ("user", "group",
    # "supergroup", "forum", "channel") once resolved; None before that.
    target_type: Optional[str] = None
    # ISO-8601 timestamp stamped when this item reaches a terminal status
    # (SENT/FAILED/SKIPPED); left None for an item never attempted.
    sent_at: Optional[str] = None


class SendQueue:
    def __init__(self, recipients: List[ParsedRecipient], resume_steps: Optional[Dict[str, int]] = None) -> None:
        # resume_steps: normalized_key -> delivery steps an earlier run
        # already completed for that recipient (Retry), so they're not
        # sent a second time.
        resume_steps = resume_steps or {}
        self._items: List[SendItem] = [
            SendItem(recipient=r, next_step=max(0, int(resume_steps.get(r.normalized_key, 0)))) for r in recipients
        ]

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
