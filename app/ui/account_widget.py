"""Accounts page content: one card per connected account (initials avatar,
name, @username / phone, a status pill, and its actions), plus the page's
single primary action, "Add account".

Everything is styled through QSS object names and the `status`/`active`
properties -- no colour is baked into a pixmap or inline HTML, so a theme
switch needs no rebuild here.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from app.i18n import tr
from app.telegram.account_manager import AccountStatus
from app.ui import icons
from app.ui.empty_state import build_empty_state, retranslate_empty_state
from app.ui.theme import ACCOUNT_CARD_MAX_WIDTH, ICON_SIZE, SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XS, icon_qsize


def status_text_and_variant(status: AccountStatus) -> tuple[str, str]:
    """(label, status property) for an account's connection state -- shared
    with the sidebar's account block."""
    if status.is_authorized:
        return tr("account_widget.status.connected"), "success"
    if status.connection_error:
        return tr("account_widget.status.connection_problem"), "warning"
    if status.needs_reauth:
        return tr("account_widget.status.reauth_required"), "error"
    return tr("account_widget.status.not_authorized"), ""


# Kept under its old name for callers/tests of the previous version.
_status_text_and_variant = status_text_and_variant


def account_initials(account) -> str:
    """Up to two initials from the name shown on the card."""
    for candidate in (account.local_alias, account.display_name, account.username):
        if candidate:
            words = [w for w in candidate.replace("_", " ").split() if w]
            letters = "".join(w[0] for w in words[:2]) if words else candidate[:1]
            return letters.upper()
    digits = account.phone.lstrip("+")
    return digits[-2:] if digits else "?"


def _avatar_initial(account) -> str:
    return account_initials(account)[:1]


def display_name(account) -> str:
    """A user-set local alias wins over Telegram's own profile name, which
    wins over the phone number."""
    return account.local_alias or account.display_name or account.phone


_display_name = display_name


def make_avatar(text: str, parent: QWidget, large: bool = False) -> QLabel:
    avatar = QLabel(text, parent)
    avatar.setObjectName("avatar")
    avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if large:
        avatar.setProperty("size", "large")
    return avatar


class AccountWidget(QWidget):
    account_selected = Signal(int)  # account_id
    add_account_requested = Signal()
    delete_account_requested = Signal(int)  # account_id
    reconnect_requested = Signal(int)  # account_id
    rename_requested = Signal(int)  # account_id
    try_demo_mode_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._statuses: List[AccountStatus] = []
        self._active_account_id: Optional[int] = None
        self._delete_buttons: List[QToolButton] = []
        self._use_buttons: List[QPushButton] = []
        self._reconnect_buttons: List[QPushButton] = []
        self._rename_buttons: List[QToolButton] = []

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE_MD)

        self._empty_label = build_empty_state(
            tr("account_widget.empty_title"), tr("account_widget.empty_body"), self, icon_name="accounts"
        )
        self._layout.addWidget(self._empty_label)

        self._actions_widget = QWidget(self)
        self._actions_row = QHBoxLayout(self._actions_widget)
        self._actions_row.setContentsMargins(0, 0, 0, 0)
        self._actions_row.setSpacing(SPACE_SM)
        self._add_button = QPushButton(tr("account_widget.add_account_button"), self._actions_widget)
        self._add_button.setProperty("variant", "primary")
        self._add_button.setIcon(icons.themed("add_account", "on_accent"))
        self._add_button.clicked.connect(self.add_account_requested.emit)
        self._try_demo_button = QPushButton(tr("account_widget.try_demo_button"), self._actions_widget)
        self._try_demo_button.setProperty("variant", "ghost")
        self._try_demo_button.clicked.connect(self.try_demo_mode_requested.emit)
        self._actions_row.addWidget(self._add_button)
        self._actions_row.addWidget(self._try_demo_button)
        self._layout.addWidget(self._actions_widget)

        self._cards_container = QVBoxLayout()
        self._cards_container.setSpacing(SPACE_SM)
        self._layout.addLayout(self._cards_container)
        self._layout.addStretch(1)

        self._cards: List[QFrame] = []
        self._sync_empty_layout()

    def set_accounts(self, statuses: List[AccountStatus], selected_id: Optional[int] = None) -> None:
        self._statuses = statuses
        self._active_account_id = selected_id
        self._clear_cards()

        for status in statuses:
            card = self._build_card(status, status.account.id == selected_id)
            self._cards_container.addWidget(card)
            self._cards.append(card)
        self._sync_empty_layout()

    def _sync_empty_layout(self) -> None:
        empty = not self._statuses
        self._empty_label.setVisible(empty)
        # In the empty state the one action sits centred under the message;
        # with accounts listed it's a plain toolbar row above the cards.
        self._layout.setAlignment(
            self._actions_widget, Qt.AlignmentFlag.AlignHCenter if empty else Qt.AlignmentFlag.AlignLeft
        )

    def _clear_cards(self) -> None:
        for card in self._cards:
            self._cards_container.removeWidget(card)
            card.deleteLater()
        self._cards = []
        self._delete_buttons = []
        self._use_buttons = []
        self._reconnect_buttons = []
        self._rename_buttons = []

    def _build_card(self, status: AccountStatus, is_active: bool) -> QFrame:
        account = status.account
        card = QFrame(self)
        card.setObjectName("accountCard")
        card.setProperty("active", "true" if is_active else "false")
        card.setMaximumWidth(ACCOUNT_CARD_MAX_WIDTH)

        row = QHBoxLayout(card)
        row.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_MD, SPACE_MD)
        row.setSpacing(SPACE_MD)

        row.addWidget(make_avatar(account_initials(account), card, large=True), 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(SPACE_XS)
        name = display_name(account)
        name_row = QHBoxLayout()
        name_row.setSpacing(SPACE_XS)
        name_label = QLabel(name, card)
        name_label.setObjectName("accountName")
        name_row.addWidget(name_label)
        rename_button = QToolButton(card)
        rename_button.setProperty("variant", "icon")
        rename_button.setProperty("accountId", account.id)
        rename_button.setIcon(icons.themed("edit", "text_muted"))
        rename_button.setIconSize(icon_qsize(ICON_SIZE))
        rename_button.setToolTip(tr("account_widget.rename_tooltip"))
        # Icon-only: give screen readers a name (a tooltip isn't one).
        rename_button.setAccessibleName(tr("account_widget.rename_tooltip"))
        rename_button.clicked.connect(lambda: self.rename_requested.emit(account.id))
        name_row.addWidget(rename_button)
        name_row.addStretch(1)
        self._rename_buttons.append(rename_button)
        text_col.addLayout(name_row)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(SPACE_SM)
        if account.username:
            username_label = QLabel(f"@{account.username}", card)
            username_label.setObjectName("accountMeta")
            meta_row.addWidget(username_label)
        # Shown unless it would just repeat the title (phone is the name).
        if name != account.phone:
            phone_label = QLabel(account.phone, card)
            phone_label.setObjectName("accountMeta")
            meta_row.addWidget(phone_label)
        meta_row.addStretch(1)
        text_col.addLayout(meta_row)
        row.addLayout(text_col, 1)

        state_text, state = status_text_and_variant(status)
        status_pill = QLabel(state_text, card)
        status_pill.setObjectName("pill")
        status_pill.setProperty("status", state)
        row.addWidget(status_pill, 0, Qt.AlignmentFlag.AlignVCenter)

        if status.connection_error:
            reconnect_button = QPushButton(tr("account_widget.reconnect_button"), card)
            reconnect_button.setIcon(icons.themed("refresh"))
            reconnect_button.setProperty("accountId", account.id)
            reconnect_button.clicked.connect(lambda: self.reconnect_requested.emit(account.id))
            row.addWidget(reconnect_button, 0, Qt.AlignmentFlag.AlignVCenter)
            self._reconnect_buttons.append(reconnect_button)

        use_button = QPushButton(
            tr("account_widget.use_button_active") if is_active else tr("account_widget.use_button_inactive"), card
        )
        use_button.setObjectName("accountUseButton")
        # The active account's button is a state, not an action: quiet, with
        # a check mark. Switching to another account is a normal action.
        use_button.setProperty("variant", "ghost" if is_active else "secondary")
        if is_active:
            use_button.setIcon(icons.themed("check", "success"))
        use_button.setProperty("active", "true" if is_active else "false")
        use_button.setProperty("accountId", account.id)
        use_button.setEnabled(not is_active)
        use_button.clicked.connect(lambda: self.account_selected.emit(account.id))
        row.addWidget(use_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self._use_buttons.append(use_button)

        delete_button = QToolButton(card)
        delete_button.setProperty("variant", "icon")
        delete_button.setProperty("accountId", account.id)
        delete_button.setIcon(icons.themed("delete", "text_muted", active_role="error"))
        delete_button.setIconSize(icon_qsize(ICON_SIZE))
        delete_button.setToolTip(tr("account_widget.delete_tooltip"))
        delete_button.setAccessibleName(tr("account_widget.delete_tooltip"))
        delete_button.clicked.connect(lambda: self.delete_account_requested.emit(account.id))
        row.addWidget(delete_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self._delete_buttons.append(delete_button)
        return card

    def current_account_id(self) -> Optional[int]:
        return self._active_account_id

    def apply_theme(self) -> None:
        """Nothing is baked in any more (avatars, pills and icons all follow
        the active theme by themselves); kept so callers can still ask."""

    def retranslate_ui(self) -> None:
        self._add_button.setText(tr("account_widget.add_account_button"))
        self._try_demo_button.setText(tr("account_widget.try_demo_button"))
        retranslate_empty_state(self._empty_label, tr("account_widget.empty_title"), tr("account_widget.empty_body"))
        self.set_accounts(self._statuses, self._active_account_id)

    def refresh_active_state(self, account_id: Optional[int]) -> None:
        """Rebuild the cards with `account_id` as active (or none)."""
        self.set_accounts(self._statuses, account_id)

    def begin_switch(self, account_id: int) -> None:
        """While a switch is in flight: disable all account interaction and
        label the target's button. Cleared by the next refresh_active_state()."""
        self.set_enabled_switching(False)
        for button in self._use_buttons:
            if button.property("accountId") == account_id:
                button.setText(tr("account_widget.switching"))

    def set_enabled_switching(self, enabled: bool) -> None:
        self._add_button.setEnabled(enabled)
        self._try_demo_button.setEnabled(enabled)
        for button in self._delete_buttons:
            button.setEnabled(enabled)
        for button in self._use_buttons:
            button.setEnabled(enabled and button.property("active") != "true")
        for button in self._reconnect_buttons:
            button.setEnabled(enabled)
        for button in self._rename_buttons:
            button.setEnabled(enabled)

