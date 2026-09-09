"""Collapsible activity panel for the application shell (replaces the old
bottom-of-page "Журнал" card). Shows the same curated, human-readable
events app.campaign.campaign_manager already emits (never raw tracebacks
-- those still go only to the rotating file log via app.logging.logger)
with a status icon per entry instead of a flat list of prefixed strings.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QToolButton, QVBoxLayout, QWidget

from app.ui import icons, theme

_MAX_VISIBLE_LINES = 300
_PANEL_WIDTH = 260


def _classify(message: str) -> Optional[tuple[str, str]]:
    """Map a log_message string's leading marker to (icon_name, color
    variant) for the journal row, or None for a plain entry with no
    strong status of its own (e.g. "Следующая отправка через N сек.")."""
    if message.startswith("✓"):
        return "check_circle", "success"
    if message.startswith("✗"):
        return "error_circle", "error"
    if message.startswith("…"):
        return "clock", "warning"
    return None


class JournalWidget(QFrame):
    toggle_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("journalPanel")
        self.setFixedWidth(_PANEL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Журнал", self)
        title.setObjectName("journalTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._collapse_button = QToolButton(self)
        self._collapse_button.setObjectName("journalToggleButton")
        self._collapse_button.setToolTip("Скрыть журнал")
        self._collapse_button.clicked.connect(self.toggle_requested.emit)
        header.addWidget(self._collapse_button)
        layout.addLayout(header)

        self._list = QListWidget(self)
        self._list.setObjectName("journalList")
        layout.addWidget(self._list)

        self._sync_collapse_icon()

    def append(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"{timestamp}  {message}")
        classification = _classify(message)
        if classification is not None:
            icon_name, variant = classification
            color = getattr(theme.current_tokens(), variant, theme.current_tokens().text_muted)
            item.setIcon(icons.icon(icon_name, color, 14))
        self._list.addItem(item)
        self._list.scrollToBottom()
        while self._list.count() > _MAX_VISIBLE_LINES:
            self._list.takeItem(0)

    def clear(self) -> None:
        self._list.clear()

    def _sync_collapse_icon(self) -> None:
        self._collapse_button.setIcon(icons.icon("close", theme.current_tokens().text_muted, 12))

    def apply_theme(self) -> None:
        """Re-tint the collapse button and re-render existing entries'
        icons for the new theme's colors."""
        self._sync_collapse_icon()
        for i in range(self._list.count()):
            item = self._list.item(i)
            text = item.text().split("  ", 1)[-1]
            classification = _classify(text)
            if classification is not None:
                icon_name, variant = classification
                color = getattr(theme.current_tokens(), variant, theme.current_tokens().text_muted)
                item.setIcon(icons.icon(icon_name, color, 14))
