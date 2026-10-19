"""A push button that opens a menu ("Import ▾", "Lists ▾", "Templates ▾").

One button with a short menu instead of a row of related buttons is what
keeps the Campaign page's button rows on one line at the default window
width. The style's own menu arrow is hidden in QSS
(`QPushButton[menuButton="true"]`); the chevron is a Lucide icon painted
here, so it follows the theme, and the label is left-aligned so the
chevron never crowds the text.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import QMenu, QPushButton, QWidget

from app.ui import icons
from app.ui.theme import ICON_SIZE_SM, SPACE_MD


class MenuButton(QPushButton):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("menuButton", True)
        self._chevron = icons.themed("chevron_down")
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        self.setMenu(menu)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        rect = QRect(self.width() - SPACE_MD - ICON_SIZE_SM, (self.height() - ICON_SIZE_SM) // 2, ICON_SIZE_SM, ICON_SIZE_SM)
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        self._chevron.paint(painter, rect, Qt.AlignmentFlag.AlignCenter, mode)
        painter.end()
