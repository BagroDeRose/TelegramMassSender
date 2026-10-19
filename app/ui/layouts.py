"""Layout helpers shared by pages."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QLayoutItem, QScrollArea, QVBoxLayout, QWidget

from app.ui.theme import SPACE_LG, SPACE_SM, SPACE_XL


class WrappingLabel(QLabel):
    """A label that stays on one line whenever that fits and wraps only
    when its column is squeezed. (A plain word-wrapping QLabel asks for a
    "nicely" proportioned, narrower shape and wraps even with room to
    spare.)"""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance(self.text()) + margins.left() + margins.right() + 2 * self.margin() + 1
        return QSize(width, self.heightForWidth(width))


class FlowLayout(QLayout):
    """A row of controls that wraps onto further lines when it runs out of
    width, instead of forcing its parent to be as wide as all of them
    side by side. Its minimum width is that of its widest item, so a page
    built from these rows can always shrink to its column without
    clipping. Items keep their preferred width (never wider than the
    line); within a line they are vertically centred."""

    def __init__(self, parent: Optional[QWidget] = None, spacing: int = SPACE_SM) -> None:
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # ---- QLayout plumbing ------------------------------------------------------

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt override
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:  # noqa: N802 - Qt override
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:  # noqa: N802 - Qt override
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def spacing(self) -> int:
        return self._spacing

    def setSpacing(self, spacing: int) -> None:  # noqa: N802 - Qt override
        self._spacing = spacing
        self.invalidate()

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 - Qt override
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        """Everything on one line, when there's room for it."""
        visible = self._visible_items()
        margins = self.contentsMargins()
        width = sum(i.sizeHint().width() for i in visible) + self._spacing * max(0, len(visible) - 1)
        height = max((i.sizeHint().height() for i in visible), default=0)
        return QSize(width + margins.left() + margins.right(), height + margins.top() + margins.bottom())

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt override
        margins = self.contentsMargins()
        width = max((self._min_width(i) for i in self._visible_items()), default=0)
        return QSize(width + margins.left() + margins.right(), self.heightForWidth(width + margins.left() + margins.right()))

    # ---- placement ---------------------------------------------------------------

    def _visible_items(self) -> List[QLayoutItem]:
        return [item for item in self._items if not item.isEmpty()]

    @staticmethod
    def _min_width(item: QLayoutItem) -> int:
        # Buttons and labels shouldn't be squeezed below what shows their
        # text; a word-wrapping label may (it grows taller instead).
        if item.hasHeightForWidth():
            return item.minimumSize().width()
        return max(item.minimumSize().width(), item.sizeHint().width())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        lines: List[List[tuple]] = [[]]
        x = 0
        for item in self._visible_items():
            width = max(self._min_width(item), min(item.sizeHint().width(), area.width()))
            if lines[-1] and x + width > area.width():
                lines.append([])
                x = 0
            height = item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height()
            lines[-1].append((item, x, width, height))
            x += width + self._spacing
        y = area.top()
        for line in lines:
            if not line:
                continue
            line_height = max(h for _, _, _, h in line)
            if apply:
                for item, offset, width, height in line:
                    top = y + (line_height - height) // 2
                    item.setGeometry(QRect(QPoint(area.left() + offset, top), QSize(width, height)))
            y += line_height + self._spacing
        return max(0, y - self._spacing - area.top()) + margins.top() + margins.bottom()


class ResponsiveColumns(QWidget):
    """A scrolling main column with a pinned side column on the right.

    The two columns stand side by side only when both get what their
    contents need -- the main column's minimum width plus the side
    column's -- and never below `threshold`; otherwise the side column
    folds into the bottom of the main column (one scrolling column), so
    nothing gets squeezed or clipped. Re-evaluated whenever the widget is
    resized or either column's contents change (language switch, a row
    that wraps, a control shown or hidden).
    """

    def __init__(self, side_width: int, threshold: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._threshold = threshold
        self._side_width = side_width
        self._folded: Optional[bool] = None
        self._finished = False
        self._recheck = QTimer(self)
        self._recheck.setSingleShot(True)
        self._recheck.setInterval(0)
        self._recheck.timeout.connect(self._update)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.main = QWidget()
        self.main.setObjectName("page")
        self.main_layout = QVBoxLayout(self.main)
        self.main_layout.setContentsMargins(SPACE_XL, 0, SPACE_LG, SPACE_XL)
        self.main_layout.setSpacing(SPACE_LG)
        self._fold_slot = QVBoxLayout()
        self._fold_slot.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(self.main)
        row.addWidget(self.scroll, 1)

        # The pinned column scrolls on its own when the window is too short
        # for it (small screens, 150 % scaling), instead of squeezing.
        self._side_slot = QScrollArea(self)
        self._side_slot.setWidgetResizable(True)
        self._side_slot.setFrameShape(QFrame.Shape.NoFrame)
        self._side_slot.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_holder = QWidget()
        side_holder.setObjectName("page")
        self._side_slot_layout = QVBoxLayout(side_holder)
        self._side_slot_layout.setContentsMargins(0, 0, SPACE_XL, SPACE_XL)
        self._side_slot.setWidget(side_holder)
        row.addWidget(self._side_slot)

        self.side = QWidget()
        self.side_layout = QVBoxLayout(self.side)
        self.side_layout.setContentsMargins(0, 0, 0, 0)
        self.side_layout.setSpacing(SPACE_LG)

        self.main.installEventFilter(self)
        self.side.installEventFilter(self)

    def finish(self) -> None:
        """Call after filling main_layout and side_layout."""
        self.main_layout.addLayout(self._fold_slot)
        self.main_layout.addStretch(1)
        self._finished = True
        self._update()

    @property
    def is_folded(self) -> bool:
        return bool(self._folded)

    # ---- what the columns need -------------------------------------------------

    def main_min_width(self) -> int:
        """The main column's own contents (not the folded side column)."""
        margins = self.main_layout.contentsMargins()
        widest = 0
        for index in range(self.main_layout.count()):
            item = self.main_layout.itemAt(index)
            if item.layout() is self._fold_slot:
                continue
            widest = max(widest, item.minimumSize().width())
        return widest + margins.left() + margins.right()

    def side_slot_width(self) -> int:
        """Pinned, the side column gets the width its contents prefer (at
        least `side_width`) -- not merely their minimum, which is what
        they squeeze to only when folded into a narrow single column."""
        margins = self._side_slot_layout.contentsMargins()
        return max(self._side_width, self.side.sizeHint().width()) + margins.left() + margins.right()

    def two_column_width(self) -> int:
        """The narrowest width at which both columns fit side by side."""
        return max(self._threshold, self.main_min_width() + self.side_slot_width())

    # ---- folding -----------------------------------------------------------------

    def _update(self) -> None:
        if not self._finished:
            return
        self._side_slot.setFixedWidth(self.side_slot_width())
        self._apply(self.width() < self.two_column_width())

    def _apply(self, folded: bool) -> None:
        if folded == self._folded:
            return
        self._folded = folded
        if folded:
            self._side_slot_layout.removeWidget(self.side)
            self._fold_slot.addWidget(self.side)
            self._side_slot.setVisible(False)
        else:
            self._fold_slot.removeWidget(self.side)
            self._side_slot_layout.addWidget(self.side)
            self._side_slot.setVisible(True)
        self.side.setVisible(True)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        # A column's contents changed what they need: look again once the
        # layouts have settled (never re-entering a layout pass).
        if event.type() == QEvent.Type.LayoutRequest and watched in (self.main, self.side):
            self._recheck.start()
        return False

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        # This widget's own width decides, so an open journal panel or an
        # expanded sidebar folds the columns as well as a narrow window.
        self._update()
