"""Randomized delay between sends within a user-configured [min, max]
range (spec items 22-23, 43).

This governs how fast this application issues its own requests -- it is
not, and must never become, a mechanism for working around Telegram's
own rate limits. See app.campaign.campaign_manager for FloodWaitError
handling, which never retries around a flood wait.
"""
from __future__ import annotations

import random

from app.config.settings import validate_delay_range


class RateLimiter:
    def __init__(self, min_delay_seconds: float, max_delay_seconds: float) -> None:
        validate_delay_range(min_delay_seconds, max_delay_seconds)
        self.min_delay_seconds = min_delay_seconds
        self.max_delay_seconds = max_delay_seconds

    def next_delay(self) -> float:
        return random.uniform(self.min_delay_seconds, self.max_delay_seconds)
