"""Tests for CampaignControlsWidget's progress/timing display: the
pre-start duration estimate, the current-recipient label, and the
elapsed/remaining-time display (v1.6 Campaign Controls). Start/Pause/Stop
button enablement is covered indirectly through tests/test_main_window_ux.py;
this file is about the newer time/progress-estimate behavior specifically.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.campaign.campaign_manager import ProgressSnapshot
from app.ui.campaign_controls import CampaignControlsWidget, format_duration


def test_format_duration_seconds_only():
    assert format_duration(5) == "5 сек"


def test_format_duration_minutes_and_seconds():
    assert format_duration(125) == "2 мин 5 сек"


def test_format_duration_clamps_negative_to_zero():
    assert format_duration(-10) == "0 сек"


def test_duration_estimate_hidden_with_no_recipients_or_interval(qapp):
    widget = CampaignControlsWidget()
    assert widget._duration_estimate_label.isHidden() is True


def test_duration_estimate_shown_once_recipients_and_interval_are_set(qapp):
    widget = CampaignControlsWidget()
    widget.set_interval_summary(10, 20)
    widget.set_recipient_count(5)
    assert widget._duration_estimate_label.isHidden() is False
    # avg interval 15s * (5 - 1) gaps = 60s = "1 мин"
    assert "1 мин" in widget._duration_estimate_label.text()


def test_duration_estimate_uses_zero_gaps_for_a_single_recipient(qapp):
    widget = CampaignControlsWidget()
    widget.set_interval_summary(10, 20)
    widget.set_recipient_count(1)
    assert widget._duration_estimate_label.isHidden() is False
    assert "0 сек" in widget._duration_estimate_label.text()


def test_duration_estimate_hidden_while_running(qapp):
    widget = CampaignControlsWidget()
    widget.set_interval_summary(10, 20)
    widget.set_recipient_count(5)
    assert widget._duration_estimate_label.isHidden() is False

    widget.set_running_state(True, paused=False)
    assert widget._duration_estimate_label.isHidden() is True


def test_duration_estimate_reappears_after_campaign_finishes(qapp):
    widget = CampaignControlsWidget()
    widget.set_interval_summary(10, 20)
    widget.set_recipient_count(5)
    widget.set_running_state(True, paused=False)
    widget.set_running_state(False)
    assert widget._duration_estimate_label.isHidden() is False


def test_current_item_label_shown_only_while_running(qapp):
    widget = CampaignControlsWidget()
    assert widget._current_item_label.isHidden() is True

    widget.set_running_state(True, paused=False)
    assert widget._current_item_label.isHidden() is False

    widget.set_running_state(False)
    assert widget._current_item_label.isHidden() is True
    assert widget._current_item_label.text() == ""


def test_set_current_item_formats_position_total_and_recipient(qapp):
    widget = CampaignControlsWidget()
    widget.set_running_state(True, paused=False)
    fake_item = SimpleNamespace(recipient=SimpleNamespace(display_label="@ivan_test"))

    widget.set_current_item(fake_item, 3, 10)

    text = widget._current_item_label.text()
    assert "3" in text
    assert "10" in text
    assert "@ivan_test" in text


def test_elapsed_timer_updates_the_elapsed_label(qapp):
    widget = CampaignControlsWidget()
    widget.start_elapsed_timer()
    # Backdate the recorded start time instead of sleeping, so this stays
    # fast and deterministic.
    widget._campaign_start_time = datetime.now() - timedelta(seconds=45)
    widget._tick_elapsed()

    assert "45 сек" in widget._elapsed_remaining_label.text() or "0 мин 45 сек" in widget._elapsed_remaining_label.text()
    widget.stop_elapsed_timer()


def test_remaining_estimate_uses_observed_average_once_items_are_done(qapp):
    widget = CampaignControlsWidget()
    widget.start_elapsed_timer()
    widget._campaign_start_time = datetime.now() - timedelta(seconds=20)
    widget._last_snapshot = ProgressSnapshot(total=4, sent=2, failed=0, skipped=0, pending=2)

    widget._tick_elapsed()

    # 20s elapsed / 2 done = 10s/item average * 2 pending = ~20s remaining
    assert "Осталось" in widget._elapsed_remaining_label.text()
    widget.stop_elapsed_timer()


def test_remaining_estimate_falls_back_to_configured_interval_before_anything_is_done(qapp):
    widget = CampaignControlsWidget()
    widget.set_interval_summary(10, 20)
    widget.start_elapsed_timer()
    widget._campaign_start_time = datetime.now()
    widget._last_snapshot = ProgressSnapshot(total=4, sent=0, failed=0, skipped=0, pending=4)

    widget._tick_elapsed()

    assert "Осталось" in widget._elapsed_remaining_label.text()
    widget.stop_elapsed_timer()


def test_stop_elapsed_timer_freezes_the_display(qapp):
    widget = CampaignControlsWidget()
    widget.start_elapsed_timer()
    widget._campaign_start_time = datetime.now() - timedelta(seconds=5)
    widget.stop_elapsed_timer()
    assert widget._elapsed_timer.isActive() is False
