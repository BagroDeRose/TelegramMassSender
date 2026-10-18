""""From my chats…" picker: every dialog of the active account -- people,
bots, groups, supergroups, forums, channels -- with a type filter, folder
filter, archive toggle, search and checkboxes.

Purely presentational: it never talks to Telegram. MainWindow loads the
list through the service layer (app.telegram.chat_targets.list_dialogs)
and hands it in with set_dialogs(); "Refresh" only emits
refresh_requested. The dialog opens at once in its loading state, so a
slow or large dialog list never blocks the window. Built fresh on each
open, so tr() at construction time is all language switching needs.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.telegram.chat_targets import DialogCategory, DialogList, DialogTarget
from app.ui import icons, theme
from app.ui.dialog_frame import build_dialog_frame
from app.ui.dialog_picker_model import (
    DialogFilterProxy,
    DialogListModel,
    DialogRowDelegate,
    selection_breakdown,
)
from app.ui.empty_state import build_empty_state, retranslate_empty_state
from app.ui.results_view import SegmentedControl
from app.ui.theme import DIALOG_PICKER_HEIGHT, DIALOG_PICKER_WIDTH, SPACE_SM

_TYPE_FILTERS = [
    (None, "chat_picker.filter.all"),
    (DialogCategory.PEOPLE, "chat_picker.filter.people"),
    (DialogCategory.GROUPS, "chat_picker.filter.groups"),
    (DialogCategory.CHANNELS, "chat_picker.filter.channels"),
    (DialogCategory.BOTS, "chat_picker.filter.bots"),
]

_PAGE_LIST, _PAGE_LOADING, _PAGE_MESSAGE = 0, 1, 2


class ChatPickerDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self, existing_keys: Iterable[str] = (), parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("chat_picker.title"))
        self.resize(DIALOG_PICKER_WIDTH, DIALOG_PICKER_HEIGHT)
        self._loaded = False

        self._model = DialogListModel(parent=self)
        self._model.set_existing_keys(existing_keys)
        self._proxy = DialogFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        frame = build_dialog_frame(self, tr("chat_picker.title"))
        layout = frame.content

        hint = QLabel(tr("chat_picker.hint"), self)
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._type_filter = SegmentedControl(self)
        for value, key in _TYPE_FILTERS:
            self._type_filter.addItem(tr(key), value)
        self._type_filter.currentIndexChanged.connect(self._on_type_changed)
        type_row = QHBoxLayout()
        type_row.addWidget(self._type_filter)
        type_row.addStretch(1)
        self._refresh_button = QPushButton(tr("chat_picker.refresh"), self)
        self._refresh_button.setIcon(icons.themed("refresh", "text_secondary"))
        self._refresh_button.setIconSize(theme.icon_qsize())
        self._refresh_button.setProperty("variant", "ghost")
        self._refresh_button.setToolTip(tr("chat_picker.refresh_tooltip"))
        self._refresh_button.clicked.connect(self._on_refresh_clicked)
        type_row.addWidget(self._refresh_button)
        layout.addLayout(type_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(SPACE_SM)
        self._search_edit = QLineEdit(self)
        self._search_edit.addAction(icons.themed("search", "text_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self._search_edit.setPlaceholderText(tr("chat_picker.search_placeholder"))
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_search_changed)
        filter_row.addWidget(self._search_edit, 1)
        self._folder_combo = QComboBox(self)
        self._folder_combo.setToolTip(tr("chat_picker.folder_tooltip"))
        self._folder_combo.currentIndexChanged.connect(self._on_folder_changed)
        self._folder_combo.setVisible(False)
        filter_row.addWidget(self._folder_combo)
        self._archive_toggle = QCheckBox(tr("chat_picker.show_archive"), self)
        self._archive_toggle.toggled.connect(self._on_archive_toggled)
        filter_row.addWidget(self._archive_toggle)
        layout.addLayout(filter_row)

        self._pages = QStackedWidget(self)
        self._list = QListView(self._pages)
        self._list.setObjectName("dialogPickerList")
        self._list.setModel(self._proxy)
        self._list.setItemDelegate(DialogRowDelegate(self._list))
        self._list.setUniformItemSizes(True)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setMouseTracking(True)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pages.addWidget(self._list)

        loading = QWidget(self._pages)
        loading_layout = QVBoxLayout(loading)
        loading_layout.addStretch(1)
        self._loading_state = build_empty_state(
            tr("chat_picker.loading_title"), tr("chat_picker.loading_body"), loading, icon_name="hourglass"
        )
        loading_layout.addWidget(self._loading_state)
        self._loading_bar = QProgressBar(loading)
        self._loading_bar.setRange(0, 0)  # indeterminate
        self._loading_bar.setTextVisible(False)
        loading_layout.addWidget(self._loading_bar)
        loading_layout.addStretch(1)
        self._pages.addWidget(loading)

        self._message_state = build_empty_state("", "", self._pages, icon_name="chats")
        self._pages.addWidget(self._message_state)
        layout.addWidget(self._pages, 1)

        selection_row = QHBoxLayout()
        self._select_all_button = QPushButton(tr("chat_picker.select_visible"), self)
        self._select_all_button.setProperty("variant", "ghost")
        self._select_all_button.clicked.connect(lambda: self._set_visible_checked(True))
        self._select_none_button = QPushButton(tr("chat_picker.select_none"), self)
        self._select_none_button.setProperty("variant", "ghost")
        self._select_none_button.clicked.connect(lambda: self._set_visible_checked(False))
        selection_row.addWidget(self._select_all_button)
        selection_row.addWidget(self._select_none_button)
        selection_row.addStretch(1)
        layout.addLayout(selection_row)

        self._selection_label = QLabel(self)
        self._selection_label.setObjectName("helperText")
        frame.footer_left.addWidget(self._selection_label)
        cancel = frame.add_button(QPushButton(tr("dialogs.cancel"), self))
        cancel.clicked.connect(self.reject)
        self._add_button = frame.add_button(QPushButton(tr("chat_picker.add_button"), self), "primary")
        self._add_button.clicked.connect(self.accept)

        self._model.dataChanged.connect(self._update_selection_label)
        self._model.modelReset.connect(self._update_selection_label)
        self._proxy.layoutChanged.connect(self._update_view_state)
        self._proxy.rowsInserted.connect(self._update_view_state)
        self._proxy.rowsRemoved.connect(self._update_view_state)
        self._proxy.modelReset.connect(self._update_view_state)

        self.setTabOrder(self._search_edit, self._folder_combo)
        self.setTabOrder(self._folder_combo, self._archive_toggle)
        self.setTabOrder(self._archive_toggle, self._list)
        self.set_loading()
        self._search_edit.setFocus()

    # ---- states fed by MainWindow ------------------------------------------------

    def set_loading(self) -> None:
        self._pages.setCurrentIndex(_PAGE_LOADING)
        self._set_controls_enabled(False)
        self._update_selection_label()

    def set_dialogs(self, result: DialogList) -> None:
        self._loaded = True
        folder_id = self._folder_combo.currentData()
        self._folder_combo.blockSignals(True)
        self._folder_combo.clear()
        self._folder_combo.addItem(tr("chat_picker.folder_all"), None)
        for folder in result.folders:
            self._folder_combo.addItem(folder.title, folder.folder_id)
        index = self._folder_combo.findData(folder_id)
        self._folder_combo.setCurrentIndex(max(0, index))
        self._folder_combo.blockSignals(False)
        self._folder_combo.setVisible(bool(result.folders))
        self._proxy.set_folder(self._folder_combo.currentData())
        self._model.set_dialogs(result.dialogs)
        self._set_controls_enabled(True)
        self._update_view_state()

    def set_error(self, message: str) -> None:
        """Loading failed: say why; Refresh stays available."""
        self._set_controls_enabled(False)
        self._refresh_button.setEnabled(True)
        self._show_message(tr("chat_picker.error_title"), message, "warning")
        self._update_selection_label()

    def set_existing_keys(self, keys: Iterable[str]) -> None:
        self._model.set_existing_keys(keys)

    # ---- results --------------------------------------------------------------------

    def selected_targets(self) -> List[DialogTarget]:
        """Ticked dialogs, newest first -- including ones the current
        filter hides, since filtering only narrows what's shown."""
        return self._model.checked_targets()

    def selected_lines(self) -> List[str]:
        return [target.recipient_line for target in self.selected_targets()]

    # ---- internals ------------------------------------------------------------------

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self._type_filter,
            self._search_edit,
            self._folder_combo,
            self._archive_toggle,
            self._select_all_button,
            self._select_none_button,
            self._refresh_button,
        ):
            widget.setEnabled(enabled)

    def _show_message(self, title: str, body: str, icon_name: str) -> None:
        retranslate_empty_state(self._message_state, title, body)
        icon_label = self._message_state.findChild(QLabel, "emptyStateIcon")
        if icon_label is not None:
            icon_label.setProperty("iconName", icon_name)
            icon_label.setPixmap(
                icons.themed_pixmap(icon_name, "text_muted", theme.ICON_SIZE_EMPTY, icon_label.devicePixelRatioF())
            )
        self._pages.setCurrentIndex(_PAGE_MESSAGE)

    def _update_view_state(self, *_args) -> None:
        if not self._loaded:
            return
        if self._model.rowCount() == 0:
            self._show_message(tr("chat_picker.empty_title"), tr("chat_picker.empty"), "chats")
        elif self._proxy.rowCount() == 0:
            self._show_message(tr("chat_picker.nothing_matches"), tr("chat_picker.nothing_matches_body"), "search")
        else:
            self._pages.setCurrentIndex(_PAGE_LIST)
        has_rows = self._proxy.rowCount() > 0
        self._select_all_button.setEnabled(has_rows)
        self._select_none_button.setEnabled(has_rows)

    def _on_type_changed(self, *_args) -> None:
        self._proxy.set_category(self._type_filter.currentData())
        self._update_view_state()

    def _on_folder_changed(self, *_args) -> None:
        self._proxy.set_folder(self._folder_combo.currentData())
        self._update_view_state()

    def _on_archive_toggled(self, checked: bool) -> None:
        self._proxy.set_show_archived(checked)
        self._update_view_state()

    def _on_search_changed(self, text: str) -> None:
        self._proxy.set_search_text(text)
        self._update_view_state()

    def _on_refresh_clicked(self) -> None:
        self.set_loading()
        self.refresh_requested.emit()

    def _set_visible_checked(self, checked: bool) -> None:
        self._model.set_rows_checked(self._proxy.visible_source_rows(), checked)

    def _update_selection_label(self, *_args) -> None:
        targets = self.selected_targets()
        count = len(targets)
        if count == 0:
            text = tr("chat_picker.selected_none")
        else:
            counts = selection_breakdown(targets)
            parts = [tr("chat_picker.selected_people", count=counts["people"])]
            if counts["bots"]:
                parts.append(tr("chat_picker.selected_bots", count=counts["bots"]))
            parts.append(tr("chat_picker.selected_chats", count=counts["chats"]))
            text = tr("chat_picker.selected_summary", count=count, parts=", ".join(parts))
        self._selection_label.setText(text)
        self._add_button.setEnabled(count > 0)
