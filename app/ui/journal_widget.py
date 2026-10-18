"""Collapsible activity panel on the right of the shell. Shows the curated,
human-readable events app.campaign.campaign_manager emits (never raw
tracebacks -- those go only to the rotating file log): the time in a muted
monospace, a status icon in the status colour, and the message.

The campaign layer prefixes its messages with a marker glyph (✓ ✗ … ▶ ⏸ ■
✖ ↷); here that marker becomes the icon and is not repeated in the text.
Rows are painted by JournalRowDelegate from the active tokens, so a theme
switch recolours them without rebuilding anything.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.ui import icons, theme
from app.ui.theme import (
    FONT_SIZE_CAPTION,
    FONT_SIZE_HELPER,
    ICON_SIZE_SM,
    JOURNAL_WIDTH,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    icon_qsize,
)

_MAX_VISIBLE_LINES = 300
_TIME_ROLE = Qt.ItemDataRole.UserRole + 1
_MESSAGE_ROLE = Qt.ItemDataRole.UserRole + 2

# Leading marker -> (icon name, token role). The first three are the
# strong per-recipient outcomes the campaign layer reports.
_MARKERS = {
    "✓": ("check_circle", "success"),
    "✗": ("error_circle", "error"),
    "…": ("clock", "warning"),
    "▶": ("start", "accent"),
    "⏸": ("pause", "warning"),
    "■": ("stop", "text_muted"),
    "✖": ("error_circle", "error"),
    "↷": ("skipped", "text_muted"),
}
_CLASSIFIED = ("✓", "✗", "…")


def _classify(message: str) -> Optional[tuple[str, str]]:
    """(icon_name, colour variant) for a message's leading per-recipient
    marker, or None for a plain entry (e.g. "Next send in N sec.")."""
    for marker in _CLASSIFIED:
        if message.startswith(marker):
            return _MARKERS[marker]
    return None


def _marker(message: str) -> Optional[str]:
    for marker in _MARKERS:
        if message.startswith(marker):
            return marker
    return None


def _display_text(message: str) -> str:
    marker = _marker(message)
    return message[len(marker):].lstrip() if marker else message


class JournalRowDelegate(QStyledItemDelegate):
    def _message_rect(self, width: int) -> QRect:
        time_width = QFontMetrics(theme.mono_font(FONT_SIZE_CAPTION)).horizontalAdvance("00:00:00")
        left = SPACE_SM + time_width + SPACE_SM + ICON_SIZE_SM + SPACE_SM
        return QRect(left, SPACE_XS, max(1, width - left - SPACE_SM), 0)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt override
        width = option.rect.width() or (JOURNAL_WIDTH - 2 * SPACE_MD)
        rect = self._message_rect(width)
        metrics = QFontMetrics(theme.ui_font(FONT_SIZE_HELPER))
        text = index.data(_MESSAGE_ROLE) or ""
        bounding = metrics.boundingRect(QRect(0, 0, rect.width(), 10_000), Qt.TextFlag.TextWordWrap, text)
        return QSize(width, bounding.height() + 2 * SPACE_XS + SPACE_XS)

    def paint(self, painter: QPainter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        # The icon is drawn below, aligned with the time stamp.
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDecoration
        widget = option.widget
        if widget is not None:
            widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        tokens = theme.current_tokens()
        rect = option.rect
        painter.save()
        mono = theme.mono_font(FONT_SIZE_CAPTION)
        painter.setFont(mono)
        painter.setPen(QColor(tokens.text_muted))
        time_rect = QRect(rect.left() + SPACE_SM, rect.top() + SPACE_XS, rect.width(), QFontMetrics(mono).height())
        painter.drawText(time_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, index.data(_TIME_ROLE) or "")

        message_rect = self._message_rect(rect.width()).translated(rect.left(), rect.top())
        message_rect.setBottom(rect.bottom() - SPACE_XS)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None and not icon.isNull():
            icon_rect = QRect(
                message_rect.left() - SPACE_SM - ICON_SIZE_SM,
                time_rect.center().y() - ICON_SIZE_SM // 2,
                ICON_SIZE_SM,
                ICON_SIZE_SM,
            )
            icon.paint(painter, icon_rect)
        painter.setFont(theme.ui_font(FONT_SIZE_HELPER))
        painter.setPen(QColor(tokens.text_primary))
        painter.drawText(message_rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop, index.data(_MESSAGE_ROLE) or "")
        painter.restore()


class JournalWidget(QFrame):
    toggle_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("journalPanel")
        self.setFixedWidth(JOURNAL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_MD, SPACE_LG, SPACE_MD, SPACE_MD)
        layout.setSpacing(SPACE_SM)

        header = QHBoxLayout()
        self._title = QLabel(tr("journal_widget.title"), self)
        self._title.setObjectName("journalTitle")
        header.addWidget(self._title)
        header.addStretch(1)
        self._collapse_button = QToolButton(self)
        self._collapse_button.setObjectName("journalToggleButton")
        self._collapse_button.setIcon(icons.themed("close", "text_muted"))
        self._collapse_button.setIconSize(icon_qsize(ICON_SIZE_SM))
        self._collapse_button.setToolTip(tr("journal_widget.hide_tooltip"))
        self._collapse_button.setAccessibleName(tr("journal_widget.hide_tooltip"))
        self._collapse_button.clicked.connect(self.toggle_requested.emit)
        header.addWidget(self._collapse_button)
        layout.addLayout(header)

        self._empty_label = QLabel(tr("journal_widget.empty"), self)
        self._empty_label.setObjectName("emptyStateBody")
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label)

        self._list = QListWidget(self)
        self._list.setObjectName("journalList")
        self._list.setItemDelegate(JournalRowDelegate(self._list))
        self._list.setWordWrap(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._list)
        self._sync_empty()

    def _sync_empty(self) -> None:
        empty = self._list.count() == 0
        self._empty_label.setVisible(empty)
        self._list.setVisible(not empty)

    def append(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"{timestamp}  {message}")
        item.setData(_TIME_ROLE, timestamp)
        item.setData(_MESSAGE_ROLE, _display_text(message))
        marker = _marker(message)
        if marker is not None:
            icon_name, role = _MARKERS[marker]
            item.setIcon(icons.themed(icon_name, role))
        item.setToolTip(message)
        self._list.addItem(item)
        self._list.scrollToBottom()
        while self._list.count() > _MAX_VISIBLE_LINES:
            self._list.takeItem(0)
        self._sync_empty()

    def clear(self) -> None:
        self._list.clear()
        self._sync_empty()

    def retranslate_ui(self) -> None:
        self._title.setText(tr("journal_widget.title"))
        self._empty_label.setText(tr("journal_widget.empty"))
        self._collapse_button.setToolTip(tr("journal_widget.hide_tooltip"))
        self._collapse_button.setAccessibleName(tr("journal_widget.hide_tooltip"))

    def apply_theme(self) -> None:
        """Icons and rows resolve colours at paint time; just repaint."""
        self._list.viewport().update()
