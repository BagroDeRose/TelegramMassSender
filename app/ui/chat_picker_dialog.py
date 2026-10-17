""""From my chats…" picker: the active account's groups/supergroups/
channels it can post to, with a type filter, title search and checkboxes.

Purely presentational -- it receives the already-loaded list
(app.telegram.chat_targets.list_writable_chats, called by MainWindow
through the service layer) and returns what was ticked. It never talks
to Telegram itself. Built fresh on each open, so tr() at construction
time is all language switching needs.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr, trn
from app.telegram.chat_targets import ChatTarget, TargetType, target_type_label
from app.ui import icons
from app.ui.dialog_frame import build_dialog_frame
from app.ui.theme import DIALOG_HEIGHT, DIALOG_WIDTH

_FILTER_ALL = "all"
_FILTER_OPTIONS = [
    (_FILTER_ALL, "chat_picker.filter.all"),
    (TargetType.CHANNEL.value, "chat_picker.filter.channels"),
    (TargetType.SUPERGROUP.value, "chat_picker.filter.supergroups"),
    (TargetType.FORUM.value, "chat_picker.filter.forums"),
    (TargetType.GROUP.value, "chat_picker.filter.groups"),
]


class ChatPickerDialog(QDialog):
    def __init__(self, chats: List[ChatTarget], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("chat_picker.title"))
        self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)
        self._chats = list(chats)

        frame = build_dialog_frame(self, tr("chat_picker.title"))
        layout = frame.content

        hint = QLabel(tr("chat_picker.hint"), self)
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        filter_row = QHBoxLayout()
        self._search_edit = QLineEdit(self)
        self._search_edit.addAction(icons.themed("search", "text_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self._search_edit.setPlaceholderText(tr("chat_picker.search_placeholder"))
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._search_edit, 1)
        self._type_combo = QComboBox(self)
        for value, key in _FILTER_OPTIONS:
            self._type_combo.addItem(tr(key), value)
        self._type_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self._type_combo)
        layout.addLayout(filter_row)

        self._list = QListWidget(self)
        for chat in self._chats:
            item = QListWidgetItem(self._item_text(chat))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, chat)
            self._list.addItem(item)
        self._list.itemChanged.connect(self._update_selection_label)
        layout.addWidget(self._list, 1)

        selection_row = QHBoxLayout()
        self._select_all_button = QPushButton(tr("chat_picker.select_visible"), self)
        self._select_all_button.setProperty("variant", "ghost")
        self._select_all_button.clicked.connect(lambda: self._set_visible_checked(True))
        self._select_none_button = QPushButton(tr("chat_picker.select_none"), self)
        self._select_none_button.setProperty("variant", "ghost")
        self._select_none_button.clicked.connect(lambda: self._set_visible_checked(False))
        self._selection_label = QLabel(self)
        self._selection_label.setObjectName("helperText")
        selection_row.addWidget(self._select_all_button)
        selection_row.addWidget(self._select_none_button)
        selection_row.addStretch(1)
        selection_row.addWidget(self._selection_label)
        layout.addLayout(selection_row)

        self._empty_label = QLabel(tr("chat_picker.nothing_matches"), self)
        self._empty_label.setObjectName("helperText")
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        cancel = frame.add_button(QPushButton(tr("dialogs.cancel"), self))
        cancel.clicked.connect(self.reject)
        self._add_button = frame.add_button(QPushButton(tr("chat_picker.add_button"), self), "primary")
        self._add_button.clicked.connect(self.accept)

        self._update_selection_label()

    @staticmethod
    def _item_text(chat: ChatTarget) -> str:
        return f"{chat.title}   ·   {target_type_label(chat.target_type)}   ·   {chat.recipient_line}"

    def _apply_filter(self, *_args) -> None:
        needle = self._search_edit.text().strip().casefold()
        type_filter = self._type_combo.currentData()
        visible = 0
        for row in range(self._list.count()):
            item = self._list.item(row)
            chat: ChatTarget = item.data(Qt.ItemDataRole.UserRole)
            matches_type = type_filter == _FILTER_ALL or chat.target_type.value == type_filter
            matches_text = not needle or needle in chat.title.casefold() or needle in (chat.username or "").casefold()
            hidden = not (matches_type and matches_text)
            item.setHidden(hidden)
            visible += 0 if hidden else 1
        self._empty_label.setVisible(visible == 0)

    def _set_visible_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._list.blockSignals(True)
        for row in range(self._list.count()):
            item = self._list.item(row)
            if not item.isHidden():
                item.setCheckState(state)
        self._list.blockSignals(False)
        self._update_selection_label()

    def _update_selection_label(self, *_args) -> None:
        count = len(self.selected_targets())
        self._selection_label.setText(trn("chat_picker.selected_count", count))
        self._add_button.setEnabled(count > 0)

    def selected_targets(self) -> List[ChatTarget]:
        """Ticked chats in list order -- including ones the current filter
        hides, since filtering only narrows what's shown."""
        return [
            self._list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._list.count())
            if self._list.item(row).checkState() == Qt.CheckState.Checked
        ]
