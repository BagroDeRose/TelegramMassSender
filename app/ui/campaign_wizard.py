"""Optional step-by-step Campaign Wizard --
guides Recipients -> Message -> Attachments -> Sending options -> Preview
-> Confirmation. Every step reuses the exact widget classes the existing
single-page Campaign workflow already uses (RecipientWidget,
MessageEditorDialog, AttachmentsWidget, MessagePreviewWidget), so no
parsing/validation/formatting logic is duplicated here -- the wizard is
just a guided, ordered way to fill in the same state the Campaign page
already holds.

"Sending" and "Results" (the spec's last two steps) are deliberately NOT
separate wizard pages: app.ui.main_window.MainWindow already owns one
live-progress UI (CampaignControlsWidget + the journal + the Results
page), wired to pause/resume/stop and FloodWait handling. A second,
wizard-internal progress display would either duplicate that machinery or
run two UIs off the same CampaignManager signals at once. Instead,
confirming this wizard closes it and hands the collected state back to
MainWindow (see result_state()), which writes it into the same live
Campaign-page widgets the fast workflow uses and calls the exact same
start path (_on_start_requested) -- so Sending/Results are the existing
Campaign/Results pages, identical to what the fast workflow already shows.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from telethon.tl.types import TypeMessageEntity

from app.config.settings import MAX_ALLOWED_DELAY_SECONDS, MIN_ALLOWED_DELAY_SECONDS, SettingsValidationError
from app.database.repositories import SettingsRepository
from app.i18n import tr
from app.telegram.template import expand_name_placeholder
from app.ui.attachments_widget import AttachmentsWidget
from app.ui.dialogs import show_error
from app.ui.message_editor_dialog import MessageEditorDialog
from app.ui.message_preview import MessagePreviewWidget
from app.ui.recipient_widget import RecipientWidget
from app.ui import icons, theme
from app.ui.dialog_frame import build_dialog_frame
from app.ui.layouts import FlowLayout
from app.ui.theme import SPACE_SM, SPACE_XS, WIZARD_HEIGHT, WIZARD_WIDTH

_STEP_TITLE_KEYS = [
    "campaign_wizard.step.recipients",
    "campaign_wizard.step.message",
    "campaign_wizard.step.attachments",
    "campaign_wizard.step.sending_options",
    "campaign_wizard.step.preview",
    "campaign_wizard.step.confirmation",
]
_STEP_COUNT = len(_STEP_TITLE_KEYS)
(
    _STEP_RECIPIENTS,
    _STEP_MESSAGE,
    _STEP_ATTACHMENTS,
    _STEP_SENDING_OPTIONS,
    _STEP_PREVIEW,
    _STEP_CONFIRMATION,
) = range(_STEP_COUNT)


@dataclass
class WizardResult:
    recipients_text: str
    message_text: str
    message_entities: List[TypeMessageEntity]
    attachment_paths: List[Path]


class CampaignWizardDialog(QDialog):
    def __init__(self, settings_repository: SettingsRepository, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._settings_repository = settings_repository
        self._message_text: str = ""
        self._message_entities: List[TypeMessageEntity] = []

        self.setWindowTitle(tr("campaign_wizard.title"))
        self.resize(WIZARD_WIDTH, WIZARD_HEIGHT)

        frame = build_dialog_frame(self)
        root = frame.content

        # Step indicator: one bar + caption per step; done and current
        # steps carry the accent, the current caption is emphasised.
        steps_row = QHBoxLayout()
        steps_row.setSpacing(SPACE_SM)
        self._step_bars: List[QFrame] = []
        self._step_captions: List[QLabel] = []
        for key in _STEP_TITLE_KEYS:
            cell = QVBoxLayout()
            cell.setSpacing(SPACE_XS)
            bar = QFrame(self)
            bar.setObjectName("stepBar")
            caption = QLabel(tr(key), self)
            caption.setObjectName("stepIndicator")
            cell.addWidget(bar)
            cell.addWidget(caption)
            steps_row.addLayout(cell, 1)
            self._step_bars.append(bar)
            self._step_captions.append(caption)
        root.addLayout(steps_row)

        self._step_label = QLabel(self)
        self._step_label.setObjectName("dialogTitle")
        root.addWidget(self._step_label)

        # Same "From my chats…" button as the Campaign page; MainWindow
        # wires it to the same picker and loading path.
        self._recipient_widget = RecipientWidget(self, show_chat_picker=True)
        self._recipient_widget.recipients_changed.connect(self._update_nav_state)
        self._attachments_widget = AttachmentsWidget(self)
        self._preview_widget = MessagePreviewWidget(self)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_recipients_page())
        self._stack.addWidget(self._build_message_page())
        self._stack.addWidget(self._build_attachments_page())
        self._stack.addWidget(self._build_sending_options_page())
        self._stack.addWidget(self._build_preview_page())
        self._stack.addWidget(self._build_confirmation_page())
        root.addWidget(self._stack, 1)

        self._cancel_button = QPushButton(tr("campaign_wizard.cancel_button"), self)
        self._cancel_button.setProperty("variant", "ghost")
        self._cancel_button.clicked.connect(self.reject)
        frame.footer_left.addWidget(self._cancel_button)
        self._back_button = frame.add_button(QPushButton(tr("campaign_wizard.back_button"), self))
        self._back_button.setIcon(icons.themed("back"))
        self._back_button.clicked.connect(self._on_back_clicked)
        self._next_button = frame.add_button(QPushButton(tr("campaign_wizard.next_button"), self), "primary")
        self._next_button.clicked.connect(self._on_next_clicked)

        self._goto_step(_STEP_RECIPIENTS)

    # ---- page builders -----------------------------------------------------

    def _build_recipients_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        hint = QLabel(tr("campaign_wizard.recipients.hint"), page)
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self._recipient_widget, 1)
        return page

    def _build_message_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        hint = QLabel(tr("campaign_wizard.message.hint"), page)
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._message_summary_label = QLabel(page)
        self._message_summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self._message_summary_label.setWordWrap(True)
        self._message_summary_label.setObjectName("summaryLabel")
        layout.addWidget(self._message_summary_label)
        open_button = QPushButton(tr("campaign_wizard.message.open_editor_button"), page)
        open_button.clicked.connect(self._on_open_editor_clicked)
        self._message_actions = FlowLayout(spacing=SPACE_SM)
        self._message_actions.addWidget(open_button)
        layout.addLayout(self._message_actions)
        layout.addStretch(1)
        return page

    def add_message_action(self, widget: QWidget) -> None:
        """Another control next to "Open editor" (the window's Templates menu)."""
        self._message_actions.addWidget(widget)

    def message(self):
        """(text, formatting entities) of the wizard's own message."""
        return self._message_text, list(self._message_entities)

    def set_message(self, text: str, entities) -> None:
        self._message_text = text
        self._message_entities = list(entities)
        self._update_message_summary()

    def interval(self):
        """(min, max) seconds currently on the sending-options step."""
        return self._min_spin.value(), self._max_spin.value()

    def set_interval(self, min_seconds: int, max_seconds: int) -> None:
        """Only the step's boxes: saved to settings when the step is left,
        like anything typed there, so cancelling the wizard changes nothing."""
        self._min_spin.setValue(min_seconds)
        self._max_spin.setValue(max_seconds)

    @property
    def attachments_widget(self) -> AttachmentsWidget:
        return self._attachments_widget

    def _build_attachments_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._attachments_widget, 1)
        return page

    def _build_sending_options_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        hint = QLabel(tr("campaign_wizard.sending_options.hint"), page)
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        interval_row = QHBoxLayout()
        interval_row.setSpacing(SPACE_SM)
        settings = self._settings_repository.load_app_settings()
        self._min_spin = QSpinBox(page)
        self._min_spin.setRange(MIN_ALLOWED_DELAY_SECONDS, MAX_ALLOWED_DELAY_SECONDS)
        self._min_spin.setValue(settings.min_delay_seconds)
        self._max_spin = QSpinBox(page)
        self._max_spin.setRange(MIN_ALLOWED_DELAY_SECONDS, MAX_ALLOWED_DELAY_SECONDS)
        self._max_spin.setValue(settings.max_delay_seconds)
        interval_row.addWidget(self._min_spin)
        interval_row.addWidget(QLabel(tr("main_window.settings.interval_dash"), page))
        interval_row.addWidget(self._max_spin)
        interval_row.addStretch(1)
        layout.addLayout(interval_row)
        layout.addStretch(1)
        return page

    def _build_preview_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        layout.addWidget(self._preview_widget)

        preview_name_row = QHBoxLayout()
        preview_name_row.addWidget(QLabel(tr("main_window.campaign_page.preview_name_label"), page))
        self._preview_name_edit = QLineEdit(page)
        self._preview_name_edit.setText(tr("main_window.campaign_page.preview_name_default"))
        self._preview_name_edit.textChanged.connect(self._update_preview)
        preview_name_row.addWidget(self._preview_name_edit)
        preview_name_row.addStretch(1)
        layout.addLayout(preview_name_row)
        layout.addStretch(1)
        return page

    def _build_confirmation_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self._confirmation_label = QLabel(page)
        self._confirmation_label.setWordWrap(True)
        self._confirmation_label.setObjectName("summaryLabel")
        layout.addWidget(self._confirmation_label)
        layout.addStretch(1)
        return page

    # ---- navigation ----------------------------------------------------------

    def _goto_step(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for step, (bar, caption) in enumerate(zip(self._step_bars, self._step_captions)):
            theme.set_status(bar, "info" if step <= index else "")
            theme.set_status(caption, "info" if step == index else "")
        self._step_label.setText(
            tr("campaign_wizard.step_label", current=index + 1, total=_STEP_COUNT, title=tr(_STEP_TITLE_KEYS[index]))
        )
        self._back_button.setEnabled(index > 0)
        is_last = index == _STEP_CONFIRMATION
        self._next_button.setText(tr("campaign_wizard.start_button") if is_last else tr("campaign_wizard.next_button"))
        if index == _STEP_MESSAGE:
            self._update_message_summary()
        elif index == _STEP_PREVIEW:
            self._update_preview()
        elif index == _STEP_CONFIRMATION:
            self._update_confirmation()
        self._update_nav_state()

    def _update_nav_state(self, *_args) -> None:
        if self._stack.currentIndex() == _STEP_RECIPIENTS:
            self._next_button.setEnabled(bool(self._recipient_widget.valid_recipients()))
        else:
            self._next_button.setEnabled(True)

    def _on_back_clicked(self) -> None:
        index = self._stack.currentIndex()
        if index > 0:
            self._goto_step(index - 1)

    def _on_next_clicked(self) -> None:
        index = self._stack.currentIndex()
        if index == _STEP_SENDING_OPTIONS and not self._save_sending_options():
            return
        if index == _STEP_CONFIRMATION:
            self.accept()
            return
        self._goto_step(index + 1)

    # ---- step behavior ---------------------------------------------------------

    def _on_open_editor_clicked(self) -> None:
        dialog = MessageEditorDialog(self._message_text, self._message_entities, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._message_text, self._message_entities = dialog.result_content()
            self._update_message_summary()

    def _update_message_summary(self) -> None:
        if self._message_text.strip():
            snippet = self._message_text if len(self._message_text) <= 120 else self._message_text[:117] + "..."
            self._message_summary_label.setText(snippet)
        else:
            self._message_summary_label.setText(tr("campaign_wizard.message.empty"))

    def _save_sending_options(self) -> bool:
        settings = self._settings_repository.load_app_settings()
        settings.min_delay_seconds = self._min_spin.value()
        settings.max_delay_seconds = self._max_spin.value()
        try:
            self._settings_repository.save_app_settings(settings)
        except SettingsValidationError as exc:
            show_error(self, tr("main_window.dialogs.interval_title"), str(exc))
            return False
        return True

    def _update_preview(self, *_args) -> None:
        attachment_names = [a.file_name for a in self._attachments_widget.get_attachments()]
        # Same expand_name_placeholder() the real send path and the
        # Campaign page's inline preview both call -- never a second,
        # wizard-only formatting implementation.
        preview_text, preview_entities = expand_name_placeholder(
            self._message_text, self._message_entities, self._preview_name_edit.text()
        )
        self._preview_widget.update_preview(preview_text, preview_entities, attachment_names)

    def _update_confirmation(self) -> None:
        self._confirmation_label.setText(
            tr(
                "campaign_wizard.confirmation.summary",
                recipients=len(self._recipient_widget.valid_recipients()),
                attachments=len(self._attachments_widget.get_attachments()),
                min=self._min_spin.value(),
                max=self._max_spin.value(),
            )
        )

    # ---- result ----------------------------------------------------------------

    @property
    def recipient_widget(self) -> RecipientWidget:
        return self._recipient_widget

    def result_state(self) -> WizardResult:
        return WizardResult(
            recipients_text=self._recipient_widget.get_text(),
            message_text=self._message_text,
            message_entities=self._message_entities,
            attachment_paths=[a.path for a in self._attachments_widget.get_attachments()],
        )
