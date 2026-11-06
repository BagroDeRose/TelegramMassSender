"""Floating, resizable editor window for composing/editing long messages
comfortably -- the inline box in the main window is too small once a
message runs to a few thousand characters, so the "real" editing surface
lives here instead; the main window only shows a compact read-only
preview (see app.ui.message_preview).

Wraps the same MessageEditorWidget used everywhere else, so formatting
logic (toolbar, extraction, round-trip) has exactly one implementation --
this dialog only adds window chrome: geometry persistence for the
session, unsaved-changes confirmation, a character counter (against the
caption limit when the message has media) and the message options block
(app.ui.message_options_widget: order of text and media, link preview).
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QRect
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPushButton, QWidget
from telethon.tl.types import TypeMessageEntity

from app.i18n import tr
from app.telegram.media_sender import Attachment
from app.telegram.message_options import DEFAULT_CAPTION_LIMIT, MessageOptions, utf16_len
from app.telegram.template import expand_name_placeholder
from app.ui import theme
from app.ui.dialog_frame import build_dialog_frame
from app.ui.message_editor import MessageEditorWidget
from app.ui.message_options_widget import MessageOptionsWidget, format_count
from app.ui.theme import EDITOR_DIALOG_HEIGHT, EDITOR_DIALOG_WIDTH

_DEFAULT_SIZE = (EDITOR_DIALOG_WIDTH, EDITOR_DIALOG_HEIGHT)

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
        attachments: Sequence[Attachment] = (),
        caption_limit: int = DEFAULT_CAPTION_LIMIT,
        options: Optional[MessageOptions] = None,
        example_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("message_editor_dialog.title"))
        self.setSizeGripEnabled(True)
        self.setModal(True)

        self._original_text = text
        self._original_entities = entities
        self._result_text = text
        self._result_entities = entities
        self._attachments = list(attachments)
        self._caption_limit = caption_limit
        self._example_name = example_name
        self._result_options = options or MessageOptions()

        frame = build_dialog_frame(self)
        self._editor = MessageEditorWidget(self)
        self._editor.set_content(text, entities)
        frame.content.addWidget(self._editor, 1)
        self._options_widget = MessageOptionsWidget(self)
        self._options_widget.set_options(self._result_options)
        self._options_widget.options_changed.connect(self._update_char_count)
        frame.content.addWidget(self._options_widget)

        self._char_count_label = QLabel(self)
        self._char_count_label.setObjectName("charCountLabel")
        frame.footer_left.addWidget(self._char_count_label)
        cancel_button = frame.add_button(QPushButton(tr("message_editor_dialog.cancel_button"), self))
        cancel_button.clicked.connect(self.reject)
        apply_button = frame.add_button(QPushButton(tr("message_editor_dialog.apply_button"), self), "primary")
        apply_button.clicked.connect(self._on_apply)

        self._editor.text_edit.textChanged.connect(self._update_char_count)
        self._update_char_count()

        self._restore_geometry()
        self._editor.text_edit.setFocus()

    def _update_char_count(self) -> None:
        text, entities = self._editor.get_content()
        example_text, example_entities = expand_name_placeholder(text, entities, self._example_name)
        self._options_widget.set_context(
            text, entities, self._attachments, self._caption_limit, example_text, example_entities
        )
        if self._attachments:
            # With media the text is first of all a caption: count it the
            # way Telegram does (UTF-16, with the example name) against
            # the account's caption limit.
            length = utf16_len(example_text)
            self._char_count_label.setText(
                tr(
                    "message_editor_dialog.char_count_caption",
                    count=format_count(length),
                    limit=format_count(self._caption_limit),
                )
            )
            theme.set_property(self._char_count_label, "status", "warning" if length > self._caption_limit else "")
        else:
            self._char_count_label.setText(tr("message_editor_dialog.char_count", count=self._editor.character_count()))
            theme.set_property(self._char_count_label, "status", "")

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
        # Custom Yes/No buttons rather than QMessageBox.StandardButton.Yes/No
        # -- the stock buttons render in whatever language Qt's own bundled
        # translations pick (no Qt translator is loaded here), ignoring the
        # app's selected language entirely; every other confirmation dialog
        # in the app already uses this same custom-button pattern (see
        # app.ui.dialogs).
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("message_editor_dialog.unsaved_title"))
        box.setText(tr("message_editor_dialog.unsaved_message"))
        no_button = box.addButton(tr("message_editor_dialog.unsaved_no"), QMessageBox.ButtonRole.NoRole)
        yes_button = box.addButton(tr("message_editor_dialog.unsaved_yes"), QMessageBox.ButtonRole.YesRole)
        yes_button.setProperty("variant", "danger")
        # "No" (don't discard) stays the default button, matching the
        # original QMessageBox.question(..., defaultButton=No) behavior --
        # accidentally hitting Enter must never discard unsaved work.
        box.setDefaultButton(no_button)
        box.exec()
        return box.clickedButton() is yes_button

    def _on_apply(self) -> None:
        self._result_text, self._result_entities = self._editor.get_content()
        self._result_options = self._options_widget.options()
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

    def result_options(self) -> MessageOptions:
        return self._result_options

    @property
    def options_widget(self) -> MessageOptionsWidget:
        return self._options_widget
