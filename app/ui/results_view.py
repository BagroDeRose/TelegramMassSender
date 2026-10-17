"""Results page building blocks: a segmented filter control and the
per-recipient table rows (status pill, recipient, target type as icon +
text, ID in monospace, reason).

The rows stay QListWidgetItems (checkable for Retry, carrying the SendItem
in UserRole, with a plain-text summary as their text for accessibility);
ResultsRowDelegate only changes how they're painted -- every colour is
read from the active tokens at paint time.
"""
from __future__ import annotations

from typing import Any, List, Optional

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from app.campaign.send_queue import SendItemStatus
from app.i18n import tr
from app.telegram.chat_targets import TargetType, target_type_label
from app.ui import icons, theme
from app.ui.theme import (
    FONT_SIZE_CAPTION,
    FONT_SIZE_HELPER,
    ICON_SIZE_SM,
    RESULTS_COL_CHECK,
    RESULTS_COL_ID,
    RESULTS_COL_STATUS,
    RESULTS_COL_TYPE,
    RESULTS_ROW_HEIGHT,
    BORDER_WIDTH,
    SEGMENT_PADDING,
    SPACE_SM,
    SPACE_XS,
)

# ---- segmented control -------------------------------------------------------------


class SegmentedControl(QFrame):
    """A row of mutually exclusive options. Mirrors the small part of the
    QComboBox API callers use (addItem/currentIndex/currentData/...), so
    it could replace a filter combo without touching its callers."""

    currentIndexChanged = Signal(int)  # noqa: N815 - Qt-style signal name

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(SEGMENT_PADDING, SEGMENT_PADDING, SEGMENT_PADDING, SEGMENT_PADDING)
        self._layout.setSpacing(SEGMENT_PADDING)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self._on_clicked)
        self._buttons: List[QPushButton] = []
        self._data: List[Any] = []
        self._current = -1

    def addItem(self, text: str, data: Any = None) -> None:  # noqa: N802 - QComboBox-style
        button = QPushButton(text, self)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._group.addButton(button, len(self._buttons))
        self._layout.addWidget(button)
        self._buttons.append(button)
        self._data.append(data)
        if self._current < 0:
            self.setCurrentIndex(0)

    def count(self) -> int:
        return len(self._buttons)

    def currentIndex(self) -> int:  # noqa: N802
        return self._current

    def currentData(self) -> Any:  # noqa: N802
        return self._data[self._current] if 0 <= self._current < len(self._data) else None

    def itemData(self, index: int) -> Any:  # noqa: N802
        return self._data[index]

    def findData(self, data: Any) -> int:  # noqa: N802
        return self._data.index(data) if data in self._data else -1

    def setItemText(self, index: int, text: str) -> None:  # noqa: N802
        self._buttons[index].setText(text)

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self._buttons):
            return
        self._buttons[index].setChecked(True)
        if index != self._current:
            self._current = index
            self.currentIndexChanged.emit(index)

    def _on_clicked(self, index: int) -> None:
        self.setCurrentIndex(index)


# ---- table rows -----------------------------------------------------------------------

_STATUS_KEYS = {
    SendItemStatus.SENT: ("main_window.results_page.status_sent", "success"),
    SendItemStatus.FAILED: ("main_window.results_page.status_failed", "error"),
    SendItemStatus.SKIPPED: ("main_window.results_page.status_skipped", ""),
    SendItemStatus.PENDING: ("main_window.results_page.status_pending", ""),
    SendItemStatus.SENDING: ("main_window.results_page.status_pending", ""),
}
_TYPE_ICONS = {
    TargetType.USER: "user",
    TargetType.GROUP: "group",
    TargetType.SUPERGROUP: "supergroup",
    TargetType.FORUM: "forum",
    TargetType.CHANNEL: "channel",
}


def _target_type(item) -> Optional[TargetType]:
    try:
        return TargetType(item.target_type) if item.target_type else None
    except ValueError:
        return None


def column_rects(row: QRect) -> dict:
    """Column geometry shared by the header and the rows."""
    x = row.left() + RESULTS_COL_CHECK
    status = QRect(x, row.top(), RESULTS_COL_STATUS, row.height())
    x += RESULTS_COL_STATUS
    flexible = max(0, row.right() - x - RESULTS_COL_TYPE - RESULTS_COL_ID)
    recipient_width = flexible * 2 // 5
    recipient = QRect(x, row.top(), recipient_width, row.height())
    x += recipient_width
    type_rect = QRect(x, row.top(), RESULTS_COL_TYPE, row.height())
    x += RESULTS_COL_TYPE
    id_rect = QRect(x, row.top(), RESULTS_COL_ID, row.height())
    x += RESULTS_COL_ID
    reason = QRect(x, row.top(), max(0, row.right() - x), row.height())
    return {"status": status, "recipient": recipient, "type": type_rect, "id": id_rect, "reason": reason}


class ResultsHeader(QWidget):
    """Column captions aligned with ResultsRowDelegate's columns."""

    _KEYS = (
        ("status", "main_window.results_page.col_status"),
        ("recipient", "main_window.results_page.col_recipient"),
        ("type", "main_window.results_page.col_type"),
        ("id", "main_window.results_page.col_id"),
        ("reason", "main_window.results_page.col_reason"),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._labels = {}
        for key, text_key in self._KEYS:
            label = QLabel(tr(text_key), self)
            label.setObjectName("tableHeader")
            self._labels[key] = label
        self.setFixedHeight(QFontMetrics(theme.ui_font(FONT_SIZE_CAPTION)).height() + SPACE_SM)

    def retranslate_ui(self) -> None:
        for key, text_key in self._KEYS:
            self._labels[key].setText(tr(text_key))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        # Rows sit inside the list's frame and padding; match that inset.
        rects = column_rects(QRect(BORDER_WIDTH, 0, self.width() - 2 * BORDER_WIDTH, self.height()))
        for key, label in self._labels.items():
            rect = rects[key].adjusted(SPACE_SM, 0, -SPACE_SM, 0)
            label.setGeometry(rect)


class ResultsRowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt override
        return QSize(option.rect.width(), RESULTS_ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        item = index.data(Qt.ItemDataRole.UserRole)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        widget = option.widget
        style = widget.style() if widget is not None else None
        # Background (hover/selection) and the Retry check box, as styled by
        # the QSS -- the check box rect matches what editorEvent hit-tests.
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        if item is None:
            painter.drawText(option.rect, Qt.AlignmentFlag.AlignVCenter, text)
            return

        tokens = theme.current_tokens()
        rects = column_rects(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Status pill.
        status_key, status = _STATUS_KEYS.get(item.status, ("main_window.results_page.status_pending", ""))
        label = tr(status_key)
        font = theme.ui_font(FONT_SIZE_CAPTION, theme.FONT_WEIGHT_MEDIUM)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        pill_w = metrics.horizontalAdvance(label) + 2 * SPACE_SM
        pill_h = metrics.height() + SPACE_XS
        pill = QRectF(rects["status"].left() + SPACE_SM, rects["status"].center().y() - pill_h / 2, pill_w, pill_h)
        fg = {"success": tokens.success, "error": tokens.error}.get(status, tokens.text_secondary)
        bg = QColor(fg)
        bg.setAlphaF(0.12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(pill, pill_h / 2, pill_h / 2)
        painter.setPen(QColor(fg))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)

        # Recipient.
        body = theme.ui_font(FONT_SIZE_HELPER + 1)
        painter.setFont(body)
        painter.setPen(QColor(tokens.text_primary))
        self._draw_elided(painter, rects["recipient"], item.recipient.display_label)

        # Target type: icon + text.
        target_type = _target_type(item)
        if target_type is not None:
            type_text = target_type_label(target_type)
            icon_name = _TYPE_ICONS[target_type]
        elif item.recipient.is_chat_target:
            type_text, icon_name = tr("main_window.results_page.type_chat"), "chats"
        else:
            type_text, icon_name = "—", None
        type_rect = rects["type"].adjusted(SPACE_SM, 0, -SPACE_XS, 0)
        if icon_name:
            icon_rect = QRect(type_rect.left(), type_rect.center().y() - ICON_SIZE_SM // 2, ICON_SIZE_SM, ICON_SIZE_SM)
            icons.themed(icon_name, "text_muted").paint(painter, icon_rect)
            type_rect.setLeft(icon_rect.right() + SPACE_XS + 1)
        painter.setFont(theme.ui_font(FONT_SIZE_HELPER))
        painter.setPen(QColor(tokens.text_secondary))
        painter.drawText(type_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, type_text)

        # ID (monospace).
        painter.setFont(theme.mono_font(FONT_SIZE_HELPER))
        painter.setPen(QColor(tokens.text_muted))
        self._draw_elided(painter, rects["id"], str(item.resolved_id) if item.resolved_id is not None else "—")

        # Reason.
        painter.setFont(theme.ui_font(FONT_SIZE_HELPER))
        painter.setPen(QColor(tokens.error if item.status == SendItemStatus.FAILED else tokens.text_muted))
        self._draw_elided(painter, rects["reason"], item.error or "")
        painter.restore()

    @staticmethod
    def _draw_elided(painter: QPainter, rect: QRect, text: str) -> None:
        inner = rect.adjusted(SPACE_SM, 0, -SPACE_SM, 0)
        elided = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, inner.width())
        painter.drawText(inner, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)


def results_list_tooltip(item) -> str:
    parts = [item.recipient.display_label]
    if item.error:
        parts.append(item.error)
    return " — ".join(parts)

