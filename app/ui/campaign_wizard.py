"""Optional step-by-step Campaign Wizard (ROADMAP: "Campaign Wizard") --
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
from app.ui.theme import SPACE_MD, SPACE_SM

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
        self.resize(640, 560)

        root = QVBoxLayout(self)
        root.setSpacing(SPACE_MD)

        self._step_label = QLabel(self)
        self._step_label.setObjectName("cardTitle")
        root.addWidget(self._step_label)

        self._recipient_widget = RecipientWidget(self)
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

        nav = QHBoxLayout()
        nav.setSpacing(SPACE_SM)
        self._back_button = QPushButton(tr("campaign_wizard.back_button"), self)
        self._back_button.clicked.connect(self._on_back_clicked)
        self._cancel_button = QPushButton(tr("campaign_wizard.cancel_button"), self)
        self._cancel_button.setObjectName("ghostButton")
        self._cancel_button.clicked.connect(self.reject)
        self._next_button = QPushButton(tr("campaign_wizard.next_button"), self)
        self._next_button.setObjectName("primaryButton")
        self._next_button.clicked.connect(self._on_next_clicked)
        nav.addWidget(self._back_button)
        nav.addWidget(self._cancel_button)
        nav.addStretch(1)
        nav.addWidget(self._next_button)
        root.addLayout(nav)

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
        layout.addWidget(open_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

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

    def result_state(self) -> WizardResult:
        return WizardResult(
            recipients_text=self._recipient_widget.get_text(),
            message_text=self._message_text,
            message_entities=self._message_entities,
            attachment_paths=[a.path for a in self._attachments_widget.get_attachments()],
        )
