"""First-run welcome dialog (ROADMAP v2.0 Onboarding).

Shown once, the first time the app has no persisted
AppSettings.onboarding_completed -- explains the basic workflow and
offers three ways forward: connect a real account (opens the existing
LoginDialog), explore safely via Demo Mode (ROADMAP v2.0 Demo Mode,
app.telegram.demo_client), or skip straight to the normal empty-state
app. A single, simple page -- not a multi-step wizard like
CampaignWizard, since this dialog holds no workflow logic of its own,
only an explanation and a choice.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.i18n import tr

# Read by the caller after exec() to see which button closed the dialog.
ACTION_GET_STARTED = "get_started"
ACTION_TRY_DEMO = "try_demo"
ACTION_SKIP = "skip"

_WORKFLOW_STEP_KEYS = (
    "onboarding_dialog.step_account",
    "onboarding_dialog.step_recipients",
    "onboarding_dialog.step_message",
    "onboarding_dialog.step_attachments",
    "onboarding_dialog.step_preview",
    "onboarding_dialog.step_start",
)


class OnboardingDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.action: str = ACTION_SKIP  # closing via the window's own X counts as skip
        self.setWindowTitle(tr("onboarding_dialog.title"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        title = QLabel(tr("onboarding_dialog.welcome_title"), self)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel(tr("onboarding_dialog.welcome_body"), self)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        steps_title = QLabel(tr("onboarding_dialog.steps_title"), self)
        steps_title.setObjectName("settingsSectionTitle")
        layout.addWidget(steps_title)

        for index, key in enumerate(_WORKFLOW_STEP_KEYS, start=1):
            step_label = QLabel(f"{index}. {tr(key)}", self)
            layout.addWidget(step_label)

        demo_note = QLabel(tr("onboarding_dialog.demo_note"), self)
        demo_note.setObjectName("helperText")
        demo_note.setWordWrap(True)
        layout.addWidget(demo_note)

        buttons = QHBoxLayout()
        self._skip_button = QPushButton(tr("onboarding_dialog.skip_button"), self)
        self._skip_button.setObjectName("ghostButton")
        self._skip_button.clicked.connect(self._on_skip_clicked)
        buttons.addWidget(self._skip_button)
        buttons.addStretch(1)

        self._demo_button = QPushButton(tr("onboarding_dialog.try_demo_button"), self)
        self._demo_button.clicked.connect(self._on_try_demo_clicked)
        buttons.addWidget(self._demo_button)

        self._get_started_button = QPushButton(tr("onboarding_dialog.get_started_button"), self)
        self._get_started_button.setObjectName("primaryButton")
        self._get_started_button.clicked.connect(self._on_get_started_clicked)
        buttons.addWidget(self._get_started_button)

        layout.addLayout(buttons)

    def _on_get_started_clicked(self) -> None:
        self.action = ACTION_GET_STARTED
        self.accept()

    def _on_try_demo_clicked(self) -> None:
        self.action = ACTION_TRY_DEMO
        self.accept()

    def _on_skip_clicked(self) -> None:
        self.action = ACTION_SKIP
        self.accept()
