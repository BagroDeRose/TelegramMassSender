"""Main application window: an application shell (sidebar navigation +
collapsible journal panel + stacked pages) wiring every layer together
into the account -> recipients -> message -> attachments -> start ->
progress flow (spec item 68). Pages: Campaign (the primary flow),
Accounts, Results, Settings.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from telethon.tl.types import TypeMessageEntity

from app.campaign.campaign_manager import CampaignManager, ProgressSnapshot
from app.campaign.campaign_state import CampaignStatus
from app.campaign.rate_limiter import RateLimiter
from app.campaign.report import suggest_report_filename, write_csv_report
from app.campaign.report_library import ReportFileMissingError
from app.campaign.send_queue import SendItemStatus
from app.campaign import presets
from app.campaign.presets import PresetError
from app.recipients import groups
from app.recipients.groups import RecipientGroupError
from app.campaign import report_library
from app.config.paths import get_reports_dir
from app.config.settings import (
    MAX_ALLOWED_DELAY_SECONDS,
    MIN_ALLOWED_DELAY_SECONDS,
    AppSettings,
    SettingsValidationError,
)
from app.database.database import Database
from app.database.models import Preset, RecipientGroup, SavedReport
from app.database.repositories import PresetRepository, RecipientGroupRepository, SavedReportRepository
from app.i18n import LANGUAGE_LABELS, VALID_LANGUAGES, get_language, set_language, tr
from app.logging.logger import get_logger
from app.telegram.account_manager import Account
from app.telegram.exceptions import AccountSwitchBlockedError
from app.telegram.service import TelegramService
from app.telegram.template import expand_name_placeholder
from app.ui import theme
from app.ui.account_widget import AccountWidget
from app.ui.attachments_widget import AttachmentsWidget
from app.ui.campaign_controls import CampaignControlsWidget, format_duration
from app.ui.campaign_wizard import CampaignWizardDialog
from app.ui.dialogs import (
    confirm_delete_account,
    confirm_delete_group,
    confirm_delete_preset,
    confirm_exit_during_campaign,
    confirm_reset_settings,
    confirm_start_campaign,
    show_error,
    show_info,
)
from app.ui.empty_state import build_empty_state, retranslate_empty_state
from app.ui.journal_widget import JournalWidget
from app.ui.login_dialog import LoginDialog
from app.ui.message_editor_dialog import MessageEditorDialog
from app.ui.message_preview import MessagePreviewWidget
from app.ui.recipient_widget import RecipientWidget
from app.ui.sidebar import Sidebar
from app.ui.stat_card import StatCard
from app.ui.theme import SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XS, SPACE_XXL

WINDOW_TITLE = "Telegram Mass Sender"
_MIN_WINDOW_SIZE = (1040, 760)

_PAGE_CAMPAIGN, _PAGE_ACCOUNTS, _PAGE_RESULTS, _PAGE_SETTINGS = range(4)

# Results page recipient-list filter values (v1.7) -- _RESULTS_FILTER_FAILED
# is the default, preserving the exact "failed recipients only" behavior
# Retry (v1.6) originally shipped with.
_RESULTS_FILTER_ALL = "all"
_RESULTS_FILTER_SENT = "sent"
_RESULTS_FILTER_FAILED = "failed"
_RESULTS_FILTER_SKIPPED = "skipped"
_RESULTS_FILTER_STATUS = {
    _RESULTS_FILTER_SENT: SendItemStatus.SENT,
    _RESULTS_FILTER_FAILED: SendItemStatus.FAILED,
    _RESULTS_FILTER_SKIPPED: SendItemStatus.SKIPPED,
}


def _format_duration(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, int(total_seconds)), 60)
    if minutes:
        return tr("main_window.duration.minutes_seconds", minutes=minutes, seconds=seconds)
    return tr("main_window.duration.seconds", seconds=seconds)


def _card(title: str, content: QWidget, count_label: Optional[QLabel] = None) -> QFrame:
    """A borderless-content card: a bold title (+ optional right-aligned
    badge) above the widget, all on one flat surface."""
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_LG)
    layout.setSpacing(SPACE_MD)

    header = QHBoxLayout()
    title_label = QLabel(title, card)
    title_label.setObjectName("cardTitle")
    header.addWidget(title_label)
    header.addStretch(1)
    if count_label is not None:
        header.addWidget(count_label)
    layout.addLayout(header)

    layout.addWidget(content)
    return card


def _page_header(title: str, subtitle: str) -> QWidget:
    header = QWidget()
    layout = QVBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    title_label = QLabel(title, header)
    title_label.setObjectName("pageTitle")
    layout.addWidget(title_label)
    subtitle_label = QLabel(subtitle, header)
    subtitle_label.setObjectName("pageSubtitle")
    layout.addWidget(subtitle_label)
    return header


def _retranslate_page_header(header: QWidget, title: str, subtitle: str) -> None:
    title_label = header.findChild(QLabel, "pageTitle")
    if title_label is not None:
        title_label.setText(title)
    subtitle_label = header.findChild(QLabel, "pageSubtitle")
    if subtitle_label is not None:
        subtitle_label.setText(subtitle)


def _retranslate_card_title(card: QFrame, title: str) -> None:
    title_label = card.findChild(QLabel, "cardTitle")
    if title_label is not None:
        title_label.setText(title)


def _section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("settingsSectionTitle")
    return label


def _scrollable_page(content: QWidget) -> QWidget:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(content)
    return scroll


class MainWindow(QMainWindow):
    def __init__(
        self,
        close_event: Optional[asyncio.Event] = None,
        database: Optional[Database] = None,
    ) -> None:
        super().__init__()
        self._logger = get_logger()
        self._shutdown_in_progress = False
        self._current_campaign: Optional[CampaignManager] = None
        # Deliberately NOT cleared when a campaign finishes (unlike
        # _current_campaign, which still gates "is a campaign active") --
        # this is what lets the CSV report/Results page stay populated
        # after the campaign completes/stops, per app.campaign.report.
        self._report_source: Optional[CampaignManager] = None
        # (account, text, entities, attachments, recipient_names) from the
        # most recently started campaign -- what Retry relaunches against
        # a smaller recipient list. Also not cleared on finish, same
        # reasoning as _report_source.
        self._last_campaign_context: Optional[tuple] = None
        # Frozen at the moment the campaign finished -- CampaignControlsWidget.
        # elapsed_seconds() keeps growing after that point (it just reads
        # wall-clock time since start), so it can't be re-read later for
        # display (e.g. on a language switch); this is the one snapshot.
        self._last_campaign_duration_seconds: Optional[float] = None
        # Guards against a second "Использовать" click starting a new
        # switch while one is still in flight -- see _switch_account.
        self._account_switch_in_progress = False
        # Guards against a second "Начать рассылку" click launching a
        # second CampaignManager over the same recipient list while the
        # first is still connecting -- see _on_start_requested/_start_campaign.
        self._campaign_starting = False
        self._close_event = close_event

        self._database = database if database is not None else Database()
        self._service = TelegramService(self._database)
        self._saved_report_repo = SavedReportRepository(self._database)
        self._preset_repo = PresetRepository(self._database)
        self._group_repo = RecipientGroupRepository(self._database)

        # Source of truth for the message: the inline preview is read-only,
        # actual editing happens in MessageEditorDialog.
        self._message_text: str = ""
        self._message_entities: List[TypeMessageEntity] = []

        settings = self._service.settings_repository.load_app_settings()

        self.setWindowTitle(WINDOW_TITLE)
        if settings.remember_window_size and settings.window_width >= _MIN_WINDOW_SIZE[0]:
            self.resize(settings.window_width, settings.window_height)
        else:
            self.resize(1180, 860)
        self.setMinimumSize(*_MIN_WINDOW_SIZE)
        set_language(settings.language)
        self._apply_theme()
        self._build_ui()
        self._wire_signals()

        self._campaign_controls.set_interval_summary(settings.min_delay_seconds, settings.max_delay_seconds)
        self._theme_combo.blockSignals(True)
        combo_index = self._theme_combo.findData(theme.get_active_theme())
        self._theme_combo.setCurrentIndex(max(0, combo_index))
        self._theme_combo.blockSignals(False)
        self._language_combo.blockSignals(True)
        language_index = self._language_combo.findData(get_language())
        self._language_combo.setCurrentIndex(max(0, language_index))
        self._language_combo.blockSignals(False)
        self._load_settings_into_page(settings)

        self._journal.setVisible(settings.journal_visible)
        self._journal_toggle_button.setChecked(settings.journal_visible)
        page_index = settings.last_page_index if settings.remember_last_page else 0
        if not (0 <= page_index <= 3):
            page_index = 0
        self._navigate_to_page(page_index)

        if settings.remember_window_size and settings.window_maximized:
            self.showMaximized()

        self._update_message_preview()
        self._update_results_page()
        self._refresh_saved_reports()
        self._refresh_presets_combo()
        self._refresh_groups_combo()
        self.statusBar().showMessage(tr("main_window.status.ready"))

        asyncio.ensure_future(self._refresh_accounts())

    # ---- theme -----------------------------------------------------------------

    def _apply_theme(self) -> None:
        settings = self._service.settings_repository.load_app_settings()
        theme.set_active_theme(settings.theme)
        app = QApplication.instance()
        if app is None:
            return
        try:
            app.setStyleSheet(theme.stylesheet_for(settings.theme))
        except Exception:  # noqa: BLE001 - never let a theming problem crash startup
            self._logger.warning("Не удалось применить тему оформления: %s", settings.theme)

    def _on_theme_combo_changed(self, index: int) -> None:
        theme_name = self._theme_combo.itemData(index)
        if not theme_name:
            return
        settings = self._service.settings_repository.load_app_settings()
        if settings.theme == theme_name:
            return
        settings.theme = theme_name
        self._service.settings_repository.save_app_settings(settings)
        theme.set_active_theme(theme_name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet_for(theme_name))
        # QSS alone can't recolor baked icon pixmaps -- refresh those explicitly.
        self._sidebar.apply_theme()
        self._attachments_widget.apply_theme()
        self._journal.apply_theme()
        self._account_widget.apply_theme()
        self._update_message_preview()

    # ---- language ----------------------------------------------------------

    def _on_language_combo_changed(self, index: int) -> None:
        language = self._language_combo.itemData(index)
        if not language:
            return
        settings = self._service.settings_repository.load_app_settings()
        if settings.language == language:
            return
        settings.language = language
        self._service.settings_repository.save_app_settings(settings)
        set_language(language)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Re-set every already-constructed widget's text to the newly
        active language -- language switches immediately, the same way a
        theme switch already applies immediately, rather than requiring a
        restart. Mirrors _on_theme_combo_changed's own re-tint dispatch to
        child widgets, just for text instead of baked pixmap colors."""
        self.setWindowTitle(WINDOW_TITLE)  # product name -- unaffected, kept for clarity
        self._journal_toggle_button.setText(tr("main_window.journal_toggle.text"))
        self._journal_toggle_button.setToolTip(tr("main_window.journal_toggle.tooltip"))
        self._update_connection_status()

        _retranslate_page_header(
            self._campaign_page_header, tr("main_window.campaign_page.title"), tr("main_window.campaign_page.subtitle")
        )
        self._open_wizard_button.setText(tr("main_window.campaign_page.open_wizard_button"))
        _retranslate_card_title(self._recipients_card, tr("main_window.campaign_page.recipients_card"))
        self._load_group_button.setText(tr("main_window.groups.load_button"))
        self._save_group_button.setText(tr("main_window.groups.save_button"))
        self._delete_group_button.setText(tr("main_window.groups.delete_button"))
        self._refresh_groups_combo()  # re-set the placeholder item's text
        self._open_editor_button.setText(tr("main_window.campaign_page.open_editor_button"))
        self._open_editor_button.setToolTip(tr("main_window.campaign_page.open_editor_tooltip"))
        self._name_hint_label.setText(tr("main_window.campaign_page.name_placeholder_hint"))
        self._preview_name_label.setText(tr("main_window.campaign_page.preview_name_label"))
        self._preview_name_edit.setToolTip(tr("main_window.campaign_page.preview_name_tooltip"))
        # The example name's current *value* is deliberately left alone --
        # it may already be user-edited, and a language switch resetting
        # it back to the new language's default would silently discard
        # that. Only the label/tooltip text is retranslated.
        self._load_preset_button.setText(tr("main_window.presets.load_button"))
        self._save_preset_button.setText(tr("main_window.presets.save_button"))
        self._delete_preset_button.setText(tr("main_window.presets.delete_button"))
        self._refresh_presets_combo()  # re-set the placeholder item's text
        _retranslate_card_title(self._message_card, tr("main_window.campaign_page.message_card"))
        _retranslate_card_title(self._attachments_card, tr("main_window.campaign_page.attachments_card"))
        _retranslate_card_title(self._campaign_card, tr("main_window.campaign_page.campaign_card"))

        _retranslate_page_header(
            self._accounts_page_header, tr("main_window.accounts_page.title"), tr("main_window.accounts_page.subtitle")
        )

        _retranslate_page_header(
            self._results_page_header, tr("main_window.results_page.title"), tr("main_window.results_page.subtitle")
        )
        retranslate_empty_state(
            self._results_empty_label,
            tr("main_window.results_page.empty_title"),
            tr("main_window.results_page.empty_body"),
        )
        self._stat_total.set_label(tr("main_window.results_page.stat_total"))
        self._stat_success.set_label(tr("main_window.results_page.stat_successful"))
        self._stat_failed.set_label(tr("main_window.results_page.stat_failed"))
        self._stat_skipped.set_label(tr("main_window.results_page.stat_skipped"))
        self._results_export_button.setText(tr("main_window.results_page.export_csv_button"))
        self._export_failures_button.setText(tr("main_window.results_page.export_failures_button"))
        self._save_report_button.setText(tr("main_window.results_page.save_report_button"))
        self._failed_section_title.setText(tr("main_window.results_page.recipients_section").upper())
        self._results_filter_label.setText(tr("main_window.results_page.filter_label"))
        self._results_filter_combo.setItemText(0, tr("main_window.results_page.filter_all"))
        self._results_filter_combo.setItemText(1, tr("main_window.results_page.filter_sent"))
        self._results_filter_combo.setItemText(2, tr("main_window.results_page.filter_failed"))
        self._results_filter_combo.setItemText(3, tr("main_window.results_page.filter_skipped"))
        self._retry_selected_button.setText(tr("main_window.results_page.retry_selected_button"))
        self._retry_all_button.setText(tr("main_window.results_page.retry_all_button"))
        self._update_duration_label()
        self._refresh_failed_items()  # row text is baked in per-item, like saved-report cards
        self._saved_reports_section_title.setText(tr("main_window.results_page.saved_reports_section").upper())
        retranslate_empty_state(
            self._saved_reports_empty_label,
            tr("main_window.results_page.saved_reports_empty_title"),
            tr("main_window.results_page.saved_reports_empty_body"),
        )

        _retranslate_page_header(
            self._settings_page_header, tr("main_window.settings_page.title"), tr("main_window.settings_page.subtitle")
        )
        _retranslate_card_title(self._appearance_card, tr("main_window.settings.appearance_card"))
        _retranslate_card_title(self._sending_card, tr("main_window.settings.sending_card"))
        _retranslate_card_title(self._application_card, tr("main_window.settings.application_card"))
        _retranslate_card_title(self._reports_card, tr("main_window.settings.reports_card"))
        _retranslate_card_title(self._advanced_card, tr("main_window.settings.advanced_card"))
        self._theme_section_label.setText(tr("main_window.settings.theme_label"))
        self._theme_hint_label.setText(tr("main_window.settings.theme_hint"))
        self._language_section_label.setText(tr("main_window.settings.language_label"))
        self._language_hint_label.setText(tr("main_window.settings.language_hint"))
        self._interval_section_label.setText(tr("main_window.settings.interval_label"))
        self._interval_dash_label.setText(tr("main_window.settings.interval_dash"))
        self._interval_hint_label.setText(tr("main_window.settings.interval_hint"))
        self._confirm_before_start_checkbox.setText(tr("main_window.settings.confirm_before_start_checkbox"))
        self._confirm_before_start_checkbox.setToolTip(tr("main_window.settings.confirm_before_start_tooltip"))
        self._remember_window_checkbox.setText(tr("main_window.settings.remember_window_size_checkbox"))
        self._remember_page_checkbox.setText(tr("main_window.settings.remember_last_page_checkbox"))
        self._reports_dir_section_label.setText(tr("main_window.settings.reports_directory_label"))
        self._reports_dir_edit.setPlaceholderText(str(get_reports_dir()))
        self._browse_reports_button.setText(tr("main_window.settings.browse_button"))
        self._reset_reports_dir_button.setText(tr("main_window.settings.default_button"))
        self._auto_save_reports_checkbox.setText(tr("main_window.settings.auto_save_reports_checkbox"))
        self._debug_logging_checkbox.setText(tr("main_window.settings.debug_logging_checkbox"))
        self._reset_settings_button.setText(tr("main_window.settings.reset_settings_button"))

        # Combo items themselves carry no translation-key state (their
        # itemData is the stable theme/language code, not display text),
        # so they're simplest to just clear and rebuild.
        self._rebuild_theme_combo()
        self._rebuild_language_combo()

        for widget in (
            self._sidebar,
            self._campaign_controls,
            self._account_widget,
            self._recipient_widget,
            self._attachments_widget,
            self._journal,
        ):
            widget.retranslate_ui()

        self._update_message_preview()
        self._refresh_saved_reports()  # saved-report card text (buttons/tooltips/meta line) is baked in per-card

    def _rebuild_theme_combo(self) -> None:
        # setItemText rather than clear()+re-add: this can run from inside
        # the combo's own currentIndexChanged handler (a language switch
        # triggers retranslate_ui(), which reaches here), and re-adding
        # items would also require re-selecting one, redundant with the
        # combo's own already-current selection. setItemText only touches
        # display text, so it's both simpler and avoids touching the item
        # list at all while its own signal may still be dispatching.
        for i, value in enumerate(theme.VALID_THEMES):
            self._theme_combo.setItemText(i, theme.THEME_LABELS[value])

    def _rebuild_language_combo(self) -> None:
        for i, value in enumerate(VALID_LANGUAGES):
            self._language_combo.setItemText(i, LANGUAGE_LABELS[value])

    # ---- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        self._account_widget = AccountWidget(self)
        self._recipient_widget = RecipientWidget(self)
        self._message_preview = MessagePreviewWidget(self)
        self._attachments_widget = AttachmentsWidget(self)
        self._campaign_controls = CampaignControlsWidget(self)
        self._journal = JournalWidget(self)

        central = QWidget(self)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = Sidebar(self)
        root.addWidget(self._sidebar)
        root.addWidget(self._journal)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(_scrollable_page(self._build_campaign_page()))
        self._stack.addWidget(_scrollable_page(self._build_accounts_page()))
        self._stack.addWidget(_scrollable_page(self._build_results_page()))
        self._stack.addWidget(_scrollable_page(self._build_settings_page()))
        root.addWidget(self._stack, 1)

        self.setCentralWidget(central)

        self._connection_status_label = QLabel(tr("main_window.status.no_account"), self)
        self._connection_status_label.setObjectName("connectionStatusLabel")
        self.statusBar().addPermanentWidget(self._connection_status_label)

        self._journal_toggle_button = QToolButton(self)
        self._journal_toggle_button.setObjectName("toolbarButton")
        self._journal_toggle_button.setText(tr("main_window.journal_toggle.text"))
        self._journal_toggle_button.setCheckable(True)
        self._journal_toggle_button.setToolTip(tr("main_window.journal_toggle.tooltip"))
        self.statusBar().addPermanentWidget(self._journal_toggle_button)

    def _build_campaign_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SPACE_XXL, SPACE_XXL, SPACE_XXL, SPACE_XXL)
        layout.setSpacing(SPACE_LG)

        self._campaign_page_header = _page_header(
            tr("main_window.campaign_page.title"), tr("main_window.campaign_page.subtitle")
        )
        header_row = QHBoxLayout()
        header_row.addWidget(self._campaign_page_header, 1)
        # Optional entry point into the step-by-step wizard -- the cards
        # below (Recipients/Message/Attachments/Campaign) are the existing
        # fast, single-page workflow and are completely untouched by this.
        self._open_wizard_button = QPushButton(tr("main_window.campaign_page.open_wizard_button"), page)
        self._open_wizard_button.setObjectName("ghostButton")
        self._open_wizard_button.clicked.connect(self._on_open_campaign_wizard_clicked)
        header_row.addWidget(self._open_wizard_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header_row)

        recipients_section = QWidget()
        recipients_layout = QVBoxLayout(recipients_section)
        recipients_layout.setContentsMargins(0, 0, 0, 0)
        recipients_layout.setSpacing(SPACE_SM)
        recipients_layout.addWidget(self._recipient_widget)

        groups_row = QHBoxLayout()
        self._groups_combo = QComboBox(recipients_section)
        self._groups_combo.setMinimumWidth(180)
        self._load_group_button = QPushButton(tr("main_window.groups.load_button"), recipients_section)
        self._load_group_button.clicked.connect(self._on_load_group_clicked)
        self._save_group_button = QPushButton(tr("main_window.groups.save_button"), recipients_section)
        self._save_group_button.setObjectName("ghostButton")
        self._save_group_button.clicked.connect(self._on_save_group_clicked)
        self._delete_group_button = QPushButton(tr("main_window.groups.delete_button"), recipients_section)
        self._delete_group_button.setObjectName("ghostButton")
        self._delete_group_button.clicked.connect(self._on_delete_group_clicked)
        groups_row.addWidget(self._groups_combo, 1)
        groups_row.addWidget(self._load_group_button)
        groups_row.addWidget(self._save_group_button)
        groups_row.addWidget(self._delete_group_button)
        recipients_layout.addLayout(groups_row)

        self._recipient_count_label = QLabel("0", page)
        self._recipient_count_label.setObjectName("cardCount")
        self._recipients_card = _card(
            tr("main_window.campaign_page.recipients_card"), recipients_section, self._recipient_count_label
        )
        layout.addWidget(self._recipients_card)

        message_section = QWidget()
        message_layout = QVBoxLayout(message_section)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(SPACE_SM)
        message_layout.addWidget(self._message_preview)

        message_buttons = QHBoxLayout()
        self._open_editor_button = QPushButton(tr("main_window.campaign_page.open_editor_button"), message_section)
        self._open_editor_button.setToolTip(tr("main_window.campaign_page.open_editor_tooltip"))
        self._open_editor_button.clicked.connect(self._on_open_editor_clicked)
        message_buttons.addWidget(self._open_editor_button)
        message_buttons.addStretch(1)
        message_layout.addLayout(message_buttons)

        self._name_hint_label = QLabel(tr("main_window.campaign_page.name_placeholder_hint"), message_section)
        self._name_hint_label.setObjectName("helperText")
        message_layout.addWidget(self._name_hint_label)

        preview_name_row = QHBoxLayout()
        self._preview_name_label = QLabel(tr("main_window.campaign_page.preview_name_label"), message_section)
        self._preview_name_label.setObjectName("helperText")
        self._preview_name_edit = QLineEdit(message_section)
        self._preview_name_edit.setText(tr("main_window.campaign_page.preview_name_default"))
        self._preview_name_edit.setToolTip(tr("main_window.campaign_page.preview_name_tooltip"))
        self._preview_name_edit.setMaximumWidth(160)
        self._preview_name_edit.textChanged.connect(self._update_message_preview)
        preview_name_row.addWidget(self._preview_name_label)
        preview_name_row.addWidget(self._preview_name_edit)
        preview_name_row.addStretch(1)
        message_layout.addLayout(preview_name_row)

        presets_row = QHBoxLayout()
        self._presets_combo = QComboBox(message_section)
        self._presets_combo.setMinimumWidth(180)
        self._load_preset_button = QPushButton(tr("main_window.presets.load_button"), message_section)
        self._load_preset_button.clicked.connect(self._on_load_preset_clicked)
        self._save_preset_button = QPushButton(tr("main_window.presets.save_button"), message_section)
        self._save_preset_button.setObjectName("ghostButton")
        self._save_preset_button.clicked.connect(self._on_save_preset_clicked)
        self._delete_preset_button = QPushButton(tr("main_window.presets.delete_button"), message_section)
        self._delete_preset_button.setObjectName("ghostButton")
        self._delete_preset_button.clicked.connect(self._on_delete_preset_clicked)
        presets_row.addWidget(self._presets_combo, 1)
        presets_row.addWidget(self._load_preset_button)
        presets_row.addWidget(self._save_preset_button)
        presets_row.addWidget(self._delete_preset_button)
        message_layout.addLayout(presets_row)

        self._message_card = _card(tr("main_window.campaign_page.message_card"), message_section)
        layout.addWidget(self._message_card)
        self._attachments_card = _card(tr("main_window.campaign_page.attachments_card"), self._attachments_widget)
        layout.addWidget(self._attachments_card)
        self._campaign_card = _card(tr("main_window.campaign_page.campaign_card"), self._campaign_controls)
        layout.addWidget(self._campaign_card)
        layout.addStretch(1)
        return page

    def _build_accounts_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SPACE_XXL, SPACE_XXL, SPACE_XXL, SPACE_XXL)
        layout.setSpacing(SPACE_LG)
        self._accounts_page_header = _page_header(
            tr("main_window.accounts_page.title"), tr("main_window.accounts_page.subtitle")
        )
        layout.addWidget(self._accounts_page_header)
        layout.addWidget(self._account_widget)
        layout.addStretch(1)
        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SPACE_XXL, SPACE_XXL, SPACE_XXL, SPACE_XXL)
        layout.setSpacing(SPACE_LG)
        self._results_page_header = _page_header(
            tr("main_window.results_page.title"), tr("main_window.results_page.subtitle")
        )
        layout.addWidget(self._results_page_header)

        self._results_empty_label = build_empty_state(
            tr("main_window.results_page.empty_title"),
            tr("main_window.results_page.empty_body"),
            page,
        )
        layout.addWidget(self._results_empty_label)

        self._results_status_label = QLabel("", page)
        self._results_status_label.setObjectName("statusLabel")
        layout.addWidget(self._results_status_label)

        self._results_duration_label = QLabel("", page)
        self._results_duration_label.setObjectName("helperText")
        layout.addWidget(self._results_duration_label)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(SPACE_MD)
        self._stat_total = StatCard(tr("main_window.results_page.stat_total"))
        self._stat_success = StatCard(tr("main_window.results_page.stat_successful"), variant="success")
        self._stat_failed = StatCard(tr("main_window.results_page.stat_failed"), variant="error")
        self._stat_skipped = StatCard(tr("main_window.results_page.stat_skipped"), variant="warning")
        for card in (self._stat_total, self._stat_success, self._stat_failed, self._stat_skipped):
            stats_row.addWidget(card, 1)
        self._results_stats_widget = QWidget(page)
        self._results_stats_widget.setLayout(stats_row)
        layout.addWidget(self._results_stats_widget)

        self._failure_categories_label = QLabel("", page)
        self._failure_categories_label.setWordWrap(True)
        self._failure_categories_label.setObjectName("helperText")
        self._failure_categories_label.setVisible(False)
        layout.addWidget(self._failure_categories_label)

        export_row = QHBoxLayout()
        self._results_export_button = QPushButton(tr("main_window.results_page.export_csv_button"), page)
        self._results_export_button.setObjectName("primaryButton")
        self._results_export_button.setEnabled(False)
        self._results_export_button.clicked.connect(self._on_export_report_requested)
        self._export_failures_button = QPushButton(tr("main_window.results_page.export_failures_button"), page)
        self._export_failures_button.setEnabled(False)
        self._export_failures_button.clicked.connect(self._on_export_failures_clicked)
        self._save_report_button = QPushButton(tr("main_window.results_page.save_report_button"), page)
        self._save_report_button.setEnabled(False)
        self._save_report_button.clicked.connect(self._on_save_report_clicked)
        export_row.addWidget(self._results_export_button)
        export_row.addWidget(self._export_failures_button)
        export_row.addWidget(self._save_report_button)
        export_row.addStretch(1)
        layout.addLayout(export_row)

        self._failed_section_title = _section_title(tr("main_window.results_page.recipients_section"))
        self._failed_section_title.setVisible(False)
        layout.addWidget(self._failed_section_title)

        filter_row = QHBoxLayout()
        self._results_filter_label = QLabel(tr("main_window.results_page.filter_label"), page)
        filter_row.addWidget(self._results_filter_label)
        self._results_filter_combo = QComboBox(page)
        self._results_filter_combo.addItem(tr("main_window.results_page.filter_all"), _RESULTS_FILTER_ALL)
        self._results_filter_combo.addItem(tr("main_window.results_page.filter_sent"), _RESULTS_FILTER_SENT)
        self._results_filter_combo.addItem(tr("main_window.results_page.filter_failed"), _RESULTS_FILTER_FAILED)
        self._results_filter_combo.addItem(tr("main_window.results_page.filter_skipped"), _RESULTS_FILTER_SKIPPED)
        self._results_filter_combo.setCurrentIndex(2)  # Failed -- the original Retry (v1.6) default
        self._results_filter_combo.currentIndexChanged.connect(lambda _i: self._refresh_failed_items())
        filter_row.addWidget(self._results_filter_combo)
        filter_row.addStretch(1)
        self._results_filter_row_widget = QWidget(page)
        self._results_filter_row_widget.setLayout(filter_row)
        self._results_filter_row_widget.setVisible(False)
        layout.addWidget(self._results_filter_row_widget)

        self._failed_items_list = QListWidget(page)
        self._failed_items_list.setMaximumHeight(180)
        self._failed_items_list.setVisible(False)
        self._failed_items_list.itemChanged.connect(self._on_failed_item_check_changed)
        layout.addWidget(self._failed_items_list)

        retry_row = QHBoxLayout()
        self._retry_selected_button = QPushButton(tr("main_window.results_page.retry_selected_button"), page)
        self._retry_selected_button.setEnabled(False)
        self._retry_selected_button.clicked.connect(self._on_retry_selected_clicked)
        self._retry_all_button = QPushButton(tr("main_window.results_page.retry_all_button"), page)
        self._retry_all_button.setObjectName("ghostButton")
        self._retry_all_button.clicked.connect(self._on_retry_all_failures_clicked)
        retry_row.addWidget(self._retry_selected_button)
        retry_row.addWidget(self._retry_all_button)
        retry_row.addStretch(1)
        self._retry_row_widget = QWidget(page)
        self._retry_row_widget.setLayout(retry_row)
        self._retry_row_widget.setVisible(False)
        layout.addWidget(self._retry_row_widget)

        self._saved_reports_section_title = _section_title(tr("main_window.results_page.saved_reports_section"))
        layout.addWidget(self._saved_reports_section_title)
        self._saved_reports_empty_label = build_empty_state(
            tr("main_window.results_page.saved_reports_empty_title"),
            tr("main_window.results_page.saved_reports_empty_body"),
            page,
        )
        layout.addWidget(self._saved_reports_empty_label)

        self._saved_reports_layout = QVBoxLayout()
        self._saved_reports_layout.setSpacing(SPACE_SM)
        layout.addLayout(self._saved_reports_layout)
        self._saved_report_cards: List[QFrame] = []

        layout.addStretch(1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SPACE_XXL, SPACE_XXL, SPACE_XXL, SPACE_XXL)
        layout.setSpacing(SPACE_LG)
        self._settings_page_header = _page_header(tr("main_window.settings_page.title"), tr("main_window.settings_page.subtitle"))
        layout.addWidget(self._settings_page_header)

        self._appearance_card = _card(tr("main_window.settings.appearance_card"), self._build_appearance_settings())
        layout.addWidget(self._appearance_card)
        self._sending_card = _card(tr("main_window.settings.sending_card"), self._build_sending_settings())
        layout.addWidget(self._sending_card)
        self._application_card = _card(tr("main_window.settings.application_card"), self._build_application_settings())
        layout.addWidget(self._application_card)
        self._reports_card = _card(tr("main_window.settings.reports_card"), self._build_reports_settings())
        layout.addWidget(self._reports_card)
        self._advanced_card = _card(tr("main_window.settings.advanced_card"), self._build_advanced_settings())
        layout.addWidget(self._advanced_card)
        layout.addStretch(1)
        return page

    def _build_appearance_settings(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        self._theme_section_label = QLabel(tr("main_window.settings.theme_label"), widget)
        layout.addWidget(self._theme_section_label)
        self._theme_combo = QComboBox(widget)
        for value in theme.VALID_THEMES:
            self._theme_combo.addItem(theme.THEME_LABELS[value], value)
        self._theme_combo.setMaximumWidth(220)
        layout.addWidget(self._theme_combo)
        self._theme_hint_label = QLabel(tr("main_window.settings.theme_hint"), widget)
        self._theme_hint_label.setObjectName("helperText")
        layout.addWidget(self._theme_hint_label)

        self._language_section_label = QLabel(tr("main_window.settings.language_label"), widget)
        layout.addWidget(self._language_section_label)
        self._language_combo = QComboBox(widget)
        for value in VALID_LANGUAGES:
            self._language_combo.addItem(LANGUAGE_LABELS[value], value)
        self._language_combo.setMaximumWidth(220)
        layout.addWidget(self._language_combo)
        self._language_hint_label = QLabel(tr("main_window.settings.language_hint"), widget)
        self._language_hint_label.setObjectName("helperText")
        layout.addWidget(self._language_hint_label)
        return widget

    def _build_sending_settings(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        self._interval_section_label = QLabel(tr("main_window.settings.interval_label"), widget)
        layout.addWidget(self._interval_section_label)
        interval_row = QHBoxLayout()
        interval_row.setSpacing(SPACE_SM)
        self._settings_min_spin = QSpinBox(widget)
        self._settings_min_spin.setRange(MIN_ALLOWED_DELAY_SECONDS, MAX_ALLOWED_DELAY_SECONDS)
        self._settings_max_spin = QSpinBox(widget)
        self._settings_max_spin.setRange(MIN_ALLOWED_DELAY_SECONDS, MAX_ALLOWED_DELAY_SECONDS)
        interval_row.addWidget(self._settings_min_spin)
        self._interval_dash_label = QLabel(tr("main_window.settings.interval_dash"), widget)
        interval_row.addWidget(self._interval_dash_label)
        interval_row.addWidget(self._settings_max_spin)
        interval_row.addStretch(1)
        layout.addLayout(interval_row)
        self._interval_hint_label = QLabel(tr("main_window.settings.interval_hint"), widget)
        self._interval_hint_label.setObjectName("helperText")
        self._interval_hint_label.setWordWrap(True)
        layout.addWidget(self._interval_hint_label)
        self._settings_min_spin.editingFinished.connect(self._on_interval_settings_changed)
        self._settings_max_spin.editingFinished.connect(self._on_interval_settings_changed)

        self._confirm_before_start_checkbox = QCheckBox(tr("main_window.settings.confirm_before_start_checkbox"), widget)
        self._confirm_before_start_checkbox.setToolTip(tr("main_window.settings.confirm_before_start_tooltip"))
        self._confirm_before_start_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("confirm_before_start", checked)
        )
        layout.addWidget(self._confirm_before_start_checkbox)
        return widget

    def _build_application_settings(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        self._remember_window_checkbox = QCheckBox(tr("main_window.settings.remember_window_size_checkbox"), widget)
        self._remember_window_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("remember_window_size", checked)
        )
        layout.addWidget(self._remember_window_checkbox)

        self._remember_page_checkbox = QCheckBox(tr("main_window.settings.remember_last_page_checkbox"), widget)
        self._remember_page_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("remember_last_page", checked)
        )
        layout.addWidget(self._remember_page_checkbox)
        return widget

    def _build_reports_settings(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        self._reports_dir_section_label = QLabel(tr("main_window.settings.reports_directory_label"), widget)
        layout.addWidget(self._reports_dir_section_label)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(SPACE_SM)
        self._reports_dir_edit = QLineEdit(widget)
        self._reports_dir_edit.setPlaceholderText(str(get_reports_dir()))
        self._reports_dir_edit.setReadOnly(True)
        self._browse_reports_button = QPushButton(tr("main_window.settings.browse_button"), widget)
        self._browse_reports_button.clicked.connect(self._on_browse_reports_directory)
        self._reset_reports_dir_button = QPushButton(tr("main_window.settings.default_button"), widget)
        self._reset_reports_dir_button.setObjectName("ghostButton")
        self._reset_reports_dir_button.clicked.connect(self._on_reset_reports_directory)
        dir_row.addWidget(self._reports_dir_edit, 1)
        dir_row.addWidget(self._browse_reports_button)
        dir_row.addWidget(self._reset_reports_dir_button)
        layout.addLayout(dir_row)

        self._auto_save_reports_checkbox = QCheckBox(tr("main_window.settings.auto_save_reports_checkbox"), widget)
        self._auto_save_reports_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("auto_save_reports", checked)
        )
        layout.addWidget(self._auto_save_reports_checkbox)
        return widget

    def _build_advanced_settings(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        self._debug_logging_checkbox = QCheckBox(tr("main_window.settings.debug_logging_checkbox"), widget)
        self._debug_logging_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("debug_logging", checked)
        )
        layout.addWidget(self._debug_logging_checkbox)

        reset_row = QHBoxLayout()
        self._reset_settings_button = QPushButton(tr("main_window.settings.reset_settings_button"), widget)
        self._reset_settings_button.setObjectName("dangerButton")
        self._reset_settings_button.clicked.connect(self._on_reset_settings_clicked)
        reset_row.addWidget(self._reset_settings_button)
        reset_row.addStretch(1)
        layout.addLayout(reset_row)
        return widget

    def _wire_signals(self) -> None:
        self._sidebar.page_selected.connect(self._on_sidebar_page_selected)
        self._journal_toggle_button.clicked.connect(self._on_toggle_journal)
        self._journal.toggle_requested.connect(self._on_toggle_journal)

        self._account_widget.add_account_requested.connect(self._on_add_account_requested)
        self._account_widget.account_selected.connect(self._on_account_selected)
        self._account_widget.delete_account_requested.connect(self._on_delete_account_requested)
        self._account_widget.reconnect_requested.connect(self._on_reconnect_requested)

        self._recipient_widget.recipients_changed.connect(self._on_form_state_changed)
        self._recipient_widget.recipients_changed.connect(self._on_recipients_changed)
        self._attachments_widget.attachments_changed.connect(self._update_message_preview)

        self._campaign_controls.start_requested.connect(self._on_start_requested)
        self._campaign_controls.pause_requested.connect(self._on_pause_requested)
        self._campaign_controls.resume_requested.connect(self._on_resume_requested)
        self._campaign_controls.stop_requested.connect(self._on_stop_requested)
        self._campaign_controls.export_report_requested.connect(self._on_export_report_requested)
        self._campaign_controls.open_settings_requested.connect(lambda: self._navigate_to_page(_PAGE_SETTINGS))

        self._theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        self._language_combo.currentIndexChanged.connect(self._on_language_combo_changed)

    def _navigate_to_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._sidebar.set_current_index(index)

    def _on_sidebar_page_selected(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def _on_toggle_journal(self) -> None:
        visible = not self._journal.isVisible()
        self._journal.setVisible(visible)
        # Explicit, not relying on the status-bar button's own click-toggle
        # -- this handler also fires from the journal panel's own internal
        # collapse button, which must keep the status-bar button in sync too.
        self._journal_toggle_button.setChecked(visible)
        settings = self._service.settings_repository.load_app_settings()
        settings.journal_visible = visible
        self._service.settings_repository.save_app_settings(settings)

    # ---- settings page -----------------------------------------------------

    def _load_settings_into_page(self, settings) -> None:
        self._settings_min_spin.blockSignals(True)
        self._settings_max_spin.blockSignals(True)
        self._settings_min_spin.setValue(settings.min_delay_seconds)
        self._settings_max_spin.setValue(settings.max_delay_seconds)
        self._settings_min_spin.blockSignals(False)
        self._settings_max_spin.blockSignals(False)

        for checkbox, value in (
            (self._confirm_before_start_checkbox, settings.confirm_before_start),
            (self._remember_window_checkbox, settings.remember_window_size),
            (self._remember_page_checkbox, settings.remember_last_page),
            (self._auto_save_reports_checkbox, settings.auto_save_reports),
            (self._debug_logging_checkbox, settings.debug_logging),
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.blockSignals(False)

        self._reports_dir_edit.setText(settings.reports_directory)

    def _save_setting_field(self, field_name: str, value) -> None:
        settings = self._service.settings_repository.load_app_settings()
        setattr(settings, field_name, value)
        self._service.settings_repository.save_app_settings(settings)

    def _on_interval_settings_changed(self) -> None:
        min_delay = self._settings_min_spin.value()
        max_delay = self._settings_max_spin.value()
        settings = self._service.settings_repository.load_app_settings()
        settings.min_delay_seconds = min_delay
        settings.max_delay_seconds = max_delay
        try:
            self._service.settings_repository.save_app_settings(settings)
        except SettingsValidationError as exc:
            show_error(self, tr("main_window.dialogs.interval_title"), str(exc))
            self._settings_min_spin.setValue(settings.min_delay_seconds)
            self._settings_max_spin.setValue(settings.max_delay_seconds)
            return
        self._campaign_controls.set_interval_summary(min_delay, max_delay)

    def _on_browse_reports_directory(self) -> None:
        current = self._reports_dir_edit.text() or str(get_reports_dir())
        chosen = QFileDialog.getExistingDirectory(self, tr("main_window.dialogs.reports_directory_title"), current)
        if not chosen:
            return
        self._reports_dir_edit.setText(chosen)
        self._save_setting_field("reports_directory", chosen)

    def _on_reset_reports_directory(self) -> None:
        self._reports_dir_edit.setText("")
        self._save_setting_field("reports_directory", "")

    def _on_reset_settings_clicked(self) -> None:
        if not confirm_reset_settings(self):
            return
        defaults = AppSettings()
        # Theme and language reset are each handled via their own
        # dedicated control, not silently flipped by a general reset.
        defaults.theme = theme.get_active_theme()
        defaults.language = get_language()
        self._service.settings_repository.save_app_settings(defaults)
        self._load_settings_into_page(defaults)
        self._campaign_controls.set_interval_summary(defaults.min_delay_seconds, defaults.max_delay_seconds)
        show_info(self, tr("main_window.dialogs.settings_title"), tr("main_window.dialogs.settings_reset_message"))

    def _reports_directory(self) -> Path:
        settings = self._service.settings_repository.load_app_settings()
        if settings.reports_directory:
            return Path(settings.reports_directory)
        return get_reports_dir()

    # ---- message editor / preview --------------------------------------------

    def _on_open_editor_clicked(self) -> None:
        dialog = MessageEditorDialog(self._message_text, self._message_entities, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._message_text, self._message_entities = dialog.result_content()
            self._update_message_preview()

    def _update_message_preview(self) -> None:
        attachment_names = [a.file_name for a in self._attachments_widget.get_attachments()]
        # Uses the same expand_name_placeholder() the real campaign send
        # path calls per-recipient (app.campaign.campaign_manager) --
        # never a second, preview-only formatting/substitution
        # implementation -- so the preview is honest about what will
        # actually be sent, UTF-16 entity offsets included. The example
        # name is illustrative only: a real recipient's name isn't known
        # until Telegram resolves them at send time, so there is nothing
        # else correct to preview with.
        preview_text, preview_entities = expand_name_placeholder(
            self._message_text, self._message_entities, self._preview_name_edit.text()
        )
        self._message_preview.update_preview(preview_text, preview_entities, attachment_names)
        self._on_form_state_changed()

    # ---- message presets --------------------------------------------------

    def _refresh_presets_combo(self) -> None:
        current_id = self._presets_combo.currentData()
        self._presets_combo.blockSignals(True)
        self._presets_combo.clear()
        self._presets_combo.addItem(tr("main_window.presets.placeholder"), None)
        for preset in presets.list_presets(self._preset_repo):
            self._presets_combo.addItem(preset.name, preset.id)
        if current_id is not None:
            index = self._presets_combo.findData(current_id)
            if index >= 0:
                self._presets_combo.setCurrentIndex(index)
        self._presets_combo.blockSignals(False)

    def _selected_preset(self) -> Optional[Preset]:
        preset_id = self._presets_combo.currentData()
        if preset_id is None:
            return None
        return self._preset_repo.get_by_id(preset_id)

    def _on_save_preset_clicked(self) -> None:
        name, ok = QInputDialog.getText(self, tr("main_window.dialogs.save_preset_title"), tr("main_window.dialogs.preset_name_label"))
        if not ok or not name.strip():
            return
        settings = self._service.settings_repository.load_app_settings()
        saved = presets.save_preset(
            self._preset_repo,
            name,
            self._message_text,
            self._message_entities,
            [a.path for a in self._attachments_widget.get_attachments()],
            settings.min_delay_seconds,
            settings.max_delay_seconds,
        )
        self._refresh_presets_combo()
        index = self._presets_combo.findData(saved.id)
        if index >= 0:
            self._presets_combo.setCurrentIndex(index)
        show_info(self, tr("main_window.dialogs.save_preset_title"), tr("main_window.dialogs.preset_saved_message", name=saved.name))

    def _on_load_preset_clicked(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            show_error(self, tr("main_window.dialogs.save_preset_title"), tr("main_window.dialogs.no_preset_selected"))
            return
        try:
            loaded = presets.load_preset(preset)
        except PresetError as exc:
            show_error(self, tr("main_window.dialogs.save_preset_title"), str(exc))
            return

        self._message_text = loaded.message_text
        self._message_entities = loaded.message_entities
        self._attachments_widget.clear()
        for path in loaded.attachment_paths:
            self._attachments_widget.add_file(path)
        if loaded.min_delay_seconds is not None and loaded.max_delay_seconds is not None:
            settings = self._service.settings_repository.load_app_settings()
            settings.min_delay_seconds = loaded.min_delay_seconds
            settings.max_delay_seconds = loaded.max_delay_seconds
            try:
                self._service.settings_repository.save_app_settings(settings)
            except SettingsValidationError:
                pass  # a stale/out-of-range saved interval must not block loading the rest of the preset
            else:
                self._load_settings_into_page(settings)
                self._campaign_controls.set_interval_summary(settings.min_delay_seconds, settings.max_delay_seconds)
        self._update_message_preview()

        if loaded.missing_attachment_names:
            show_error(
                self,
                tr("main_window.dialogs.preset_missing_attachments_title"),
                tr("main_window.dialogs.preset_missing_attachments_message", names=", ".join(loaded.missing_attachment_names)),
            )

    def _on_delete_preset_clicked(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            show_error(self, tr("main_window.dialogs.save_preset_title"), tr("main_window.dialogs.no_preset_selected"))
            return
        if not confirm_delete_preset(self, preset.name):
            return
        presets.delete_preset(self._preset_repo, preset.id)
        self._refresh_presets_combo()

    # ---- recipient groups ---------------------------------------------------

    def _refresh_groups_combo(self) -> None:
        current_id = self._groups_combo.currentData()
        self._groups_combo.blockSignals(True)
        self._groups_combo.clear()
        self._groups_combo.addItem(tr("main_window.groups.placeholder"), None)
        for group in groups.list_groups(self._group_repo):
            self._groups_combo.addItem(group.name, group.id)
        if current_id is not None:
            index = self._groups_combo.findData(current_id)
            if index >= 0:
                self._groups_combo.setCurrentIndex(index)
        self._groups_combo.blockSignals(False)

    def _selected_group(self) -> Optional[RecipientGroup]:
        group_id = self._groups_combo.currentData()
        if group_id is None:
            return None
        return self._group_repo.get_by_id(group_id)

    def _on_save_group_clicked(self) -> None:
        self._recipient_widget.flush()
        name, ok = QInputDialog.getText(self, tr("main_window.dialogs.save_group_title"), tr("main_window.dialogs.group_name_label"))
        if not ok or not name.strip():
            return
        saved = groups.save_group(
            self._group_repo, name, self._recipient_widget.get_text(), self._recipient_widget.name_overrides()
        )
        self._refresh_groups_combo()
        index = self._groups_combo.findData(saved.id)
        if index >= 0:
            self._groups_combo.setCurrentIndex(index)
        show_info(self, tr("main_window.dialogs.save_group_title"), tr("main_window.dialogs.group_saved_message", name=saved.name))

    def _on_load_group_clicked(self) -> None:
        group = self._selected_group()
        if group is None:
            show_error(self, tr("main_window.dialogs.save_group_title"), tr("main_window.dialogs.no_group_selected"))
            return
        try:
            loaded = groups.load_group(group)
        except RecipientGroupError as exc:
            show_error(self, tr("main_window.dialogs.save_group_title"), str(exc))
            return
        self._recipient_widget.set_text_with_names(loaded.recipients_text, loaded.name_overrides)

    def _on_delete_group_clicked(self) -> None:
        group = self._selected_group()
        if group is None:
            show_error(self, tr("main_window.dialogs.save_group_title"), tr("main_window.dialogs.no_group_selected"))
            return
        if not confirm_delete_group(self, group.name):
            return
        groups.delete_group(self._group_repo, group.id)
        self._refresh_groups_combo()

    # ---- campaign wizard ---------------------------------------------------

    def _on_open_campaign_wizard_clicked(self) -> None:
        dialog = CampaignWizardDialog(self._service.settings_repository, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = dialog.result_state()
        # Write the wizard's collected state into the exact same live
        # widgets/fields the fast workflow uses, then reuse its own Start
        # path -- so both workflows validate and start a campaign through
        # one code path (_on_start_requested), never two.
        self._recipient_widget.set_text(result.recipients_text)
        self._message_text = result.message_text
        self._message_entities = result.message_entities
        self._attachments_widget.clear()
        for path in result.attachment_paths:
            self._attachments_widget.add_file(path)
        self._update_message_preview()
        self._navigate_to_page(_PAGE_CAMPAIGN)
        settings = self._service.settings_repository.load_app_settings()
        self._campaign_controls.set_interval_summary(settings.min_delay_seconds, settings.max_delay_seconds)
        self._load_settings_into_page(settings)
        self._on_start_requested()

    def _on_recipients_changed(self, summary) -> None:
        self._recipient_count_label.setText(str(len(summary.valid_recipients)))
        self._campaign_controls.set_recipient_count(len(summary.valid_recipients))

    # ---- account management -------------------------------------------------

    def _can_switch_accounts(self) -> bool:
        return self._current_campaign is None or not self._current_campaign.is_active

    def _ensure_switch_guard(self) -> None:
        if self._service.account_manager is not None:
            self._service.account_manager.set_switch_guard(self._can_switch_accounts)

    async def _refresh_accounts(self, select_id: Optional[int] = None) -> None:
        self._ensure_switch_guard()
        account_manager = self._service.account_manager
        if account_manager is None:
            self._account_widget.set_accounts([])
            self._on_form_state_changed()
            self._update_connection_status()
            return
        statuses = await account_manager.list_accounts_with_status()
        valid_ids = {s.account.id for s in statuses}

        # Preference order: an explicit caller override (e.g. "select the
        # account I just added/reconnected") > whatever AccountManager
        # already considers active this session (read *after* the above
        # await, so a manual switch that completed while this coroutine
        # was awaiting network calls always wins over stale data here) >
        # the persisted choice from a previous run > the first account.
        selected = select_id if select_id is not None else account_manager.active_account_id
        if selected is None or selected not in valid_ids:
            settings = self._service.settings_repository.load_app_settings()
            if settings.active_account_id and settings.active_account_id in valid_ids:
                selected = settings.active_account_id
        if (selected is None or selected not in valid_ids) and statuses:
            selected = statuses[0].account.id

        self._account_widget.set_accounts(statuses, selected)
        if selected is not None:
            try:
                account_manager.switch_active_account(selected)
            except AccountSwitchBlockedError:
                pass
            else:
                self._persist_active_account(selected)
        self._on_form_state_changed()
        self._update_connection_status()

    def _persist_active_account(self, account_id: Optional[int]) -> None:
        settings = self._service.settings_repository.load_app_settings()
        settings.active_account_id = account_id or 0
        try:
            self._service.settings_repository.save_app_settings(settings)
        except SettingsValidationError:
            pass

    def _update_connection_status(self) -> None:
        # The colored dot is a secondary cue only -- the text itself always
        # spells out "Connected"/"No account" so state is never color-only.
        tokens = theme.current_tokens()
        if self._active_account() is None:
            dot_color, text = tokens.text_muted, tr("main_window.status.no_account")
        else:
            account = self._active_account()
            label = f"@{account.username}" if account.username else account.phone
            dot_color, text = tokens.success, tr("main_window.status.connected", label=label)
        self._connection_status_label.setText(f'<span style="color:{dot_color};">●</span>&nbsp;&nbsp;{text}')

    def _on_add_account_requested(self) -> None:
        if not self._can_switch_accounts():
            show_error(self, tr("main_window.dialogs.unavailable_title"), tr("main_window.dialogs.add_account_unavailable"))
            return
        dialog = LoginDialog(self._service, self)
        result_holder: dict = {}
        dialog.account_ready.connect(lambda acc: result_holder.__setitem__("account", acc))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            account = result_holder.get("account")
            asyncio.ensure_future(self._refresh_accounts(select_id=account.id if account else None))

    def _on_account_selected(self, account_id: int) -> None:
        if self._account_switch_in_progress:
            return  # a switch is already in flight -- ignore the extra click
        # Set synchronously, before scheduling the coroutine: two clicks
        # arriving back-to-back (before the event loop ever runs
        # _switch_account) must both see this guard, not just the second
        # one to actually start executing.
        self._account_switch_in_progress = True
        asyncio.ensure_future(self._switch_account(account_id))

    async def _switch_account(self, account_id: int) -> None:
        """The single place app.telegram.account_manager's active-account
        id is changed by user action. account_manager.switch_active_account
        itself is synchronous (pure in-memory bookkeeping -- no network
        call), so the only real reason this is a coroutine is to give the
        Qt/qasync event loop a chance to paint the transitional
        "Переключение..." state before the (fast) switch completes; there
        is no blocking wait or nested event loop involved.
        """
        account_manager = self._service.account_manager
        if account_manager is None:
            return

        previous_active_id = account_manager.active_account_id
        self._account_widget.begin_switch(account_id)
        await asyncio.sleep(0)  # yield once so the transitional state actually paints

        try:
            account_manager.switch_active_account(account_id)
        except AccountSwitchBlockedError as exc:
            show_error(self, tr("main_window.dialogs.unavailable_title"), str(exc))
            self._account_widget.refresh_active_state(previous_active_id)
            self._account_switch_in_progress = False
            return
        except Exception as exc:  # noqa: BLE001 - surfaced as a friendly message, logged for detail
            self._logger.warning("Не удалось переключить аккаунт %s: %s", account_id, exc)
            show_error(
                self,
                tr("main_window.dialogs.switch_account_title"),
                tr("main_window.dialogs.switch_account_failed"),
            )
            self._account_widget.refresh_active_state(previous_active_id)
            self._account_switch_in_progress = False
            return

        self._account_widget.refresh_active_state(account_id)
        self._persist_active_account(account_id)
        self._on_form_state_changed()
        self._update_connection_status()
        self._account_switch_in_progress = False

    def _on_delete_account_requested(self, account_id: int) -> None:
        if not self._can_switch_accounts():
            show_error(self, tr("main_window.dialogs.unavailable_title"), tr("main_window.dialogs.delete_account_unavailable"))
            return
        account = self._service.account_repository.get_by_id(account_id)
        if account is None:
            return
        if not confirm_delete_account(self, account.phone):
            return
        asyncio.ensure_future(self._delete_account(account))

    async def _delete_account(self, account: Account) -> None:
        account_manager = self._service.account_manager
        if account_manager is None:
            return
        await account_manager.delete_account(account)
        await self._refresh_accounts()

    def _on_reconnect_requested(self, account_id: int) -> None:
        asyncio.ensure_future(self._refresh_accounts(select_id=account_id))

    def _active_account(self) -> Optional[Account]:
        account_manager = self._service.account_manager
        if account_manager is None or account_manager.active_account_id is None:
            return None
        return self._service.account_repository.get_by_id(account_manager.active_account_id)

    # ---- proactive Start-button state -----------------------------------------

    def _on_form_state_changed(self, *_args) -> None:
        has_account = self._active_account() is not None
        has_recipients = bool(self._recipient_widget.get_summary().valid_recipients)
        has_content = bool(self._message_text.strip()) or not self._attachments_widget.is_empty()
        self._campaign_controls.set_start_ready(has_account and has_recipients and has_content)

    # ---- campaign lifecycle ---------------------------------------------------

    def _on_start_requested(self) -> None:
        if self._campaign_starting:
            return  # a start is already in flight -- ignore the extra click
        if self._current_campaign is not None and self._current_campaign.is_active:
            show_error(self, tr("main_window.dialogs.campaign_title"), tr("main_window.start_error.already_running"))
            return

        account = self._active_account()
        if account is None:
            show_error(self, tr("main_window.dialogs.campaign_title"), tr("main_window.start_error.no_account"))
            return

        self._recipient_widget.flush()
        recipients = self._recipient_widget.valid_recipients()
        if not recipients:
            show_error(self, tr("main_window.dialogs.campaign_title"), tr("main_window.start_error.no_recipients"))
            return
        recipient_names = self._recipient_widget.name_overrides()

        text, entities = self._message_text, self._message_entities
        attachments = self._attachments_widget.get_attachments()
        missing = self._attachments_widget.missing_files()
        if missing:
            names = ", ".join(p.name for p in missing)
            show_error(self, tr("main_window.dialogs.campaign_title"), tr("main_window.start_error.missing_files", names=names))
            return
        unreadable = self._attachments_widget.unreadable_files()
        if unreadable:
            names = ", ".join(p.name for p in unreadable)
            show_error(
                self,
                tr("main_window.dialogs.campaign_title"),
                tr("main_window.start_error.unreadable_files", names=names),
            )
            return
        if not text.strip() and not attachments:
            show_error(self, tr("main_window.dialogs.campaign_title"), tr("main_window.start_error.no_content"))
            return

        settings = self._service.settings_repository.load_app_settings()
        if settings.confirm_before_start and not confirm_start_campaign(self, len(recipients)):
            return

        try:
            rate_limiter = RateLimiter(settings.min_delay_seconds, settings.max_delay_seconds)
        except SettingsValidationError as exc:
            show_error(self, tr("main_window.dialogs.interval_title"), str(exc))
            return

        # Set synchronously, before scheduling the coroutine: two clicks
        # arriving back-to-back (before the event loop ever runs
        # _start_campaign, e.g. while ensure_connected's network round-trip
        # is still pending) must both see this guard, not just the second
        # one to actually start executing -- see _switch_account for the
        # same pattern applied to account switching.
        self._campaign_starting = True
        asyncio.ensure_future(
            self._start_campaign(
                account, recipients, text, entities, attachments, rate_limiter, settings.retry_count, recipient_names
            )
        )

    async def _start_campaign(
        self, account, recipients, text, entities, attachments, rate_limiter, retry_count, recipient_names
    ) -> None:
        account_manager = self._service.account_manager
        assert account_manager is not None
        try:
            client = await account_manager.ensure_connected(account)
            if not await client.is_user_authorized():
                show_error(self, tr("main_window.dialogs.campaign_title"), tr("main_window.start_error.not_authorized"))
                self._campaign_starting = False
                return
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            show_error(self, tr("main_window.dialogs.campaign_title"), tr("main_window.start_error.connect_failed", error=exc))
            self._campaign_starting = False
            return

        campaign = CampaignManager(
            client=client,
            recipients=recipients,
            message_text=text,
            message_entities=entities,
            attachments=attachments,
            rate_limiter=rate_limiter,
            max_retries=retry_count,
            recipient_names=recipient_names,
            # No Qt parent on purpose: with parent=self, Qt's ownership
            # hierarchy would keep every past campaign alive forever as a
            # child of MainWindow. Plain Python refcounting reclaims it as
            # soon as self._current_campaign is reassigned to the next one.
            parent=None,
        )
        self._current_campaign = campaign
        self._campaign_starting = False
        self._report_source = campaign
        # What Retry (below) needs to relaunch this exact message/
        # attachments/account against a different (smaller) recipient
        # list -- deliberately not the rate limiter/retry count, which
        # are re-read fresh from current settings at retry time instead,
        # same as a normal Start.
        self._last_campaign_context = (account, text, entities, attachments, recipient_names)
        self._campaign_controls.set_report_available(True)
        self._results_export_button.setEnabled(True)
        self._save_report_button.setEnabled(True)
        self._journal.clear()
        self._account_widget.set_enabled_switching(False)

        campaign.state_changed.connect(self._on_campaign_state_changed)
        campaign.progress_changed.connect(self._campaign_controls.update_progress)
        campaign.progress_changed.connect(self._update_results_stats)
        campaign.current_item_changed.connect(self._campaign_controls.set_current_item)
        campaign.log_message.connect(self._journal.append)
        campaign.flood_wait_started.connect(self._on_flood_wait_started)
        campaign.flood_wait_tick.connect(self._on_flood_wait_tick)
        campaign.finished.connect(self._on_campaign_finished)

        campaign.start()
        self._campaign_controls.start_elapsed_timer()
        self._campaign_controls.set_running_state(True, paused=False)
        self._results_status_label.setText(tr("main_window.results.running"))
        self._update_results_page()
        self.statusBar().showMessage(tr("main_window.status.campaign_running"))

    def _on_campaign_state_changed(self, status_value: str) -> None:
        status = CampaignStatus(status_value)
        if status == CampaignStatus.RUNNING:
            self._campaign_controls.set_running_state(True, paused=False)
            self._campaign_controls.set_status_text("")
            self.statusBar().showMessage(tr("main_window.status.campaign_running"))
        elif status == CampaignStatus.PAUSED:
            self._campaign_controls.set_running_state(True, paused=True)
            self.statusBar().showMessage(tr("main_window.status.campaign_paused"))
        elif status == CampaignStatus.WAITING_FOR_FLOOD:
            self._campaign_controls.set_running_state(True, paused=True)
            self.statusBar().showMessage(tr("main_window.status.campaign_waiting_flood"))

    def _on_flood_wait_started(self, seconds: int) -> None:
        self._campaign_controls.set_status_text(
            tr("main_window.flood_wait.started", duration=_format_duration(seconds))
        )

    def _on_flood_wait_tick(self, remaining: int) -> None:
        self._campaign_controls.set_status_text(
            tr("main_window.flood_wait.tick", duration=_format_duration(remaining))
        )

    def _on_campaign_finished(self, status_value: str) -> None:
        self._campaign_controls.stop_elapsed_timer()
        self._last_campaign_duration_seconds = self._campaign_controls.elapsed_seconds()
        self._update_duration_label()
        self._campaign_controls.set_running_state(False)
        self._campaign_controls.set_status_text("")
        self._account_widget.set_enabled_switching(True)
        status = CampaignStatus(status_value)
        if status == CampaignStatus.COMPLETED:
            self.statusBar().showMessage(tr("main_window.status.campaign_completed"))
            self._results_status_label.setText(tr("main_window.results.completed"))
        elif status == CampaignStatus.STOPPED:
            self.statusBar().showMessage(tr("main_window.status.campaign_stopped"))
            self._results_status_label.setText(tr("main_window.results.stopped"))
        elif status == CampaignStatus.ERROR:
            self.statusBar().showMessage(tr("main_window.status.campaign_error"))
            self._results_status_label.setText(tr("main_window.results.error"))
            show_error(
                self,
                tr("main_window.dialogs.campaign_error_title"),
                tr("main_window.dialogs.campaign_error_message"),
            )
        self._current_campaign = None
        self._on_form_state_changed()
        self._refresh_failed_items()

        settings = self._service.settings_repository.load_app_settings()
        if settings.auto_save_reports and self._report_source is not None and self._report_source.items:
            self._auto_save_report()

    def _auto_save_report(self) -> None:
        if self._report_source is None:
            return
        snapshot = self._report_source.snapshot()
        name = tr("main_window.report.default_name", timestamp=f"{datetime.now():%Y-%m-%d %H:%M}")
        try:
            report_library.save_report(
                self._saved_report_repo,
                self._reports_directory(),
                name,
                self._report_source.items,
                snapshot.total,
                snapshot.sent,
                snapshot.failed,
                snapshot.skipped,
            )
        except OSError as exc:
            self._logger.warning("Не удалось автоматически сохранить отчёт: %s", exc)
            return
        self._refresh_saved_reports()

    def _on_pause_requested(self) -> None:
        if self._current_campaign is not None:
            self._current_campaign.pause()

    def _on_resume_requested(self) -> None:
        if self._current_campaign is not None:
            self._current_campaign.resume()

    def _on_stop_requested(self) -> None:
        if self._current_campaign is not None:
            asyncio.ensure_future(self._current_campaign.stop())

    # ---- results page -----------------------------------------------------------

    def _update_results_page(self) -> None:
        has_data = self._report_source is not None and bool(self._report_source.items)
        self._results_empty_label.setVisible(not has_data)
        self._results_stats_widget.setVisible(has_data)
        if self._report_source is not None:
            self._update_results_stats(self._report_source.snapshot())
        self._refresh_failed_items()

    def _update_results_stats(self, snapshot: ProgressSnapshot) -> None:
        self._results_empty_label.setVisible(False)
        self._results_stats_widget.setVisible(True)
        self._stat_total.set_value(snapshot.total)
        self._stat_success.set_value(snapshot.sent)
        self._stat_failed.set_value(snapshot.failed)
        self._stat_skipped.set_value(snapshot.skipped)

    # ---- retry --------------------------------------------------------------

    def _update_duration_label(self) -> None:
        if self._last_campaign_duration_seconds is not None:
            self._results_duration_label.setText(
                tr("main_window.results_page.duration_label", duration=format_duration(self._last_campaign_duration_seconds))
            )
        else:
            self._results_duration_label.setText("")

    def _refresh_failed_items(self) -> None:
        all_items = self._report_source.items if self._report_source is not None else []
        failed_items = [item for item in all_items if item.status == SendItemStatus.FAILED]

        filter_value = self._results_filter_combo.currentData()
        if filter_value == _RESULTS_FILTER_ALL:
            displayed_items = all_items
        else:
            target_status = _RESULTS_FILTER_STATUS.get(filter_value, SendItemStatus.FAILED)
            displayed_items = [item for item in all_items if item.status == target_status]

        self._failed_items_list.blockSignals(True)
        self._failed_items_list.clear()
        for item in displayed_items:
            text = item.recipient.display_label
            if item.error:
                text += f"  —  {item.error}"
            list_item = QListWidgetItem(text)
            if item.status == SendItemStatus.FAILED:
                list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                list_item.setCheckState(Qt.CheckState.Unchecked)
            else:
                list_item.setFlags(list_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._failed_items_list.addItem(list_item)
        self._failed_items_list.blockSignals(False)

        has_any = bool(all_items)
        self._failed_section_title.setVisible(has_any)
        self._results_filter_row_widget.setVisible(has_any)
        self._failed_items_list.setVisible(has_any)
        self._retry_row_widget.setVisible(bool(failed_items))
        self._retry_all_button.setEnabled(bool(failed_items))
        self._export_failures_button.setEnabled(bool(failed_items))
        self._update_retry_selected_enabled()
        self._update_failure_categories(failed_items)

    def _update_failure_categories(self, failed_items: List) -> None:
        if not failed_items:
            self._failure_categories_label.setVisible(False)
            return
        counts: Dict[str, int] = {}
        for item in failed_items:
            reason = item.error or tr("main_window.results_page.unknown_error")
            counts[reason] = counts.get(reason, 0) + 1
        parts = [f"{reason}: {count}" for reason, count in sorted(counts.items(), key=lambda kv: -kv[1])]
        self._failure_categories_label.setText(
            tr("main_window.results_page.failure_categories", categories="; ".join(parts))
        )
        self._failure_categories_label.setVisible(True)

    def _on_failed_item_check_changed(self, _item: QListWidgetItem) -> None:
        self._update_retry_selected_enabled()

    def _update_retry_selected_enabled(self) -> None:
        any_checked = any(
            self._failed_items_list.item(i).flags() & Qt.ItemFlag.ItemIsUserCheckable
            and self._failed_items_list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self._failed_items_list.count())
        )
        self._retry_selected_button.setEnabled(any_checked)

    def _on_retry_selected_clicked(self) -> None:
        recipients = [
            self._failed_items_list.item(i).data(Qt.ItemDataRole.UserRole).recipient
            for i in range(self._failed_items_list.count())
            if self._failed_items_list.item(i).flags() & Qt.ItemFlag.ItemIsUserCheckable
            and self._failed_items_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        self._retry_recipients(recipients)

    def _on_retry_all_failures_clicked(self) -> None:
        # Reads directly from _report_source rather than the (possibly
        # differently-filtered) list widget, so "retry all failures"
        # always means every actual failure regardless of what the
        # results filter above happens to be showing right now.
        if self._report_source is None:
            return
        recipients = [item.recipient for item in self._report_source.items if item.status == SendItemStatus.FAILED]
        self._retry_recipients(recipients)

    def _retry_recipients(self, recipients) -> None:
        # Reuses _start_campaign exactly like the fast workflow and the
        # Campaign Wizard both do -- one validation/start implementation,
        # never a second retry-specific code path. Only the recipient
        # list shrinks to the ones actually retried; message/attachments/
        # account are exactly what was sent the first time
        # (_last_campaign_context), never whatever is currently sitting
        # in the Campaign page's boxes.
        if not recipients or self._last_campaign_context is None or self._campaign_starting:
            return
        if self._current_campaign is not None and self._current_campaign.is_active:
            show_error(self, tr("main_window.dialogs.campaign_title"), tr("main_window.start_error.already_running"))
            return
        account, text, entities, attachments, recipient_names = self._last_campaign_context
        settings = self._service.settings_repository.load_app_settings()
        try:
            rate_limiter = RateLimiter(settings.min_delay_seconds, settings.max_delay_seconds)
        except SettingsValidationError as exc:
            show_error(self, tr("main_window.dialogs.interval_title"), str(exc))
            return
        self._campaign_starting = True
        asyncio.ensure_future(
            self._start_campaign(
                account, recipients, text, entities, attachments, rate_limiter, settings.retry_count, recipient_names
            )
        )

    def _on_save_report_clicked(self) -> None:
        if self._report_source is None or not self._report_source.items:
            return
        default_name = tr("main_window.report.default_name", timestamp=f"{datetime.now():%Y-%m-%d %H:%M}")
        name, ok = QInputDialog.getText(
            self, tr("main_window.dialogs.save_report_title"), tr("main_window.dialogs.report_name_label"), text=default_name
        )
        if not ok:
            return
        snapshot = self._report_source.snapshot()
        try:
            report_library.save_report(
                self._saved_report_repo,
                self._reports_directory(),
                name,
                self._report_source.items,
                snapshot.total,
                snapshot.sent,
                snapshot.failed,
                snapshot.skipped,
            )
        except OSError as exc:
            show_error(self, tr("main_window.dialogs.save_report_error_title"), tr("main_window.dialogs.save_report_error_message", error=exc))
            return
        self._refresh_saved_reports()
        show_info(self, tr("main_window.dialogs.report_saved_title"), tr("main_window.dialogs.report_saved_message", name=name))

    def _refresh_saved_reports(self) -> None:
        for card in self._saved_report_cards:
            self._saved_reports_layout.removeWidget(card)
            card.deleteLater()
        self._saved_report_cards = []

        reports = report_library.list_reports(self._saved_report_repo)
        self._saved_reports_empty_label.setVisible(not reports)
        for report in reports:
            card = self._build_saved_report_card(report)
            self._saved_reports_layout.addWidget(card)
            self._saved_report_cards.append(card)

    def _build_saved_report_card(self, report: SavedReport) -> QFrame:
        card = QFrame()
        card.setObjectName("reportCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(SPACE_XS)
        favorite_button = QToolButton(card)
        favorite_button.setObjectName("favoriteButton")
        favorite_button.setText(tr("main_window.results_page.report_favorite_on") if report.is_favorite else tr("main_window.results_page.report_favorite_off"))
        favorite_button.setProperty("active", "true" if report.is_favorite else "false")
        favorite_button.setToolTip(tr("main_window.results_page.report_favorite_tooltip"))
        favorite_button.clicked.connect(lambda: self._on_toggle_favorite(report))
        header.addWidget(favorite_button)
        name_label = QLabel(report.name, card)
        name_label.setObjectName("reportName")
        header.addWidget(name_label, 1)
        layout.addLayout(header)

        meta = QLabel(
            tr(
                "main_window.results_page.report_meta_line",
                total=report.total,
                successful=report.successful,
                failed=report.failed,
            ),
            card,
        )
        meta.setObjectName("reportMeta")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        date_label = QLabel(report.created_at, card)
        date_label.setObjectName("helperText")
        layout.addWidget(date_label)

        actions = QHBoxLayout()
        actions.setSpacing(SPACE_XS)
        open_button = QPushButton(tr("main_window.results_page.report_open_button"), card)
        open_button.setObjectName("ghostButton")
        open_button.clicked.connect(lambda: self._on_open_saved_report(report))
        export_button = QPushButton(tr("main_window.results_page.report_export_button"), card)
        export_button.setObjectName("ghostButton")
        export_button.clicked.connect(lambda: self._on_export_saved_report(report))
        actions.addWidget(open_button)
        actions.addWidget(export_button)

        more_button = QPushButton(tr("main_window.results_page.report_more_button"), card)
        more_button.setObjectName("ghostButton")
        more_button.setToolTip(tr("main_window.results_page.report_more_tooltip"))
        more_menu = QMenu(more_button)
        rename_action = more_menu.addAction(tr("main_window.results_page.report_rename_action"))
        rename_action.triggered.connect(lambda: self._on_rename_saved_report(report))
        delete_action = more_menu.addAction(tr("main_window.results_page.report_delete_action"))
        delete_action.triggered.connect(lambda: self._on_delete_saved_report(report))
        more_button.setMenu(more_menu)
        actions.addWidget(more_button)

        actions.addStretch(1)
        layout.addLayout(actions)

        return card

    def _on_toggle_favorite(self, report: SavedReport) -> None:
        report_library.set_favorite(self._saved_report_repo, report.id, not report.is_favorite)
        self._refresh_saved_reports()

    def _on_open_saved_report(self, report: SavedReport) -> None:
        path = Path(report.file_path)
        if not path.is_file():
            show_error(self, tr("main_window.dialogs.report_title"), tr("main_window.dialogs.report_file_missing", path=path))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_export_saved_report(self, report: SavedReport) -> None:
        default_name = Path(report.file_path).name
        path_str, _ = QFileDialog.getSaveFileName(
            self, tr("main_window.dialogs.export_report_title"), default_name, tr("main_window.dialogs.export_report_file_filter")
        )
        if not path_str:
            return
        try:
            report_library.export_report(report, Path(path_str))
        except (ReportFileMissingError, OSError) as exc:
            show_error(self, tr("main_window.dialogs.export_report_title"), str(exc))
            return
        show_info(self, tr("main_window.dialogs.export_report_title"), tr("main_window.dialogs.export_report_saved", path=path_str))

    def _on_rename_saved_report(self, report: SavedReport) -> None:
        new_name, ok = QInputDialog.getText(
            self, tr("main_window.dialogs.rename_report_title"), tr("main_window.dialogs.report_name_label"), text=report.name
        )
        if not ok:
            return
        report_library.rename_report(self._saved_report_repo, report.id, new_name)
        self._refresh_saved_reports()

    def _on_delete_saved_report(self, report: SavedReport) -> None:
        report_library.delete_report(self._saved_report_repo, report)
        self._refresh_saved_reports()

    # ---- report export (current campaign) ---------------------------------------

    def _on_export_report_requested(self) -> None:
        if self._report_source is None or not self._report_source.items:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, tr("main_window.dialogs.export_report_title"), suggest_report_filename(), tr("main_window.dialogs.export_report_file_filter")
        )
        if not path_str:
            return
        try:
            write_csv_report(self._report_source.items, Path(path_str))
        except OSError as exc:
            show_error(self, tr("main_window.dialogs.export_report_title"), tr("main_window.dialogs.export_report_write_failed", error=exc))
            return
        show_info(self, tr("main_window.dialogs.export_report_title"), tr("main_window.dialogs.export_report_saved", path=path_str))

    def _on_export_failures_clicked(self) -> None:
        if self._report_source is None:
            return
        failed = [item for item in self._report_source.items if item.status == SendItemStatus.FAILED]
        if not failed:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, tr("main_window.dialogs.export_report_title"), suggest_report_filename(), tr("main_window.dialogs.export_report_file_filter")
        )
        if not path_str:
            return
        try:
            write_csv_report(failed, Path(path_str))
        except OSError as exc:
            show_error(self, tr("main_window.dialogs.export_report_title"), tr("main_window.dialogs.export_report_write_failed", error=exc))
            return
        show_info(self, tr("main_window.dialogs.export_report_title"), tr("main_window.dialogs.export_report_saved", path=path_str))

    # ---- shutdown --------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._shutdown_in_progress:
            event.ignore()
            return
        if self._current_campaign is not None and self._current_campaign.is_active:
            if not confirm_exit_during_campaign(self):
                event.ignore()
                return
        event.ignore()
        self._shutdown_in_progress = True
        asyncio.ensure_future(self._perform_shutdown())

    def _save_window_state(self) -> None:
        settings = self._service.settings_repository.load_app_settings()
        if settings.remember_window_size:
            settings.window_maximized = self.isMaximized()
            if not self.isMaximized():
                settings.window_width = self.width()
                settings.window_height = self.height()
        if settings.remember_last_page:
            settings.last_page_index = self._stack.currentIndex()
        try:
            self._service.settings_repository.save_app_settings(settings)
        except SettingsValidationError:
            pass

    async def _perform_shutdown(self) -> None:
        self._logger.info("Начинается корректное завершение работы приложения")
        try:
            self._save_window_state()
            if self._current_campaign is not None and self._current_campaign.is_active:
                await self._current_campaign.stop()
            await self._service.shutdown()
        finally:
            self._database.close()
            self._logger.info("Приложение завершает работу")
            self.hide()
            if self._close_event is not None:
                self._close_event.set()
            app = QApplication.instance()
            if app is not None:
                app.quit()
