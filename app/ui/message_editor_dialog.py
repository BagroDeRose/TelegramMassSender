"""Floating, resizable editor window for composing/editing long messages
comfortably -- the inline box in the main window is too small once a
message runs to a few thousand characters, so the "real" editing surface
lives here instead; the main window only shows a compact read-only
preview (see app.ui.message_preview).

Wraps the same MessageEditorWidget used everywhere else, so formatting
logic (toolbar, extraction, round-trip) has exactly one implementation --
this dialog only adds window chrome: geometry persistence for the
session, unsaved-changes confirmation, and a character counter.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QRect
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget
from telethon.tl.types import TypeMessageEntity

from app.ui.message_editor import MessageEditorWidget

_DEFAULT_SIZE = (760, 560)

# Module-level so the dialog reopens at the same size/position within the
# same run of the app (spec: "желательно восстанавливать размер и
# положение окна" -- session-scoped is sufficient, no need to persist to
# disk for this).
_last_geometry: Optional[QRect] = None


def _entities_equal(a: List[TypeMessageEntity], b: List[TypeMessageEntity]) -> bool:
    if len(a) != len(b):
        return False
    key = lambda e: (type(e).__name__, e.offset, e.length)
    for x, y in zip(sorted(a, key=key), sorted(b, key=key)):
        if type(x) is not type(y) or x.offset != y.offset or x.length != y.length:
            return False
        if hasattr(x, "url") and getattr(x, "url", None) != getattr(y, "url", None):
            return False
    return True


class MessageEditorDialog(QDialog):
    def __init__(
        self,
        text: str,
        entities: List[TypeMessageEntity],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Редактор сообщения")
        self.setSizeGripEnabled(True)
        self.setModal(True)

        self._original_text = text
        self._original_entities = entities
        self._result_text = text
        self._result_entities = entities

        layout = QVBoxLayout(self)
        self._editor = MessageEditorWidget(self)
        self._editor.set_content(text, entities)
        layout.addWidget(self._editor, 1)

        footer = QHBoxLayout()
        self._char_count_label = QLabel(self)
        self._char_count_label.setObjectName("charCountLabel")
        footer.addWidget(self._char_count_label)
        footer.addStretch(1)
        cancel_button = QPushButton("Отмена", self)
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("Применить", self)
        apply_button.setObjectName("primaryButton")
        apply_button.setDefault(True)
        apply_button.clicked.connect(self._on_apply)
        footer.addWidget(cancel_button)
        footer.addWidget(apply_button)
        layout.addLayout(footer)

        self._editor.text_edit.textChanged.connect(self._update_char_count)
        self._update_char_count()

        self._restore_geometry()
        self._editor.text_edit.setFocus()

    def _update_char_count(self) -> None:
        self._char_count_label.setText(f"Символов: {self._editor.character_count()}")

    def _restore_geometry(self) -> None:
        if _last_geometry is not None and self._is_geometry_on_screen(_last_geometry):
            self.setGeometry(_last_geometry)
        else:
            self.resize(*_DEFAULT_SIZE)

    @staticmethod
    def _is_geometry_on_screen(rect: QRect) -> bool:
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().intersects(rect):
                return True
        return False

    def _save_geometry(self) -> None:
        global _last_geometry
        _last_geometry = self.geometry()

    def has_unsaved_changes(self) -> bool:
        current_text, current_entities = self._editor.get_content()
        if current_text != self._original_text:
            return True
        return not _entities_equal(current_entities, self._original_entities)

    def _confirm_discard(self) -> bool:
        if not self.has_unsaved_changes():
            return True
        reply = QMessageBox.question(
            self,
            "Несохранённые изменения",
            "Изменения не были применены. Закрыть без сохранения?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_apply(self) -> None:
        self._result_text, self._result_entities = self._editor.get_content()
        self._save_geometry()
        self.accept()

    def reject(self) -> None:
        if not self._confirm_discard():
            return
        self._save_geometry()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        if not self._confirm_discard():
            event.ignore()
            return
        self._save_geometry()
        event.accept()

    def result_content(self) -> Tuple[str, List[TypeMessageEntity]]:
        return self._result_text, self._result_entities
