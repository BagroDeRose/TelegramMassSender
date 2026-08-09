"""Attachment list widget: add via file dialog or drag & drop, remove,
clear (spec items 18-19, 50). Wraps app.telegram.media_sender.Attachment
so downstream code (the send plan) can consume the list directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.telegram.media_sender import Attachment

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_VIDEO_EXT = {".mp4", ".mov", ".avi"}


def _icon_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _IMAGE_EXT:
        return "🖼"
    if suffix in _VIDEO_EXT:
        return "🎬"
    return "📄"


class AttachmentsWidget(QWidget):
    attachments_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._paths: List[Path] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self._list)

        buttons = QHBoxLayout()
        add_button = QPushButton("📎 Добавить медиафайл", self)
        add_button.clicked.connect(self._on_add_clicked)
        remove_button = QPushButton("Удалить", self)
        remove_button.clicked.connect(self._on_remove_clicked)
        clear_button = QPushButton("Очистить", self)
        clear_button.clicked.connect(self._on_clear_clicked)
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def _on_add_clicked(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Выбрать файлы")
        for file_path in files:
            self.add_file(Path(file_path))

    def _on_remove_clicked(self) -> None:
        for item in self._list.selectedItems():
            row = self._list.row(item)
            self._list.takeItem(row)
            del self._paths[row]
        self.attachments_changed.emit()

    def _on_clear_clicked(self) -> None:
        self._list.clear()
        self._paths.clear()
        self.attachments_changed.emit()

    def add_file(self, path: Path) -> None:
        if path in self._paths:
            return
        self._paths.append(path)
        item = QListWidgetItem(f"{_icon_for(path)} {path.name}")
        item.setToolTip(str(path))
        self._list.addItem(item)
        self.attachments_changed.emit()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if local_path:
                self.add_file(Path(local_path))
        event.acceptProposedAction()

    def get_attachments(self) -> List[Attachment]:
        return [Attachment(path=p) for p in self._paths]

    def is_empty(self) -> bool:
        return not self._paths

    def missing_files(self) -> List[Path]:
        return [p for p in self._paths if not p.is_file()]
