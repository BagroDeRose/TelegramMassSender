"""A compact "Saved lists ▾" / "Templates ▾" button: one menu with "Save
current…", a "Load" submenu and a "Delete" submenu listing what's saved.
With nothing saved yet, Load and Delete are disabled and the menu says so.

Purely presentational: it emits save_requested / load_requested(id) /
delete_requested(id); MainWindow does the work (the same handlers for the
Campaign page and the Campaign Wizard).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QAction, QIcon, QPainter
from PySide6.QtWidgets import QMenu, QPushButton, QWidget

from app.i18n import tr
from app.ui import icons
from app.ui.theme import ICON_SIZE_SM, SPACE_MD


@dataclass(frozen=True)
class SavedMenuTexts:
    """i18n keys for one kind of saved item."""

    button: str
    tooltip: str
    save: str
    load: str
    delete: str
    empty: str
    icon: str


class SavedItemsMenuButton(QPushButton):
    save_requested = Signal()
    load_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, texts: SavedMenuTexts, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._texts = texts
        self._items: List[Tuple[int, str]] = []
        # The style's own menu arrow is hidden in QSS; the chevron is
        # painted here so it is a Lucide icon in the theme's colours.
        self.setProperty("menuButton", True)
        self.setIcon(icons.themed(texts.icon))
        self._chevron = icons.themed("chevron_down")
        self._menu = QMenu(self)
        self._menu.setToolTipsVisible(True)
        self.setMenu(self._menu)
        self.save_action: Optional[QAction] = None
        self.load_menu: Optional[QMenu] = None
        self.delete_menu: Optional[QMenu] = None
        self.empty_action: Optional[QAction] = None
        self.retranslate_ui()

    # ---- contents ------------------------------------------------------------------

    def set_items(self, items: Sequence[Tuple[int, str]]) -> None:
        """(id, name) of everything saved, in display order."""
        self._items = list(items)
        self._rebuild()

    def item_names(self) -> List[str]:
        return [name for _, name in self._items]

    def item_ids(self) -> List[int]:
        return [item_id for item_id, _ in self._items]

    def retranslate_ui(self) -> None:
        self.setText(tr(self._texts.button))
        self.setToolTip(tr(self._texts.tooltip))
        self._rebuild()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        rect = QRect(self.width() - SPACE_MD - ICON_SIZE_SM, (self.height() - ICON_SIZE_SM) // 2, ICON_SIZE_SM, ICON_SIZE_SM)
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        self._chevron.paint(painter, rect, Qt.AlignmentFlag.AlignCenter, mode)
        painter.end()

    def _rebuild(self) -> None:
        menu = self._menu
        menu.clear()
        self.save_action = menu.addAction(icons.themed("save"), tr(self._texts.save))
        self.save_action.triggered.connect(lambda _checked=False: self.save_requested.emit())
        self.load_menu = menu.addMenu(icons.themed("folder"), tr(self._texts.load))
        self.delete_menu = menu.addMenu(icons.themed("delete", "error"), tr(self._texts.delete))
        for item_id, name in self._items:
            load = self.load_menu.addAction(name)
            load.triggered.connect(lambda _checked=False, i=item_id: self.load_requested.emit(i))
            delete = self.delete_menu.addAction(f"{name}…")
            delete.triggered.connect(lambda _checked=False, i=item_id: self.delete_requested.emit(i))
        has_items = bool(self._items)
        self.load_menu.setEnabled(has_items)
        self.delete_menu.setEnabled(has_items)
        self.empty_action = None
        if not has_items:
            menu.addSeparator()
            self.empty_action = menu.addAction(tr(self._texts.empty))
            self.empty_action.setEnabled(False)


LISTS_TEXTS = SavedMenuTexts(
    button="main_window.lists.button",
    tooltip="main_window.lists.tooltip",
    save="main_window.lists.save_action",
    load="main_window.lists.load_menu",
    delete="main_window.lists.delete_menu",
    empty="main_window.lists.empty",
    icon="accounts",
)

TEMPLATES_TEXTS = SavedMenuTexts(
    button="main_window.templates.button",
    tooltip="main_window.templates.tooltip",
    save="main_window.templates.save_action",
    load="main_window.templates.load_menu",
    delete="main_window.templates.delete_menu",
    empty="main_window.templates.empty",
    icon="document",
)
