"""Structured campaign event logging (ROADMAP: Structured Logging).

Each event is one JSON object per log line, written through the same
rotating, secret-scrubbing handler app.logging.logger already sets up
(SecretScrubbingFilter runs on every record regardless of shape) -- so
this is one logging pipeline, not a second log file to manage.

Fields never include message text, credentials, or session data -- only
what app.campaign.campaign_manager's existing human-readable journal
messages already surface (recipient display labels, counts, timings),
structured instead of interpolated into a sentence. A recipient's
display label (e.g. "@username" or "+491234567") is operational data
already logged today via the journal, not a credential.
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

from app.logging.logger import get_logger


class EventType(Enum):
    CAMPAIGN_STARTED = "CAMPAIGN_STARTED"
    RECIPIENT_RESOLVED = "RECIPIENT_RESOLVED"
    MESSAGE_SENT = "MESSAGE_SENT"
    ATTACHMENT_SENT = "ATTACHMENT_SENT"
    FLOOD_WAIT = "FLOOD_WAIT"
    RECIPIENT_FAILED = "RECIPIENT_FAILED"
    CAMPAIGN_COMPLETED = "CAMPAIGN_COMPLETED"


def log_event(event_type: EventType, **fields: Any) -> None:
    payload = {"event": event_type.value, **fields}
    get_logger().info("EVENT %s", json.dumps(payload, ensure_ascii=False, default=str))
