"""Application-shell sidebar: brand header + primary navigation. Purely a
navigation control -- it has no idea what the pages contain, it only picks
which index of the main window's QStackedWidget is visible.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QToolButton, QVBoxLayout, QWidget

from app.config.paths import get_resource_path
from app.ui import icons, theme
from app.ui.theme import SPACE_LG, SPACE_XL, SPACE_XS, SPACE_XXL

# (internal name, icon glyph, display label) -- internal name is only used
# for lookups in tests/debugging, the label is what's shown.
NAV_ITEMS: Tuple[Tuple[str, str, str], ...] = (
    ("campaign", "campaign", "Кампания"),
    ("accounts", "accounts", "Аккаунты"),
    ("results", "results", "Результаты"),
    ("settings", "settings", "Настройки"),
)


class Sidebar(QFrame):
    page_selected = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_LG, SPACE_XL, SPACE_LG, SPACE_LG)
        layout.setSpacing(SPACE_XXL)

        layout.addWidget(self._build_brand())

        divider = QFrame(self)
        divider.setObjectName("sidebarDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        self._buttons: List[QToolButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        nav = QVBoxLayout()
        nav.setSpacing(SPACE_XS)
        for index, (_key, icon_name, label) in enumerate(NAV_ITEMS):
            button = QToolButton(self)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setText(f"  {label}")
            button.setIconSize(QSize(18, 18))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("iconName", icon_name)
            button.clicked.connect(lambda _checked=False, i=index: self._on_clicked(i))
            self._group.addButton(button, index)
            nav.addWidget(button)
            self._buttons.append(button)
        layout.addLayout(nav)
        layout.addStretch(1)

        self._buttons[0].setChecked(True)
        self.apply_theme()

    def _build_brand(self) -> QWidget:
        brand = QWidget(self)
        row = QVBoxLayout(brand)
        row.setContentsMargins(4, 0, 0, 0)
        row.setSpacing(2)

        logo_label = QLabel(brand)
        logo_path = get_resource_path("assets", "icons", "icon_32.png")
        if logo_path.is_file():
            pixmap = QPixmap(str(logo_path))
            logo_label.setPixmap(pixmap.scaledToHeight(26, Qt.TransformationMode.SmoothTransformation))
        row.addWidget(logo_label)

        title = QLabel("Mass Sender", brand)
        title.setObjectName("sidebarBrandTitle")
        row.addWidget(title)

        subtitle = QLabel("для Telegram", brand)
        subtitle.setObjectName("sidebarBrandSubtitle")
        row.addWidget(subtitle)

        return brand

    def _on_clicked(self, index: int) -> None:
        self.apply_theme()  # resync active/inactive icon tint with the click
        self.page_selected.emit(index)

    def set_current_index(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)
            self.apply_theme()

    def apply_theme(self) -> None:
        """Re-tint every nav icon for the active theme/checked state. Icons
        are baked pixmaps (QSS cannot recolor a QIcon), so this must be
        called explicitly after a theme switch -- see main_window.py."""
        tokens = theme.current_tokens()
        for button in self._buttons:
            icon_name = button.property("iconName")
            color = tokens.accent if button.isChecked() else tokens.text_secondary
            button.setIcon(icons.icon(icon_name, color, size=18))
