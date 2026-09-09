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

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
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

from app.telegram.media_sender import Attachment
from app.ui import icons, theme
from app.ui.empty_state import build_empty_state
from app.ui.theme import SPACE_SM, SPACE_XS
from app.ui.thumbnails import format_file_size, is_image, make_thumbnail

_TILE_SIZE = 108
_THUMBNAIL_SIZE = 84
_REMOVE_ICON_SIZE = 11


@dataclass
class _Tile:
    image_label: QLabel  # holds either the decoded thumbnail or the file-type icon
    remove_button: QToolButton
    is_image: bool


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

        self._list = QListWidget(self)
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
        item = QListWidgetItem(self._list)
        item.setSizeHint(QSize(_TILE_SIZE, _TILE_SIZE + 46))
        self._list.addItem(item)
        self._list.setItemWidget(item, self._build_tile(item, path))
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
        thumbnail = make_thumbnail(path, _THUMBNAIL_SIZE - 8) if is_image(path) else None
        image_is_thumbnail = thumbnail is not None
        if thumbnail is not None:
            frame.setPixmap(thumbnail)
        else:
            frame.setPixmap(icons.icon("document", tokens.text_muted, 30).pixmap(30, 30))
        column.addWidget(frame)

        name_label = QLabel(_elide(path.name), tile)
        name_label.setObjectName("thumbnailName")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setToolTip(str(path))
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

        self._tiles[id(item)] = _Tile(image_label=frame, remove_button=remove_button, is_image=image_is_thumbnail)
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
        """Re-tint baked document-icon/remove-button pixmaps after a theme
        switch -- QSS alone can't recolor a QIcon/QPixmap, and real image
        thumbnails don't need re-decoding since they carry their own
        colors regardless of theme."""
        color = theme.current_tokens().text_muted
        for tile in self._tiles.values():
            if not tile.is_image:
                tile.image_label.setPixmap(icons.icon("document", color, 30).pixmap(30, 30))
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
