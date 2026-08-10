"""Account selector: dropdown of connected accounts + add/delete controls
(spec items 7, 11, 37)."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

from app.telegram.account_manager import AccountStatus

_NO_ACCOUNTS_PLACEHOLDER = "Нет подключённых аккаунтов"


class AccountWidget(QWidget):
    account_selected = Signal(int)  # account_id
    add_account_requested = Signal()
    delete_account_requested = Signal(int)  # account_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._combo = QComboBox(self)
        self._combo.currentIndexChanged.connect(self._on_index_changed)
        layout.addWidget(self._combo, 1)

        self._add_button = QPushButton("+ Добавить аккаунт", self)
        self._add_button.setObjectName("primaryButton")
        self._add_button.clicked.connect(self.add_account_requested.emit)
        layout.addWidget(self._add_button)

        self._delete_button = QPushButton("Удалить аккаунт", self)
        self._delete_button.setObjectName("dangerButton")
        self._delete_button.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self._delete_button)

        self._account_ids: List[int] = []

    def set_accounts(self, statuses: List[AccountStatus], selected_id: Optional[int] = None) -> None:
        self._combo.blockSignals(True)
        self._combo.clear()
        self._account_ids = []
        if not statuses:
            self._combo.addItem(_NO_ACCOUNTS_PLACEHOLDER)
        for status in statuses:
            marker = "●" if status.is_authorized else "⚠"
            label = f"{marker} {status.account.phone}"
            if status.needs_reauth:
                label += " (требуется повторная авторизация)"
            self._combo.addItem(label)
            self._account_ids.append(status.account.id)
        if selected_id is not None and selected_id in self._account_ids:
            self._combo.setCurrentIndex(self._account_ids.index(selected_id))
        self._combo.blockSignals(False)
        self._delete_button.setEnabled(bool(statuses))

    def _on_index_changed(self, index: int) -> None:
        if 0 <= index < len(self._account_ids):
            self.account_selected.emit(self._account_ids[index])

    def _on_delete_clicked(self) -> None:
        index = self._combo.currentIndex()
        if 0 <= index < len(self._account_ids):
            self.delete_account_requested.emit(self._account_ids[index])

    def current_account_id(self) -> Optional[int]:
        index = self._combo.currentIndex()
        if 0 <= index < len(self._account_ids):
            return self._account_ids[index]
        return None

    def select_account(self, account_id: int) -> None:
        if account_id in self._account_ids:
            self._combo.blockSignals(True)
            self._combo.setCurrentIndex(self._account_ids.index(account_id))
            self._combo.blockSignals(False)

    def set_enabled_switching(self, enabled: bool) -> None:
        self._combo.setEnabled(enabled)
        self._add_button.setEnabled(enabled)
        self._delete_button.setEnabled(enabled and bool(self._account_ids))
