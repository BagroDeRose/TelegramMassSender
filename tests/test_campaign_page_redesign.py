"""Campaign page after the redesign: two columns that fold into one when
narrow, the launch panel's summary, its idle -> progress switch, and the
FloodWait countdown block."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.campaign.campaign_manager import ProgressSnapshot
from app.database.database import Database
from app.security.secure_storage import SecureStorage
from app.ui.campaign_controls import CampaignControlsWidget, format_countdown
from app.ui.main_window import MainWindow
from app.ui.theme import CAMPAIGN_FOLD_WIDTH, WINDOW_MIN_WIDTH


def _make_window(tmp_path: Path) -> MainWindow:
    return MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))


async def test_columns_fold_when_the_page_is_narrow_and_unfold_when_wide(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.show()
    columns = window._campaign_columns
    window.resize(1400, 800)  # page area well above the fold width
    QApplication.processEvents()
    assert columns.width() > CAMPAIGN_FOLD_WIDTH
    assert columns.is_folded is False
    assert columns._side_slot.isAncestorOf(columns.side)
    assert not columns.main.isAncestorOf(columns.side)

    window.resize(WINDOW_MIN_WIDTH, 800)
    QApplication.processEvents()
    assert columns.width() < CAMPAIGN_FOLD_WIDTH
    assert columns.is_folded is True
    assert columns.main.isAncestorOf(columns.side)
    assert window._campaign_controls.isVisibleTo(window)


def test_launch_summary_counts_people_chats_and_attachments(qapp):
    panel = CampaignControlsWidget()
    panel.set_interval_summary(10, 20)
    panel.set_recipient_breakdown(3)
    panel.set_recipient_count(12)
    panel.set_attachment_count(4)
    assert panel._people_value.text() == "9"
    assert panel._chats_value.text() == "3"
    assert panel._attachments_value.text() == "4"
    assert "10" in panel._interval_summary_label.text() and "20" in panel._interval_summary_label.text()


def test_panel_switches_between_launch_and_progress(qapp):
    panel = CampaignControlsWidget()
    assert panel._pages.currentIndex() == 0
    panel.set_running_state(True)
    assert panel._pages.currentIndex() == 1
    panel.update_progress(ProgressSnapshot(total=12, sent=5, failed=1, skipped=1, pending=5))
    assert "7" in panel._done_label.text() and "12" in panel._done_label.text()
    assert panel._sent_counter.text() == "5"
    assert panel._failed_counter.text() == "1"
    panel.set_running_state(False)
    assert panel._pages.currentIndex() == 0


def test_flood_wait_block_counts_down_and_continue_only_after_pause(qapp):
    panel = CampaignControlsWidget()
    panel.set_running_state(True)
    panel.set_flood_wait(125)
    assert panel._flood_block.isHidden() is False
    assert panel._flood_countdown.text() == format_countdown(125) == "02:05"
    assert panel._flood_continue_button.isEnabled() is False  # the wait is never cut short
    assert panel._state_pill.property("status") == "warning"

    panel.set_flood_wait(0)
    panel.set_running_state(True, paused=True)
    assert panel._flood_continue_button.isEnabled() is True
    emitted = []
    panel.resume_requested.connect(lambda: emitted.append(True))
    panel._flood_continue_button.click()
    assert emitted == [True]

    panel.set_running_state(False)
    assert panel._flood_block.isHidden() is True
