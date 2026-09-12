"""Start/Pause/Stop controls, progress display, and the CSV export button
(spec items 19-26, 30, 43).

Sending interval configuration and the standalone Test Send flow both
used to live here; they've moved out (interval -> Settings -> Sending,
now the single source of truth for that value; Test Send removed
entirely -- entering a test account into Recipients and starting a real
campaign already covers the same need with no separate code path to
maintain). See app.ui.main_window for the read-only interval summary this
widget still displays.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from app.campaign.campaign_manager import ProgressSnapshot
from app.i18n import tr
from app.ui.theme import SPACE_LG, SPACE_SM, SPACE_XS


class CampaignControlsWidget(QWidget):
    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    export_report_requested = Signal()
    open_settings_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._running = False
        self._is_paused = False
        self._start_ready = False
        self._interval_min: Optional[int] = None
        self._interval_max: Optional[int] = None
        self._last_snapshot: Optional[ProgressSnapshot] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_LG)

        interval_row = QHBoxLayout()
        interval_row.setSpacing(SPACE_XS)
        self._interval_summary_label = QLabel("", self)
        self._interval_summary_label.setObjectName("helperText")
        interval_row.addWidget(self._interval_summary_label)
        self._change_interval_button = QPushButton(tr("campaign_controls.edit_in_settings_button"), self)
        self._change_interval_button.setObjectName("toolbarButton")
        self._change_interval_button.clicked.connect(self.open_settings_requested.emit)
        interval_row.addWidget(self._change_interval_button)
        interval_row.addStretch(1)
        layout.addLayout(interval_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(SPACE_SM)
        self._start_button = QPushButton(tr("campaign_controls.start_button"), self)
        self._start_button.setObjectName("primaryButton")
        self._start_button.setToolTip(tr("campaign_controls.start_tooltip"))
        self._start_button.clicked.connect(self.start_requested.emit)
        self._pause_button = QPushButton(tr("campaign_controls.pause_button"), self)
        self._pause_button.clicked.connect(self._on_pause_clicked)
        self._stop_button = QPushButton(tr("campaign_controls.stop_button"), self)
        self._stop_button.setObjectName("dangerButton")
        self._stop_button.clicked.connect(self.stop_requested.emit)
        action_row.addWidget(self._start_button, 1)
        action_row.addWidget(self._pause_button)
        action_row.addWidget(self._stop_button)
        layout.addLayout(action_row)

        stats_section = QVBoxLayout()
        stats_section.setSpacing(SPACE_XS)
        self._progress_bar = QProgressBar(self)
        self._progress_bar.setRange(0, 100)
        stats_section.addWidget(self._progress_bar)
        self._stats_label = QLabel(
            tr("campaign_controls.stats_line", total=0, sent=0, failed=0, skipped=0, pending=0), self
        )
        self._stats_label.setWordWrap(True)
        self._stats_label.setObjectName("summaryLabel")
        stats_section.addWidget(self._stats_label)
        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)
        self._status_label.setObjectName("statusLabel")
        stats_section.addWidget(self._status_label)

        report_row = QHBoxLayout()
        self._export_report_button = QPushButton(tr("campaign_controls.export_report_button"), self)
        self._export_report_button.setToolTip(tr("campaign_controls.export_report_tooltip"))
        self._export_report_button.setEnabled(False)
        self._export_report_button.clicked.connect(self.export_report_requested.emit)
        report_row.addWidget(self._export_report_button)
        report_row.addStretch(1)
        stats_section.addLayout(report_row)

        layout.addLayout(stats_section)

        self._update_start_enabled()
        self.set_running_state(False)

    def _on_pause_clicked(self) -> None:
        if self._is_paused:
            self.resume_requested.emit()
        else:
            self.pause_requested.emit()

    def set_interval_summary(self, min_seconds: int, max_seconds: int) -> None:
        self._interval_min = min_seconds
        self._interval_max = max_seconds
        self._interval_summary_label.setText(tr("campaign_controls.interval_summary", min=min_seconds, max=max_seconds))

    def set_start_ready(self, ready: bool) -> None:
        """Proactively enable/disable Start based on whether an account,
        recipients, and message content are all present -- not just
        reactively rejecting the click with an error popup."""
        self._start_ready = ready
        self._update_start_enabled()

    def _update_start_enabled(self) -> None:
        self._start_button.setEnabled(self._start_ready and not self._running)

    def set_running_state(self, running: bool, paused: bool = False) -> None:
        self._running = running
        self._is_paused = paused
        self._update_start_enabled()
        self._pause_button.setEnabled(running)
        self._pause_button.setText(tr("campaign_controls.resume_button") if paused else tr("campaign_controls.pause_button"))
        self._stop_button.setEnabled(running)

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
        percent = int(done / snapshot.total * 100) if snapshot.total else 0
        self._progress_bar.setValue(percent)

    def set_status_text(self, text: str) -> None:
        self._status_label.setText(text)

    def set_report_available(self, available: bool) -> None:
        self._export_report_button.setEnabled(available)

    def retranslate_ui(self) -> None:
        self._change_interval_button.setText(tr("campaign_controls.edit_in_settings_button"))
        self._start_button.setText(tr("campaign_controls.start_button"))
        self._start_button.setToolTip(tr("campaign_controls.start_tooltip"))
        self._pause_button.setText(tr("campaign_controls.resume_button") if self._is_paused else tr("campaign_controls.pause_button"))
        self._stop_button.setText(tr("campaign_controls.stop_button"))
        if self._last_snapshot is not None:
            self.update_progress(self._last_snapshot)
        else:
            self._stats_label.setText(tr("campaign_controls.stats_line", total=0, sent=0, failed=0, skipped=0, pending=0))
        self._export_report_button.setText(tr("campaign_controls.export_report_button"))
        self._export_report_button.setToolTip(tr("campaign_controls.export_report_tooltip"))
        if self._interval_min is not None and self._interval_max is not None:
            self._interval_summary_label.setText(
                tr("campaign_controls.interval_summary", min=self._interval_min, max=self._interval_max)
            )
