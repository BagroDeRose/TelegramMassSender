"""Account selector: one card per connected account (spec items 7, 11, 37)
-- replaces the earlier combo-box selector, which made the active account
hard to notice at a glance. Each card shows connection state clearly
(never color-only) and carries its own "Use this account"/"Reconnect"/
delete actions, since those are now per-account rather than tied to
whatever happens to be selected in a shared combo.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from app.telegram.account_manager import AccountStatus
from app.ui import icons, theme
from app.ui.empty_state import build_empty_state
from app.ui.theme import SPACE_MD, SPACE_SM, SPACE_XS

_CARD_MAX_WIDTH = 420
_AVATAR_SIZE = 40

# Maps a status variant name to the Tokens field that carries its color --
# "muted" has no same-named token (it's `text_muted`), so this is an
# explicit table rather than a getattr(tokens, variant) guess.
_VARIANT_TOKEN_FIELD = {
    "success": "success",
    "warning": "warning",
    "error": "error",
    "muted": "text_muted",
}


def _status_text_and_variant(status: AccountStatus) -> tuple[str, str]:
    if status.is_authorized:
        return "Подключён", "success"
    if status.connection_error:
        return "Проблема с подключением", "warning"
    if status.needs_reauth:
        return "Требуется повторная авторизация", "error"
    return "Не авторизован", "muted"


def _avatar_initial(account) -> str:
    for candidate in (account.display_name, account.username, account.phone.lstrip("+")):
        if candidate:
            return candidate[0]
    return "?"


class AccountWidget(QWidget):
    account_selected = Signal(int)  # account_id
    add_account_requested = Signal()
    delete_account_requested = Signal(int)  # account_id
    reconnect_requested = Signal(int)  # account_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._statuses: List[AccountStatus] = []
        self._active_account_id: Optional[int] = None
        self._delete_buttons: List[QToolButton] = []
        self._use_buttons: List[QPushButton] = []
        self._reconnect_buttons: List[QPushButton] = []

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE_MD)

        top_row = QHBoxLayout()
        self._add_button = QPushButton("+ Добавить аккаунт", self)
        self._add_button.setObjectName("primaryButton")
        self._add_button.clicked.connect(self.add_account_requested.emit)
        top_row.addWidget(self._add_button)
        top_row.addStretch(1)
        self._layout.addLayout(top_row)

        self._empty_label = build_empty_state(
            "Нет Telegram-аккаунтов", "Добавьте аккаунт, чтобы начать.", self
        )
        self._layout.addWidget(self._empty_label)

        self._cards_container = QVBoxLayout()
        self._cards_container.setSpacing(SPACE_SM)
        self._layout.addLayout(self._cards_container)
        self._layout.addStretch(1)

        self._cards: List[QFrame] = []

    def set_accounts(self, statuses: List[AccountStatus], selected_id: Optional[int] = None) -> None:
        self._statuses = statuses
        self._active_account_id = selected_id
        self._clear_cards()

        self._empty_label.setVisible(not statuses)
        for status in statuses:
            card = self._build_card(status, status.account.id == selected_id)
            self._cards_container.addWidget(card)
            self._cards.append(card)

    def _clear_cards(self) -> None:
        for card in self._cards:
            self._cards_container.removeWidget(card)
            card.deleteLater()
        self._cards = []
        self._delete_buttons = []
        self._use_buttons = []
        self._reconnect_buttons = []

    def _build_card(self, status: AccountStatus, is_active: bool) -> QFrame:
        account = status.account
        card = QFrame(self)
        card.setObjectName("accountCard")
        card.setProperty("active", "true" if is_active else "false")
        card.setMaximumWidth(_CARD_MAX_WIDTH)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        outer.setSpacing(SPACE_SM)

        header = QHBoxLayout()
        header.setSpacing(SPACE_MD)

        tokens = theme.current_tokens()
        avatar_label = QLabel(card)
        avatar_label.setPixmap(
            icons.avatar_pixmap(_avatar_initial(account), tokens.accent, tokens.on_accent, _AVATAR_SIZE)
        )
        avatar_label.setFixedSize(_AVATAR_SIZE, _AVATAR_SIZE)
        header.addWidget(avatar_label, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name_label = QLabel(account.display_name or account.phone, card)
        name_label.setObjectName("accountName")
        text_col.addWidget(name_label)
        if account.username:
            username_label = QLabel(f"@{account.username}", card)
            username_label.setObjectName("accountMeta")
            text_col.addWidget(username_label)

        state_text, variant = _status_text_and_variant(status)
        dot_color = getattr(tokens, _VARIANT_TOKEN_FIELD.get(variant, "text_muted"), tokens.text_muted)
        status_label = QLabel(
            f'<span style="color:{dot_color};">●</span>&nbsp;&nbsp;{state_text}', card
        )
        status_label.setObjectName("accountMeta")
        text_col.addWidget(status_label)

        header.addLayout(text_col, 1)
        outer.addLayout(header)

        actions = QHBoxLayout()
        actions.addStretch(1)
        if status.connection_error:
            reconnect_button = QPushButton("Переподключить", card)
            reconnect_button.setProperty("accountId", account.id)
            reconnect_button.clicked.connect(lambda: self.reconnect_requested.emit(account.id))
            actions.addWidget(reconnect_button)
            self._reconnect_buttons.append(reconnect_button)
        use_button = QPushButton("Активен" if is_active else "Использовать", card)
        use_button.setObjectName("accountUseButton")
        use_button.setProperty("active", "true" if is_active else "false")
        use_button.setProperty("accountId", account.id)
        use_button.setEnabled(not is_active)
        use_button.clicked.connect(lambda: self.account_selected.emit(account.id))
        actions.addWidget(use_button)
        self._use_buttons.append(use_button)

        delete_button = QToolButton(card)
        delete_button.setObjectName("chipRemoveButton")
        delete_button.setProperty("accountId", account.id)
        delete_button.setIcon(icons.icon("close", theme.current_tokens().text_muted, 12))
        delete_button.setToolTip("Удалить аккаунт")
        delete_button.clicked.connect(lambda: self.delete_account_requested.emit(account.id))
        actions.addWidget(delete_button)
        self._delete_buttons.append(delete_button)

        outer.addLayout(actions)
        return card

    def current_account_id(self) -> Optional[int]:
        return self._active_account_id

    def apply_theme(self) -> None:
        """Rebuild the cards after a theme switch -- the avatar pixmap and
        the status-dot color are baked in Python at build time (QSS can't
        reach a QPixmap or inline-HTML QLabel content), so unlike most of
        this app's QSS-only widgets, this one needs an explicit refresh."""
        self.set_accounts(self._statuses, self._active_account_id)

    def refresh_active_state(self, account_id: Optional[int]) -> None:
        """Rebuild the cards to reflect `account_id` as active (or no
        account active, if None) -- the single place this widget's
        displayed state gets resynced to whatever
        app.telegram.account_manager considers active. Works even when
        `account_id` isn't in the cached statuses (e.g. restoring "no
        account was active" after a failed switch), unlike a lookup-first
        variant would."""
        self.set_accounts(self._statuses, account_id)

    def begin_switch(self, account_id: int) -> None:
        """Transitional state while an account switch is in flight:
        disable all account interaction and label the target account's
        button so a click gets immediate feedback instead of silence.
        Cleared by the next refresh_active_state() call (success or
        failure), which rebuilds every card from scratch."""
        self.set_enabled_switching(False)
        for button in self._use_buttons:
            if button.property("accountId") == account_id:
                button.setText("Переключение…")

    def set_enabled_switching(self, enabled: bool) -> None:
        self._add_button.setEnabled(enabled)
        for button in self._delete_buttons:
            button.setEnabled(enabled)
        for button in self._use_buttons:
            button.setEnabled(enabled and button.property("active") != "true")
        for button in self._reconnect_buttons:
            button.setEnabled(enabled)
