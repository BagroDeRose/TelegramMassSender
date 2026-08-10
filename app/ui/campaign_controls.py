"""Interval settings, Start/Pause/Stop controls, progress display, and the
test-send row (spec items 19-26, 30, 43)."""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.campaign.campaign_manager import ProgressSnapshot
from app.config.settings import (
    DEFAULT_MAX_DELAY_SECONDS,
    DEFAULT_MIN_DELAY_SECONDS,
    MAX_ALLOWED_DELAY_SECONDS,
    MIN_ALLOWED_DELAY_SECONDS,
)


class CampaignControlsWidget(QWidget):
    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    test_send_requested = Signal(str)  # recipient text

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._running = False
        self._is_paused = False
        self._start_ready = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        interval_box = QGroupBox("Интервал отправки", self)
        interval_layout = QFormLayout(interval_box)
        self._min_spin = QSpinBox(interval_box)
        self._min_spin.setRange(MIN_ALLOWED_DELAY_SECONDS, MAX_ALLOWED_DELAY_SECONDS)
        self._min_spin.setValue(DEFAULT_MIN_DELAY_SECONDS)
        self._min_spin.setToolTip(
            "Минимальная пауза перед отправкой следующему получателю (секунды).\n"
            "Случайный интервал снижает интенсивность работы программы, но не\n"
            "гарантирует отсутствие ограничений со стороны Telegram."
        )
        self._max_spin = QSpinBox(interval_box)
        self._max_spin.setRange(MIN_ALLOWED_DELAY_SECONDS, MAX_ALLOWED_DELAY_SECONDS)
        self._max_spin.setValue(DEFAULT_MAX_DELAY_SECONDS)
        self._max_spin.setToolTip("Максимальная пауза перед отправкой следующему получателю (секунды).")
        interval_layout.addRow("Минимум (сек):", self._min_spin)
        interval_layout.addRow("Максимум (сек):", self._max_spin)
        layout.addWidget(interval_box)

        test_box = QGroupBox("Тестовая отправка", self)
        test_layout = QHBoxLayout(test_box)
        self._test_recipient_edit = QLineEdit(test_box)
        self._test_recipient_edit.setPlaceholderText("@username или ID получателя")
        self._test_recipient_edit.setToolTip(
            "Рекомендуется сначала проверить сообщение на своём втором аккаунте,\n"
            "прежде чем запускать рассылку на весь список."
        )
        self._test_button = QPushButton("Отправить тест", test_box)
        self._test_button.clicked.connect(
            lambda: self.test_send_requested.emit(self._test_recipient_edit.text().strip())
        )
        test_layout.addWidget(self._test_recipient_edit)
        test_layout.addWidget(self._test_button)
        layout.addWidget(test_box)

        stats_box = QGroupBox("Статистика", self)
        stats_layout = QVBoxLayout(stats_box)
        self._stats_label = QLabel("Всего: 0    Отправлено: 0    Ошибок: 0    Осталось: 0", stats_box)
        self._stats_label.setWordWrap(True)
        self._stats_label.setObjectName("summaryLabel")
        stats_layout.addWidget(self._stats_label)
        self._progress_bar = QProgressBar(stats_box)
        self._progress_bar.setRange(0, 100)
        stats_layout.addWidget(self._progress_bar)
        self._status_label = QLabel("", stats_box)
        self._status_label.setWordWrap(True)
        self._status_label.setObjectName("statusLabel")
        stats_layout.addWidget(self._status_label)
        layout.addWidget(stats_box)

        buttons = QHBoxLayout()
        self._start_button = QPushButton("▶ НАЧАТЬ", self)
        self._start_button.setObjectName("primaryButton")
        self._start_button.setToolTip("Нужны: подключённый аккаунт, хотя бы один получатель и текст или вложение")
        self._start_button.clicked.connect(self.start_requested.emit)
        self._pause_button = QPushButton("⏸ ПАУЗА", self)
        self._pause_button.clicked.connect(self._on_pause_clicked)
        self._stop_button = QPushButton("■ ОСТАНОВИТЬ", self)
        self._stop_button.setObjectName("dangerButton")
        self._stop_button.clicked.connect(self.stop_requested.emit)
        buttons.addWidget(self._start_button)
        buttons.addWidget(self._pause_button)
        buttons.addWidget(self._stop_button)
        layout.addLayout(buttons)

        self._update_start_enabled()
        self.set_running_state(False)

    def _on_pause_clicked(self) -> None:
        if self._is_paused:
            self.resume_requested.emit()
        else:
            self.pause_requested.emit()

    def get_interval(self) -> Tuple[int, int]:
        return self._min_spin.value(), self._max_spin.value()

    def set_interval(self, min_seconds: int, max_seconds: int) -> None:
        self._min_spin.setValue(min_seconds)
        self._max_spin.setValue(max_seconds)

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
        self._pause_button.setText("▶ ПРОДОЛЖИТЬ" if paused else "⏸ ПАУЗА")
        self._stop_button.setEnabled(running)
        self._min_spin.setEnabled(not running)
        self._max_spin.setEnabled(not running)
        # A test send goes through the same Telegram client the campaign is
        # using -- block it while a campaign is active so the two can't
        # send concurrently and confuse the user about what actually went out.
        self._test_recipient_edit.setEnabled(not running)
        self._test_button.setEnabled(not running)

    def update_progress(self, snapshot: ProgressSnapshot) -> None:
        self._stats_label.setText(
            f"Всего: {snapshot.total}    Отправлено: {snapshot.sent}    "
            f"Ошибок: {snapshot.failed}    Осталось: {snapshot.pending}"
        )
        done = snapshot.sent + snapshot.failed + snapshot.skipped
        percent = int(done / snapshot.total * 100) if snapshot.total else 0
        self._progress_bar.setValue(percent)

    def set_status_text(self, text: str) -> None:
        self._status_label.setText(text)
