"""Layout helpers shared by pages."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from app.ui.theme import SPACE_LG, SPACE_XL


class ResponsiveColumns(QWidget):
    """A scrolling main column with a pinned side column on the right.

    Narrower than `threshold`, the side column folds into the bottom of
    the main column (one scrolling column), so nothing gets squeezed.
    """

    def __init__(self, side_width: int, threshold: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._threshold = threshold
        self._side_width = side_width
        self._folded: Optional[bool] = None

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
        self._side_slot.setFixedWidth(side_width + SPACE_XL)
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

    def finish(self) -> None:
        """Call after filling main_layout and side_layout."""
        self.main_layout.addLayout(self._fold_slot)
        self.main_layout.addStretch(1)
        self._apply(self.width() < self._threshold)

    @property
    def is_folded(self) -> bool:
        return bool(self._folded)

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

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        # This widget's own width decides, so an open journal panel or an
        # expanded sidebar folds the columns as well as a narrow window.
        self._apply(self.width() < self._threshold)
