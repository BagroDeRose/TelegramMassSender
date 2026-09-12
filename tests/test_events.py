"""Tests for app.logging.events (ROADMAP: Structured Logging) -- one JSON
object per log line through the existing rotating/secret-scrubbing
handler, never message contents or credentials.
"""
from __future__ import annotations

import json
import logging

from app.logging.events import EventType, log_event
from app.logging.logger import LOGGER_NAME


def test_log_event_writes_one_json_line(caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        log_event(EventType.CAMPAIGN_STARTED, recipient_count=5, min_delay_seconds=10, max_delay_seconds=20)

    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(records) == 1
    message = records[0].getMessage()
    assert message.startswith("EVENT ")
    payload = json.loads(message[len("EVENT "):])
    assert payload == {
        "event": "CAMPAIGN_STARTED",
        "recipient_count": 5,
        "min_delay_seconds": 10,
        "max_delay_seconds": 20,
    }


def test_log_event_serializes_every_declared_event_type(caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        for event_type in EventType:
            log_event(event_type, sample_field="x")

    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(records) == len(EventType)
    logged_events = {json.loads(r.getMessage()[len("EVENT "):])["event"] for r in records}
    assert logged_events == {e.value for e in EventType}


def test_log_event_never_needs_message_text_or_credentials_fields():
    # Documentation-as-test: the roadmap's event vocabulary has no field
    # for message text or credentials -- this just pins the enum members
    # to the spec'd set so an accidental rename/addition is caught.
    assert {e.value for e in EventType} == {
        "CAMPAIGN_STARTED",
        "RECIPIENT_RESOLVED",
        "MESSAGE_SENT",
        "ATTACHMENT_SENT",
        "FLOOD_WAIT",
        "RECIPIENT_FAILED",
        "CAMPAIGN_COMPLETED",
    }
