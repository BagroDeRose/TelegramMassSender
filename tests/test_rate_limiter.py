"""Rate limiter tests (spec item 58): min/max bounds, min<=max, random
delay stays within range, and the sanity floor rejects unreasonable
values without turning delay configuration into a rate-limit workaround.
"""
from __future__ import annotations

import pytest

from app.campaign.rate_limiter import RateLimiter
from app.config.settings import MIN_ALLOWED_DELAY_SECONDS, SettingsValidationError


def test_next_delay_within_bounds():
    limiter = RateLimiter(5, 10)
    for _ in range(200):
        delay = limiter.next_delay()
        assert 5 <= delay <= 10


def test_min_equals_max_is_allowed_and_deterministic():
    limiter = RateLimiter(7, 7)
    assert limiter.next_delay() == 7


def test_min_greater_than_max_rejected():
    with pytest.raises(SettingsValidationError):
        RateLimiter(10, 5)


def test_below_floor_rejected():
    with pytest.raises(SettingsValidationError):
        RateLimiter(MIN_ALLOWED_DELAY_SECONDS - 1, 10)


def test_zero_or_negative_rejected():
    with pytest.raises(SettingsValidationError):
        RateLimiter(0, 10)
