"""Launch / progress panel (right column of the Campaign page).

Idle: a summary of what will happen (people, groups/channels,
attachments, interval, time estimate) and the page's single primary
action, "Start campaign".
Running: the same panel turns into progress -- state, a progress bar,
"7 of 12", the current recipient, sent/failed/skipped counters,
elapsed/remaining, Pause/Resume and Stop. A FloodWait shows its own block
with a countdown and a Continue button.

The interval is configured in Settings; this panel only summarises it and
links there.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.campaign.campaign_manager import ProgressSnapshot
from app.i18n import tr
from app.ui import icons, theme
from app.ui.motion import fade_in
from app.ui.theme import MOTION_SLOW_MS, SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XS

_ELAPSED_TICK_MS = 1000
_PROGRESS_SCALE = 1000  # progress bar resolution (per-mille) for smooth motion


def format_duration(total_seconds: float) -> str:
    minutes, seconds = divmod(max(0, int(total_seconds)), 60)
    if minutes:
        return tr("main_window.duration.minutes_seconds", minutes=minutes, seconds=seconds)
    return tr("main_window.duration.seconds", seconds=seconds)


def format_countdown(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, int(total_seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _label(text: str, object_name: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(object_name)
    return label


class CampaignControlsWidget(QFrame):
    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    export_report_requested = Signal()
    open_settings_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("launchPanel")
        self._running = False
        self._is_paused = False
        self._start_ready = False
        self._interval_min: Optional[int] = None
        self._interval_max: Optional[int] = None
        self._last_snapshot: Optional[ProgressSnapshot] = None
        self._recipient_count = 0
        self._chat_count = 0
        self._attachment_count = 0
        self._flood_remaining: Optional[int] = None
        self._campaign_start_time: Optional[datetime] = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_LG)
        outer.setSpacing(SPACE_MD)

        self._title = _label(tr("campaign_controls.title_ready"), "launchTitle", self)
        outer.addWidget(self._title)

        self._pages = QStackedWidget(self)
        self._pages.addWidget(self._build_idle_page())
        self._pages.addWidget(self._build_run_page())
        outer.addWidget(self._pages)

        self._status_label = _label("", "statusLabel", self)
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        outer.addWidget(self._status_label)

        self._export_report_button = QPushButton(tr("campaign_controls.export_report_button"), self)
        self._export_report_button.setProperty("variant", "ghost")
        self._export_report_button.setIcon(icons.themed("export"))
        self._export_report_button.setToolTip(tr("campaign_controls.export_report_tooltip"))
        self._export_report_button.setEnabled(False)
        self._export_report_button.setVisible(False)
        self._export_report_button.clicked.connect(self.export_report_requested.emit)
        outer.addWidget(self._export_report_button, 0, Qt.AlignmentFlag.AlignLeft)

        self._update_start_enabled()
        self.set_running_state(False)

    # ---- construction -------------------------------------------------------------

    def _build_idle_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_LG)

        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACE_MD)
        grid.setVerticalSpacing(SPACE_SM)
        grid.setColumnStretch(1, 1)
        self._people_key = _label(tr("campaign_controls.summary_people"), "summaryKey", page)
        self._people_value = _label("0", "summaryValue", page)
        self._chats_key = _label(tr("campaign_controls.summary_chats"), "summaryKey", page)
        self._chats_value = _label("0", "summaryValue", page)
        self._attachments_key = _label(tr("campaign_controls.summary_attachments"), "summaryKey", page)
        self._attachments_value = _label("0", "summaryValue", page)
        self._interval_key = _label(tr("campaign_controls.summary_interval"), "summaryKey", page)
        interval_cell = QHBoxLayout()
        interval_cell.setSpacing(SPACE_XS)
        self._interval_summary_label = _label("—", "summaryValue", page)
        interval_cell.addWidget(self._interval_summary_label)
        self._change_interval_button = QPushButton(tr("campaign_controls.edit_in_settings_button"), page)
        self._change_interval_button.setObjectName("toolbarButton")
        self._change_interval_button.clicked.connect(self.open_settings_requested.emit)
        interval_cell.addWidget(self._change_interval_button)
        interval_cell.addStretch(1)
        self._estimate_key = _label(tr("campaign_controls.summary_estimate"), "summaryKey", page)
        self._duration_estimate_label = _label("", "summaryValue", page)
        rows = (
            (self._people_key, self._people_value),
            (self._chats_key, self._chats_value),
            (self._attachments_key, self._attachments_value),
            (self._interval_key, interval_cell),
            (self._estimate_key, self._duration_estimate_label),
        )
        for row, (key, value) in enumerate(rows):
            grid.addWidget(key, row, 0)
            if isinstance(value, QHBoxLayout):
                grid.addLayout(value, row, 1)
            else:
                grid.addWidget(value, row, 1)
        layout.addLayout(grid)

        self._start_button = QPushButton(tr("campaign_controls.start_button"), page)
        self._start_button.setProperty("variant", "primary")
        self._start_button.setIcon(icons.themed("start", "on_accent"))
        self._start_button.setToolTip(tr("campaign_controls.start_tooltip"))
        self._start_button.clicked.connect(self.start_requested.emit)
        layout.addWidget(self._start_button)
        return page

    def _build_run_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_MD)

        head = QHBoxLayout()
        self._state_pill = _label("", "pill", page)
        head.addWidget(self._state_pill)
        head.addStretch(1)
        self._done_label = _label("0 / 0", "bigCounter", page)
        head.addWidget(self._done_label)
        layout.addLayout(head)

        self._progress_bar = QProgressBar(page)
        self._progress_bar.setRange(0, _PROGRESS_SCALE)
        self._progress_bar.setTextVisible(False)
        self._progress_animation = QPropertyAnimation(self._progress_bar, b"value", self)
        self._progress_animation.setDuration(MOTION_SLOW_MS)
        self._progress_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        layout.addWidget(self._progress_bar)

        self._current_item_label = _label("", "helperText", page)
        self._current_item_label.setWordWrap(True)
        layout.addWidget(self._current_item_label)

        counters = QHBoxLayout()
        counters.setSpacing(SPACE_LG)
        self._sent_counter = self._counter(page, counters, "success", "campaign_controls.counter_sent")
        self._failed_counter = self._counter(page, counters, "error", "campaign_controls.counter_failed")
        self._skipped_counter = self._counter(page, counters, "", "campaign_controls.counter_skipped")
        counters.addStretch(1)
        layout.addLayout(counters)

        # Full sentence kept for screen readers / existing callers.
        self._stats_label = _label(
            tr("campaign_controls.stats_line", total=0, sent=0, failed=0, skipped=0, pending=0), "summaryLabel", page
        )
        self._stats_label.setVisible(False)
        layout.addWidget(self._stats_label)

        self._elapsed_remaining_label = _label("", "helperText", page)
        layout.addWidget(self._elapsed_remaining_label)

        self._flood_block = QFrame(page)
        self._flood_block.setObjectName("floodBlock")
        flood_layout = QVBoxLayout(self._flood_block)
        flood_layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        flood_layout.setSpacing(SPACE_XS)
        self._flood_title = _label(tr("campaign_controls.flood_title"), "floodTitle", self._flood_block)
        flood_layout.addWidget(self._flood_title)
        self._flood_countdown = _label("00:00", "floodCountdown", self._flood_block)
        flood_layout.addWidget(self._flood_countdown)
        self._flood_text = _label(tr("campaign_controls.flood_text"), "helperText", self._flood_block)
        self._flood_text.setWordWrap(True)
        flood_layout.addWidget(self._flood_text)
        self._flood_continue_button = QPushButton(tr("campaign_controls.resume_button"), self._flood_block)
        self._flood_continue_button.setIcon(icons.themed("resume"))
        self._flood_continue_button.clicked.connect(self.resume_requested.emit)
        flood_layout.addWidget(self._flood_continue_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._flood_block.setVisible(False)
        layout.addWidget(self._flood_block)

        actions = QHBoxLayout()
        actions.setSpacing(SPACE_SM)
        self._pause_button = QPushButton(tr("campaign_controls.pause_button"), page)
        self._pause_button.setIcon(icons.themed("pause"))
        self._pause_button.clicked.connect(self._on_pause_clicked)
        self._stop_button = QPushButton(tr("campaign_controls.stop_button"), page)
        self._stop_button.setProperty("variant", "danger")
        self._stop_button.setIcon(icons.themed("stop", "error"))
        self._stop_button.clicked.connect(self.stop_requested.emit)
        actions.addWidget(self._pause_button, 1)
        actions.addWidget(self._stop_button, 1)
        layout.addLayout(actions)
        return page

    def _counter(self, parent: QWidget, row: QHBoxLayout, status: str, key: str) -> QLabel:
        cell = QVBoxLayout()
        cell.setSpacing(0)
        value = _label("0", "summaryValue", parent)
        value.setProperty("status", status)
        caption = _label(tr(key), "helperText", parent)
        caption.setProperty("captionKey", key)
        cell.addWidget(value)
        cell.addWidget(caption)
        row.addLayout(cell)
        return value

    # ---- behaviour -----------------------------------------------------------------

    def _on_pause_clicked(self) -> None:
        if self._is_paused:
            self.resume_requested.emit()
        else:
            self.pause_requested.emit()

    def set_interval_summary(self, min_seconds: int, max_seconds: int) -> None:
        self._interval_min = min_seconds
        self._interval_max = max_seconds
        self._interval_summary_label.setText(tr("campaign_controls.interval_value", min=min_seconds, max=max_seconds))
        self._update_duration_estimate()

    def set_recipient_count(self, count: int) -> None:
        """Valid recipients in the box -- drives the summary and estimate."""
        self._recipient_count = count
        self._update_summary()
        self._update_duration_estimate()

    def set_recipient_breakdown(self, chat_count: int) -> None:
        """How many of the recipients are groups/channels by format."""
        self._chat_count = chat_count
        self._update_summary()

    def set_attachment_count(self, count: int) -> None:
        self._attachment_count = count
        self._update_summary()

    def _update_summary(self) -> None:
        self._people_value.setText(str(max(0, self._recipient_count - self._chat_count)))
        self._chats_value.setText(str(self._chat_count))
        self._attachments_value.setText(str(self._attachment_count))

    def _update_duration_estimate(self) -> None:
        visible = not (
            self._running or self._recipient_count <= 0 or self._interval_min is None or self._interval_max is None
        )
        self._duration_estimate_label.setVisible(visible)
        self._estimate_key.setVisible(visible)
        if not visible:
            return
        avg_interval = (self._interval_min + self._interval_max) / 2
        # count sends have (count - 1) gaps between them -- no wait after the last one.
        total_seconds = avg_interval * max(0, self._recipient_count - 1)
        self._duration_estimate_label.setText(
            tr("campaign_controls.duration_estimate", duration=format_duration(total_seconds))
        )

    def set_start_ready(self, ready: bool) -> None:
        """Proactively enable Start once an account, recipients and content
        are all present."""
        self._start_ready = ready
        self._update_start_enabled()

    def _update_start_enabled(self) -> None:
        self._start_button.setEnabled(self._start_ready and not self._running)

    def set_running_state(self, running: bool, paused: bool = False) -> None:
        was_running = self._running
        self._running = running
        self._is_paused = paused
        self._update_start_enabled()
        self._pause_button.setEnabled(running)
        self._pause_button.setText(tr("campaign_controls.resume_button") if paused else tr("campaign_controls.pause_button"))
        self._pause_button.setIcon(icons.themed("resume" if paused else "pause"))
        self._stop_button.setEnabled(running)
        self._current_item_label.setVisible(running)
        self._elapsed_remaining_label.setVisible(running)
        if not running:
            self._current_item_label.setText("")
            self.set_flood_wait(None)
        self._flood_continue_button.setEnabled(paused)
        self._sync_state_pill()
        self._pages.setCurrentIndex(1 if running else 0)
        if running != was_running and self.isVisible():
            fade_in(self._pages.currentWidget())
        self._title.setText(tr("campaign_controls.title_running") if running else tr("campaign_controls.title_ready"))
        self._update_duration_estimate()

    def _sync_state_pill(self) -> None:
        if self._flood_remaining is not None:
            text, status = tr("campaign_controls.state_flood"), "warning"
        elif self._is_paused:
            text, status = tr("campaign_controls.state_paused"), "warning"
        else:
            text, status = tr("campaign_controls.state_running"), "info"
        self._state_pill.setText(text)
        theme.set_status(self._state_pill, status)

    def set_flood_wait(self, remaining_seconds: Optional[int]) -> None:
        """Show (or, with None, hide) the FloodWait block with a countdown.
        Its Continue button only enables once the campaign has paused after
        the wait -- the wait itself is never cut short."""
        self._flood_remaining = remaining_seconds
        self._flood_block.setVisible(remaining_seconds is not None)
        if remaining_seconds is not None:
            self._flood_countdown.setText(format_countdown(remaining_seconds))
            self._flood_text.setText(
                tr("campaign_controls.flood_text_waiting") if remaining_seconds > 0 else tr("campaign_controls.flood_text")
            )
        self._sync_state_pill()

    def set_current_item(self, item, position: int, total: int) -> None:
        """Connected to CampaignManager.current_item_changed."""
        self._current_item_label.setText(
            tr("campaign_controls.current_item", position=position, total=total, recipient=item.recipient.display_label)
        )

    def start_elapsed_timer(self) -> None:
        """Called once, when a campaign actually starts."""
        self._campaign_start_time = datetime.now()
        self._elapsed_timer.start(_ELAPSED_TICK_MS)
        self._tick_elapsed()

    def stop_elapsed_timer(self) -> None:
        self._tick_elapsed()  # one last update so the final elapsed time is accurate
        self._elapsed_timer.stop()

    def elapsed_seconds(self) -> Optional[float]:
        if self._campaign_start_time is None:
            return None
        return (datetime.now() - self._campaign_start_time).total_seconds()

    def _tick_elapsed(self) -> None:
        if self._campaign_start_time is None:
            return
        elapsed_seconds = (datetime.now() - self._campaign_start_time).total_seconds()
        remaining_text = self._estimate_remaining_text(elapsed_seconds)
        if remaining_text:
            self._elapsed_remaining_label.setText(
                tr("campaign_controls.elapsed_remaining", elapsed=format_duration(elapsed_seconds), remaining=remaining_text)
            )
        else:
            self._elapsed_remaining_label.setText(tr("campaign_controls.elapsed_only", elapsed=format_duration(elapsed_seconds)))

    def _estimate_remaining_text(self, elapsed_seconds: float) -> str:
        if self._last_snapshot is None or self._last_snapshot.pending <= 0:
            return ""
        done = self._last_snapshot.sent + self._last_snapshot.failed + self._last_snapshot.skipped
        if done > 0:
            avg_per_item = elapsed_seconds / done
            return format_duration(avg_per_item * self._last_snapshot.pending)
        if self._interval_min is not None and self._interval_max is not None:
            avg_interval = (self._interval_min + self._interval_max) / 2
            return format_duration(avg_interval * self._last_snapshot.pending)
        return ""

    def update_progress(self, snapshot: ProgressSnapshot) -> None:
        self._last_snapshot = snapshot
        self._stats_label.setText(
            tr(
                "campaign_controls.stats_line",
                total=snapshot.total,
                sent=snapshot.sent,
                failed=snapshot.failed,
                skipped=snapshot.skipped,
                pending=snapshot.pending,
            )
        )
        done = snapshot.sent + snapshot.failed + snapshot.skipped
        self._done_label.setText(tr("campaign_controls.done_of_total", done=done, total=snapshot.total))
        self._sent_counter.setText(str(snapshot.sent))
        self._failed_counter.setText(str(snapshot.failed))
        self._skipped_counter.setText(str(snapshot.skipped))
        target = int(done / snapshot.total * _PROGRESS_SCALE) if snapshot.total else 0
        self._progress_animation.stop()
        self._progress_animation.setStartValue(self._progress_bar.value())
        self._progress_animation.setEndValue(target)
        self._progress_animation.start()

    def set_status_text(self, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.setVisible(bool(text))

    def set_report_available(self, available: bool) -> None:
        self._export_report_button.setEnabled(available)
        self._export_report_button.setVisible(available)

    def retranslate_ui(self) -> None:
        self._title.setText(tr("campaign_controls.title_running") if self._running else tr("campaign_controls.title_ready"))
        self._people_key.setText(tr("campaign_controls.summary_people"))
        self._chats_key.setText(tr("campaign_controls.summary_chats"))
        self._attachments_key.setText(tr("campaign_controls.summary_attachments"))
        self._interval_key.setText(tr("campaign_controls.summary_interval"))
        self._estimate_key.setText(tr("campaign_controls.summary_estimate"))
        self._change_interval_button.setText(tr("campaign_controls.edit_in_settings_button"))
        self._start_button.setText(tr("campaign_controls.start_button"))
        self._start_button.setToolTip(tr("campaign_controls.start_tooltip"))
        self._pause_button.setText(tr("campaign_controls.resume_button") if self._is_paused else tr("campaign_controls.pause_button"))
        self._stop_button.setText(tr("campaign_controls.stop_button"))
        self._flood_title.setText(tr("campaign_controls.flood_title"))
        self._flood_continue_button.setText(tr("campaign_controls.resume_button"))
        for caption in self.findChildren(QLabel):
            key = caption.property("captionKey")
            if key:
                caption.setText(tr(key))
        if self._last_snapshot is not None:
            self.update_progress(self._last_snapshot)
        else:
            self._stats_label.setText(tr("campaign_controls.stats_line", total=0, sent=0, failed=0, skipped=0, pending=0))
        self._export_report_button.setText(tr("campaign_controls.export_report_button"))
        self._export_report_button.setToolTip(tr("campaign_controls.export_report_tooltip"))
        if self._interval_min is not None and self._interval_max is not None:
            self._interval_summary_label.setText(
                tr("campaign_controls.interval_value", min=self._interval_min, max=self._interval_max)
            )
        self.set_flood_wait(self._flood_remaining)
        self._update_duration_estimate()
        if self._campaign_start_time is not None:
            self._tick_elapsed()
