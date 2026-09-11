"""Attachment list widget: add via file dialog or drag & drop, remove,
clear (spec items 18-19, 50). Wraps app.telegram.media_sender.Attachment
so downstream code (the send plan) can consume the list directly.

Presentation: a compact grid of tiles. Image files get a real (memory-
conscious, scaled-decode) thumbnail via app.ui.thumbnails; everything else
gets a generic document tile with filename + size. Order is exactly
insertion order -- matches app.telegram.media_sender's own send order.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.telegram.media_sender import Attachment, AttachmentKind, kind_for_path
from app.ui import icons, theme
from app.ui.empty_state import build_empty_state
from app.ui.theme import SPACE_SM, SPACE_XS
from app.ui.thumbnails import format_file_size, is_image, make_thumbnail

_TILE_SIZE = 108
_THUMBNAIL_SIZE = 84
_REMOVE_ICON_SIZE = 11
_FILE_ICON_SIZE = 30

# Which icons.py glyph represents each AttachmentKind in a tile that isn't
# showing a real decoded thumbnail. PHOTO/ANIMATION/IMAGE_OTHER are omitted
# on purpose: they normally get a real thumbnail (see THUMBNAILABLE_KINDS in
# media_sender.py) and only reach this fallback for a corrupted/unreadable
# file, same as any other kind -- the generic document glyph is an honest,
# unchanged-from-before fallback for that rare case, not a missing icon.
_ICON_NAME_FOR_KIND = {
    AttachmentKind.VIDEO: "video",
    AttachmentKind.AUDIO: "audio",
    AttachmentKind.ARCHIVE: "archive",
}
_DEFAULT_ICON_NAME = "document"


def _icon_name_for(path: Path) -> str:
    return _ICON_NAME_FOR_KIND.get(kind_for_path(path), _DEFAULT_ICON_NAME)


@dataclass
class _Tile:
    image_label: QLabel  # holds either the decoded thumbnail or the file-type icon
    remove_button: QToolButton
    is_image: bool
    icon_name: str = _DEFAULT_ICON_NAME  # which glyph is shown when is_image is False


_REORDER_MIME_TYPE = "application/x-telegrammasssender-attachment-row"


class _ReorderableListWidget(QListWidget):
    """QListWidget with drag-to-reorder detected via plain mouse events and
    a minimal hand-rolled QDrag, rather than Qt's built-in
    setDragDropMode(InternalMove).

    Every item here carries a fully custom tile widget attached via
    setItemWidget() (thumbnail/icon, filename, remove button). Qt's
    built-in item-view drag-and-drop reorders by round-tripping each
    dragged row's *model data* (text/icon/decoration roles) through
    mimeData()/dropMimeData() -- it has no mechanism to carry a
    setItemWidget()-attached widget across that round-trip, so enabling
    InternalMove here would silently drop each moved tile's thumbnail/
    icon/remove-button. Instead, a drag only ever carries the source row
    index as private MIME data; the actual reorder is done by the owning
    AttachmentsWidget mutating its own path list and rebuilding tiles from
    scratch (see AttachmentsWidget._rebuild_tiles), reusing the same,
    already-tested per-tile construction used for a normal add_file().

    Movement stays Static throughout (unchanged from before this class
    existed) -- this is about the *order* changing, not items being
    freely repositioned to arbitrary pixel coordinates.
    """

    tile_reorder_requested = Signal(int, int)  # from_row, to_row
    files_dropped = Signal(list)  # List[str] local file paths from an external (e.g. Explorer) drag

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # Required for dragEnterEvent/dropEvent below to be delivered to
        # this widget at all -- for both the internal reorder drag and an
        # external file drag landing directly on the (populated) tile
        # grid. AttachmentsWidget's own setAcceptDrops(True) still handles
        # an external drop while the grid is empty/hidden.
        self.setAcceptDrops(True)
        self._press_row: Optional[int] = None
        self._press_pos = None
        # QAbstractItemView's internal viewportEvent() forwards a press to
        # this widget's own mousePressEvent() override, but does not
        # reliably do the same for a subsequent mouse move while no
        # QAbstractItemView-native drag is configured (confirmed
        # empirically: mousePressEvent fired, mouseMoveEvent never did, for
        # the same physical gesture) -- an event filter installed directly
        # on the viewport sees the real, raw mouse events instead, so drag
        # detection lives here rather than in a mouseMoveEvent override.
        # The viewport is cached once here rather than re-calling
        # self.viewport() inside eventFilter: PySide6 can hand back a fresh
        # Python wrapper object for the same underlying C++ widget on each
        # call, which makes an `is` identity check against a freshly
        # re-fetched self.viewport() unreliable (confirmed empirically --
        # the very first event matched, later ones silently didn't).
        self._viewport = self.viewport()
        self._viewport.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt override)
        # No identity/equality check against self._viewport here: this
        # filter is only ever installed on that one object, so `watched`
        # can only be it -- an `is`/`==` re-check proved unreliable in
        # practice (PySide6 can hand back event-delivery wrapper objects
        # that don't compare equal to a separately-cached Python reference
        # for the same underlying C++ widget), and checking membership by
        # install-time guarantee instead of by comparing wrapper objects
        # sidesteps that entirely.
        event_type = event.type()
        if event_type == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            self._press_row = index.row() if index.isValid() else None
            self._press_pos = event.position().toPoint()
        elif event_type == QEvent.Type.MouseMove and self._press_row is not None:
            if (
                bool(event.buttons() & Qt.MouseButton.LeftButton)
                and self._press_pos is not None
                and (event.position().toPoint() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                row = self._press_row
                self._press_row = None
                self._press_pos = None
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData(_REORDER_MIME_TYPE, str(row).encode("ascii"))
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.MoveAction)
                return True  # consumed -- don't let the base view also treat this as a selection drag
        elif event_type == QEvent.Type.MouseButtonRelease:
            self._press_row = None
            self._press_pos = None
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasFormat(_REORDER_MIME_TYPE) or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasFormat(_REORDER_MIME_TYPE) or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        mime = event.mimeData()
        if mime.hasFormat(_REORDER_MIME_TYPE):
            source_row = int(bytes(mime.data(_REORDER_MIME_TYPE)).decode("ascii"))
            index = self.indexAt(event.position().toPoint())
            target_row = index.row() if index.isValid() else self.count() - 1
            event.acceptProposedAction()
            if target_row >= 0 and target_row != source_row:
                self.tile_reorder_requested.emit(source_row, target_row)
        elif mime.hasUrls():
            paths = [url.toLocalFile() for url in mime.urls() if url.toLocalFile()]
            event.acceptProposedAction()
            if paths:
                self.files_dropped.emit(paths)


class AttachmentsWidget(QWidget):
    attachments_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._paths: List[Path] = []
        self._tiles: Dict[int, _Tile] = {}  # id(QListWidgetItem) -> its themed parts

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        self._empty_label = build_empty_state(
            "Нет вложений", "Перетащите файлы сюда или нажмите «Добавить файл»", self
        )
        layout.addWidget(self._empty_label)

        self._list = _ReorderableListWidget(self)
        self._list.setViewMode(QListView.ViewMode.IconMode)
        self._list.setFlow(QListView.Flow.LeftToRight)
        self._list.setWrapping(True)
        self._list.setResizeMode(QListView.ResizeMode.Adjust)
        self._list.setMovement(QListView.Movement.Static)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.setSpacing(SPACE_SM)
        self._list.setUniformItemSizes(True)
        self._list.hide()
        self._list.tile_reorder_requested.connect(self._on_tile_reorder_requested)
        self._list.files_dropped.connect(self._on_files_dropped_on_list)
        layout.addWidget(self._list)

        buttons = QHBoxLayout()
        self._add_button = QPushButton("Добавить файл", self)
        self._add_button.clicked.connect(self._on_add_clicked)
        remove_button = QPushButton("Удалить выбранное", self)
        remove_button.clicked.connect(self._on_remove_clicked)
        clear_button = QPushButton("Очистить", self)
        clear_button.setObjectName("ghostButton")
        clear_button.clicked.connect(self._on_clear_clicked)
        buttons.addWidget(self._add_button)
        buttons.addWidget(remove_button)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._sync_empty_state()

    # ---- adding / removing ---------------------------------------------------

    def _on_add_clicked(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Выбрать файлы")
        for file_path in files:
            self.add_file(Path(file_path))

    def _on_remove_clicked(self) -> None:
        for item in self._list.selectedItems():
            self._remove_item(item)

    def _on_clear_clicked(self) -> None:
        self._list.clear()
        self._paths.clear()
        self._tiles.clear()
        self._sync_empty_state()
        self.attachments_changed.emit()

    def _remove_item(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if row < 0:
            return
        self._tiles.pop(id(item), None)
        self._list.takeItem(row)
        del self._paths[row]
        self._sync_empty_state()
        self.attachments_changed.emit()

    def add_file(self, path: Path) -> None:
        if path in self._paths:
            return
        self._paths.append(path)
        self._append_tile(path)
        self._sync_empty_state()
        self.attachments_changed.emit()

    def _on_files_dropped_on_list(self, paths: List[str]) -> None:
        # Forwarded from _ReorderableListWidget for an external file drag
        # landing directly on the (already populated, thus visible) tile
        # grid -- add_file already de-dupes and emits attachments_changed.
        for file_path in paths:
            self.add_file(Path(file_path))

    def _on_tile_reorder_requested(self, source_row: int, target_row: int) -> None:
        if not (0 <= source_row < len(self._paths)) or not (0 <= target_row < len(self._paths)):
            return  # stale/out-of-range row -- ignore rather than corrupt order
        path = self._paths.pop(source_row)
        self._paths.insert(target_row, path)
        self._rebuild_tiles()

    def _append_tile(self, path: Path) -> None:
        item = QListWidgetItem(self._list)
        item.setSizeHint(QSize(_TILE_SIZE, _TILE_SIZE + 46))
        self._list.addItem(item)
        self._list.setItemWidget(item, self._build_tile(item, path))

    def _rebuild_tiles(self) -> None:
        """Rebuild every tile from self._paths, in its current order. Used
        after a reorder rather than trying to move the existing
        QListWidgetItem/setItemWidget pair in place -- Qt's item-view
        drag-and-drop machinery does not preserve a setItemWidget()
        widget across a move (see _ReorderableListWidget), so a full
        rebuild via the same per-path tile construction add_file() already
        uses is the simplest way to guarantee the displayed tiles always
        match self._paths exactly, without a second, parallel code path."""
        self._list.clear()
        self._tiles.clear()
        for path in self._paths:
            self._append_tile(path)
        self._sync_empty_state()
        self.attachments_changed.emit()

    def _build_tile(self, item: QListWidgetItem, path: Path) -> QWidget:
        tokens = theme.current_tokens()
        tile = QWidget(self._list)
        tile.setFixedWidth(_TILE_SIZE)
        column = QVBoxLayout(tile)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        frame = QLabel(tile)
        frame.setObjectName("thumbnailTile")
        frame.setFixedSize(_TILE_SIZE, _THUMBNAIL_SIZE)
        frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Purely decorative -- let a press/drag started here pass through to
        # the list widget underneath instead of being swallowed by the
        # label, so dragging by the thumbnail (the most natural place to
        # grab a tile) actually reaches _ReorderableListWidget's handlers.
        frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        thumbnail = make_thumbnail(path, _THUMBNAIL_SIZE - 8) if is_image(path) else None
        image_is_thumbnail = thumbnail is not None
        icon_name = _icon_name_for(path)
        if thumbnail is not None:
            frame.setPixmap(thumbnail)
        else:
            frame.setPixmap(icons.icon(icon_name, tokens.text_muted, _FILE_ICON_SIZE).pixmap(_FILE_ICON_SIZE, _FILE_ICON_SIZE))
        column.addWidget(frame)

        name_label = QLabel(_elide(path.name), tile)
        name_label.setObjectName("thumbnailName")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setToolTip(str(path))
        name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        column.addWidget(name_label)

        if not image_is_thumbnail:
            try:
                size_text = format_file_size(path.stat().st_size)
            except OSError:
                size_text = ""
            if size_text:
                meta_label = QLabel(size_text, tile)
                meta_label.setObjectName("thumbnailMeta")
                meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                meta_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                column.addWidget(meta_label)

        remove_button = QToolButton(tile)
        remove_button.setObjectName("chipRemoveButton")
        remove_button.setIcon(icons.icon("close", tokens.text_muted, _REMOVE_ICON_SIZE))
        remove_button.setText(" Удалить")
        remove_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        remove_button.setToolTip("Удалить вложение")
        remove_button.clicked.connect(lambda: self._remove_item(item))
        remove_row = QHBoxLayout()
        remove_row.setContentsMargins(0, 0, 0, 0)
        remove_row.addStretch(1)
        remove_row.addWidget(remove_button)
        remove_row.addStretch(1)
        column.addLayout(remove_row)

        self._tiles[id(item)] = _Tile(
            image_label=frame, remove_button=remove_button, is_image=image_is_thumbnail, icon_name=icon_name
        )
        return tile

    def _sync_empty_state(self) -> None:
        has_items = bool(self._paths)
        self._empty_label.setVisible(not has_items)
        self._list.setVisible(has_items)

    # ---- drag & drop ------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if local_path:
                self.add_file(Path(local_path))
        event.acceptProposedAction()

    # ---- theming -------------------------------------------------------------

    def apply_theme(self) -> None:
        """Re-tint baked file-icon/remove-button pixmaps after a theme
        switch -- QSS alone can't recolor a QIcon/QPixmap, and real image
        thumbnails don't need re-decoding since they carry their own
        colors regardless of theme. Each tile remembers which glyph it
        was built with (icon_name) so re-tinting doesn't collapse every
        non-image tile back to the generic document icon."""
        color = theme.current_tokens().text_muted
        for tile in self._tiles.values():
            if not tile.is_image:
                tile.image_label.setPixmap(icons.icon(tile.icon_name, color, _FILE_ICON_SIZE).pixmap(_FILE_ICON_SIZE, _FILE_ICON_SIZE))
            tile.remove_button.setIcon(icons.icon("close", color, _REMOVE_ICON_SIZE))

    # ---- public API used by app.ui.main_window --------------------------------

    def get_attachments(self) -> List[Attachment]:
        return [Attachment(path=p) for p in self._paths]

    def is_empty(self) -> bool:
        return not self._paths

    def missing_files(self) -> List[Path]:
        return [p for p in self._paths if not p.is_file()]


def _elide(text: str, max_chars: int = 16) -> str:
    """Character-count elision, not pixel-measured -- the tile has a fixed
    width and this app's font, so a fixed budget is good enough and avoids
    needing a QFontMetrics instance at tile-build time."""
    if len(text) <= max_chars:
        return text
    stem, _, ext = text.rpartition(".")
    if not stem:
        return text[: max_chars - 2] + "…"
    return f"{stem[:10]}…{('.' + ext) if ext else ''}"
