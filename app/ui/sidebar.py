"""Application-shell sidebar: brand, primary navigation, and the active
account at the bottom. Collapses from ~220 px to an icon rail (~64 px);
MainWindow persists the state.

Purely a navigation control -- it has no idea what the pages contain; it
only picks which index of the main window's QStackedWidget is visible and
asks for the Accounts page when the account block is clicked.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.config.paths import get_resource_path
from app.i18n import tr
from app.ui import icons, theme
from app.ui.account_widget import make_avatar
from app.ui.theme import (
    ICON_SIZE,
    ICON_SIZE_NAV,
    MOTION_MS,
    SIDEBAR_COLLAPSED_WIDTH,
    SIDEBAR_LOGO,
    SIDEBAR_WIDTH,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    icon_qsize,
)

# (internal name, icon name, translation key)
NAV_ITEMS: Tuple[Tuple[str, str, str], ...] = (
    ("campaign", "campaign", "sidebar.nav.campaign"),
    ("accounts", "accounts", "sidebar.nav.accounts"),
    ("results", "results", "sidebar.nav.results"),
    ("settings", "settings", "sidebar.nav.settings"),
)


def _nav_label(label_key: str) -> str:
    # QToolButton draws text right against the icon and has no QSS for the
    # gap; two leading spaces are the gap. Accessible names use tr() alone.
    return f"  {tr(label_key)}"


class _AccountBlock(QPushButton):
    """Active account summary: initials, name, status dot. A flat button so
    it's keyboard-reachable and announces itself; its labels pass clicks
    through."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebarAccountButton")
        self.setProperty("variant", "ghost")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        layout.setSpacing(SPACE_SM)
        self._avatar = make_avatar("", self)
        layout.addWidget(self._avatar)
        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        self._name = QLabel(self)
        self._name.setObjectName("sidebarAccountName")
        text_col.addWidget(self._name)
        status_row = QHBoxLayout()
        status_row.setSpacing(SPACE_XS)
        self._dot = QLabel(self)
        self._dot.setObjectName("statusDot")
        status_row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self._status = QLabel(self)
        self._status.setObjectName("sidebarAccountMeta")
        status_row.addWidget(self._status, 1)
        text_col.addLayout(status_row)
        self._text_widget = QWidget(self)
        self._text_widget.setLayout(text_col)
        layout.addWidget(self._text_widget, 1)
        for child in (self._avatar, self._name, self._dot, self._status, self._text_widget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._content_layout = layout

    def sizeHint(self):  # noqa: N802 - Qt override
        # A QPushButton sizes itself from its own (empty) text; this one's
        # content is the child layout.
        return self._content_layout.sizeHint()

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        return self._content_layout.minimumSize()

    def set_account(self, initials: str, name: str, status_text: str, status: str) -> None:
        self._avatar.setText(initials)
        self._name.setText(name)
        self._status.setText(status_text)
        theme.set_status(self._dot, status)
        self.setToolTip(f"{name} · {status_text}")
        self.setAccessibleName(f"{name}, {status_text}")

    def set_collapsed(self, collapsed: bool) -> None:
        self._text_widget.setVisible(not collapsed)


class Sidebar(QFrame):
    page_selected = Signal(int)
    account_clicked = Signal()
    collapsed_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._collapsed = False
        self.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACE_LG, 0, 0)
        layout.setSpacing(SPACE_MD)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(SPACE_LG, 0, SPACE_SM, 0)
        brand_row.setSpacing(SPACE_SM)
        self._logo = QLabel(self)
        logo_path = get_resource_path("assets", "icons", "icon_32.png")
        if logo_path.is_file():
            pixmap = QPixmap(str(logo_path))
            self._logo.setPixmap(pixmap.scaledToHeight(SIDEBAR_LOGO, Qt.TransformationMode.SmoothTransformation))
        brand_row.addWidget(self._logo)
        self._title = QLabel("Mass Sender", self)  # product name -- not translated
        self._title.setObjectName("sidebarBrandTitle")
        brand_row.addWidget(self._title, 1)
        self._toggle = QToolButton(self)
        self._toggle.setObjectName("sidebarToggle")
        self._toggle.setIconSize(icon_qsize(ICON_SIZE))
        self._toggle.clicked.connect(lambda: self.set_collapsed(not self._collapsed, animate=True))
        brand_row.addWidget(self._toggle)
        layout.addLayout(brand_row)

        self._buttons: List[QToolButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        nav = QVBoxLayout()
        nav.setContentsMargins(0, SPACE_SM, 0, 0)
        nav.setSpacing(SPACE_XS)
        for index, (_key, icon_name, label_key) in enumerate(NAV_ITEMS):
            button = QToolButton(self)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setText(_nav_label(label_key))
            button.setIcon(icons.themed(icon_name, "text_secondary", checked_role="accent"))
            button.setIconSize(icon_qsize(ICON_SIZE_NAV))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("iconName", icon_name)
            button.clicked.connect(lambda _checked=False, i=index: self._on_clicked(i))
            self._group.addButton(button, index)
            nav.addWidget(button)
            self._buttons.append(button)
        layout.addLayout(nav)
        layout.addStretch(1)

        self._account_frame = QFrame(self)
        self._account_frame.setObjectName("sidebarAccount")
        account_layout = QVBoxLayout(self._account_frame)
        account_layout.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        self._account_block = _AccountBlock(self._account_frame)
        self._account_block.clicked.connect(self.account_clicked.emit)
        account_layout.addWidget(self._account_block)
        layout.addWidget(self._account_frame)
        self.set_account(None)

        self._animation = QPropertyAnimation(self, b"minimumWidth", self)
        self._animation.setDuration(MOTION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(lambda value: self.setMaximumWidth(int(value)))

        self._buttons[0].setChecked(True)
        self._sync_collapsed_ui()

    # ---- navigation ------------------------------------------------------------

    def _on_clicked(self, index: int) -> None:
        self.page_selected.emit(index)

    def set_current_index(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    # ---- account block -----------------------------------------------------------

    def set_account(self, account_info: Optional[Tuple[str, str, str, str]]) -> None:
        """(initials, name, status text, status) of the active account, or
        None when there is none."""
        if account_info is None:
            self._account_block.set_account("?", tr("sidebar.no_account"), tr("sidebar.no_account_hint"), "")
        else:
            self._account_block.set_account(*account_info)

    # ---- collapse ------------------------------------------------------------------

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool, animate: bool = False) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        target = SIDEBAR_COLLAPSED_WIDTH if collapsed else SIDEBAR_WIDTH
        if animate:
            self._animation.stop()
            self._animation.setStartValue(self.width())
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self.setFixedWidth(target)
        self._sync_collapsed_ui()
        self.collapsed_changed.emit(collapsed)

    def _sync_collapsed_ui(self) -> None:
        collapsed = self._collapsed
        self._title.setVisible(not collapsed)
        self._logo.setVisible(not collapsed)
        self._toggle.setIcon(icons.themed("expand" if collapsed else "collapse", "text_muted"))
        tooltip = tr("sidebar.expand_tooltip") if collapsed else tr("sidebar.collapse_tooltip")
        self._toggle.setToolTip(tooltip)
        self._toggle.setAccessibleName(tooltip)
        style = Qt.ToolButtonStyle.ToolButtonIconOnly if collapsed else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        for button, (_key, _icon, label_key) in zip(self._buttons, NAV_ITEMS):
            button.setToolButtonStyle(style)
            button.setToolTip(tr(label_key) if collapsed else "")
            button.setAccessibleName(tr(label_key))
        self._account_block.set_collapsed(collapsed)

    # ---- language / theme ------------------------------------------------------------

    def retranslate_ui(self) -> None:
        for button, (_key, _icon_name, label_key) in zip(self._buttons, NAV_ITEMS):
            button.setText(_nav_label(label_key))
        self._sync_collapsed_ui()

    def apply_theme(self) -> None:
        """Icons resolve their colours at paint time; nothing to redo."""
        for button in self._buttons:
            button.update()
