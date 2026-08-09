"""Scrolling event log shown to the user (spec item 32) -- only
human-readable outcomes (✓/✗/…/⏸), never stack traces (those go to the
rotating file log only, via app.logging.logger).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

_MAX_VISIBLE_LINES = 500


class LogWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget(self)
        layout.addWidget(self._list)

    def append(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._list.addItem(QListWidgetItem(f"{timestamp} {message}"))
        self._list.scrollToBottom()
        while self._list.count() > _MAX_VISIBLE_LINES:
            self._list.takeItem(0)

    def clear(self) -> None:
        self._list.clear()
