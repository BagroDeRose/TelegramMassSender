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

from PySide6.QtCore import QEvent, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from telethon.errors import FloodWaitError
from telethon.tl.types import TypeMessageEntity

from app.campaign.campaign_manager import ERROR_CATEGORY_SLOWMODE, CampaignManager, ProgressSnapshot
from app.campaign.campaign_state import CampaignStatus
from app.campaign.rate_limiter import RateLimiter
from app.campaign.report import suggest_report_filename, write_csv_report
from app.campaign.report_library import ReportFileMissingError
from app.campaign.send_queue import SendItemStatus
from app.campaign import presets
from app.campaign.presets import PresetError
from app.recipients import groups
from app.recipients.groups import RecipientGroupError
from app.recipients.parser import RecipientKind
from app.campaign import report_library
from app.config.paths import get_reports_dir, get_resource_path
from app.config.settings import (
    MAX_ALLOWED_DELAY_SECONDS,
    MAX_LARGE_CAMPAIGN_THRESHOLD,
    MIN_ALLOWED_DELAY_SECONDS,
    MIN_LARGE_CAMPAIGN_THRESHOLD,
    AppSettings,
    SettingsValidationError,
)
from app import diagnostics
from app.diagnostic_bundle import export_diagnostic_bundle
from app.database.database import Database
from app.database.models import Preset, RecipientGroup, SavedReport
from app.database.repositories import PresetRepository, RecipientGroupRepository, SavedReportRepository
from app.i18n import LANGUAGE_LABELS, VALID_LANGUAGES, get_language, set_language, tr
from app.logging.logger import get_logger
from app.telegram.account_manager import Account, AccountStatus
from app.telegram.chat_targets import (
    CHAT_TARGET_TYPES,
    DialogCache,
    DialogCategory,
    TargetType,
    load_dialog_snapshot,
    target_type_label,
)
from app.telegram.exceptions import AccountDeletionError, AccountSwitchBlockedError
from app.security.secure_storage import SecureStorage
from app.telegram.service import TelegramService
from app.telegram.template import expand_name_placeholder
from app.ui import icons, theme
from app.ui.account_widget import AccountWidget, account_initials, display_name, status_text_and_variant
from app.ui.attachments_widget import AttachmentsWidget
from app.ui.campaign_controls import CampaignControlsWidget, format_duration
from app.ui.campaign_wizard import CampaignWizardDialog
from app.ui.chat_picker_dialog import ChatPickerDialog
from app.ui.dialog_picker_model import dialog_recipient_keys
from app.ui.dialogs import (
    confirm_delete_account,
    confirm_delete_group,
    confirm_delete_preset,
    confirm_exit_during_campaign,
    RecipientBreakdown,
    confirm_large_campaign,
    confirm_reset_settings,
    confirm_start_campaign,
    show_error,
    show_info,
)
from app.ui.empty_state import build_empty_state, empty_state_action, retranslate_empty_state
from app.ui.journal_widget import JournalWidget
from app.ui.layouts import FlowLayout, ResponsiveColumns
from app.ui.results_view import ResultsHeader, ResultsRowDelegate, SegmentedControl
from app.ui.motion import ToastHost, fade_in
from app.ui.login_dialog import LoginDialog
from app.ui.onboarding_dialog import (
    ACTION_GET_STARTED as ONBOARDING_ACTION_GET_STARTED,
    ACTION_TRY_DEMO as ONBOARDING_ACTION_TRY_DEMO,
    OnboardingDialog,
)
from app.ui.message_editor_dialog import MessageEditorDialog
from app.ui.message_preview import MessagePreviewWidget
from app.ui.recipient_widget import RecipientWidget
from app.ui.sidebar import Sidebar
from app.ui.stat_card import StatCard
from app.ui.theme import (
    CAMPAIGN_FOLD_WIDTH,
    COMBO_MIN_WIDTH,
    CONTROL_WIDTH,
    DIAGNOSTICS_MAX_HEIGHT,
    HEADER_GAP,
    LAUNCH_PANEL_WIDTH,
    PREVIEW_NAME_WIDTH,
    RESULTS_LIST_MIN_HEIGHT,
    SETTINGS_LABEL_WIDTH,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
    SPACE_XXL,
    WINDOW_DEFAULT_HEIGHT,
    WINDOW_DEFAULT_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)

WINDOW_TITLE = "Telegram Mass Sender"
_MIN_WINDOW_SIZE = (WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

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


# SendItem.error_category -> the single label the failure breakdown shows
# for every error text in that category (each item keeps its own text).
_ERROR_CATEGORY_LABEL_KEYS = {ERROR_CATEGORY_SLOWMODE: "chat_targets.reason.slowmode"}


def _chat_type_of(item) -> Optional[TargetType]:
    """The resolved group/channel type of a results item, or None for a
    user or a not-yet-resolved target."""
    try:
        target_type = TargetType(item.target_type) if item.target_type else None
    except ValueError:
        return None
    return target_type if target_type in CHAT_TARGET_TYPES else None


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
    layout.setSpacing(HEADER_GAP)
    title_label = QLabel(title, header)
    title_label.setObjectName("pageTitle")
    layout.addWidget(title_label)
    subtitle_label = QLabel(subtitle, header)
    subtitle_label.setObjectName("pageSubtitle")
    # Wraps on a narrow page instead of setting the page's minimum width.
    subtitle_label.setWordWrap(True)
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
        secure_storage: Optional[SecureStorage] = None,
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
        self._tray_icon: Optional[QSystemTrayIcon] = None
        self._restore_maximized_from_tray = False
        # Every background task this window starts is kept here until it
        # finishes, and every one of them gets its result observed in
        # _on_background_task_done. Without that, a raising task (most
        # visibly account deletion failing on a locked session file) is
        # only reported by asyncio at garbage-collection time as
        # "Task exception was never retrieved", with no handling at all.
        # Holding the reference also stops the loop from dropping a task
        # mid-flight, which asyncio explicitly documents as possible for
        # tasks nothing keeps alive.
        self._background_tasks: set = set()
        # Account operations (refresh / switch / delete / demo mode) all
        # touch the same client manager and session files, so they are run
        # one at a time. Interleaving them is what let a status refresh
        # rebuild a Telethon client -- reopening its session file -- in the
        # middle of a delete, making the delete fail with WinError 32.
        self._account_lock = asyncio.Lock()
        # Last known status per account id (from _refresh_accounts_locked),
        # so "From my chats…" is only offered for an account that is
        # actually connected and authorized.
        self._account_statuses: Dict[int, AccountStatus] = {}
        # The open "From my chats…" picker, if any (one at a time), and the
        # open Campaign Wizard, whose recipients step has the same button.
        self._chat_picker: Optional[ChatPickerDialog] = None
        self._campaign_wizard: Optional[CampaignWizardDialog] = None
        # The active account's dialogs as the picker last read them, kept
        # for this session: reopening the picker shows them at once, and a
        # campaign's dialogs warm-up starts from them. Cleared on every
        # account change and by the picker's Refresh.
        self._dialog_cache = DialogCache()

        self._database = database if database is not None else Database()
        self._service = TelegramService(self._database, secure_storage=secure_storage)
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
            self.resize(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)
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
        self._sidebar.set_collapsed(settings.sidebar_collapsed)
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
        self._refresh_diagnostics()
        self.statusBar().showMessage(tr("main_window.status.ready"))
        self._setup_system_tray()

        self._apply_tab_order()
        self._spawn(self._refresh_accounts(), "обновление списка аккаунтов")

    def campaign_tab_chain(self) -> list:
        """The keyboard order of the shell and the Campaign page: navigation
        first (left), then the page top to bottom, left column before the
        right one, ending on the primary action."""
        recipients = self._recipient_widget
        attachments = self._attachments_widget
        controls = self._campaign_controls
        return [
            self._sidebar._toggle,
            *self._sidebar._buttons,
            self._sidebar._account_block,
            self._open_wizard_button,
            recipients._text_edit,
            recipients._import_button,
            recipients._import_csv_button,
            recipients._pick_chats_button,
            recipients._clear_button,
            recipients._review_invalid_button,
            self._groups_combo,
            self._load_group_button,
            self._save_group_button,
            self._delete_group_button,
            self._open_editor_button,
            self._presets_combo,
            self._load_preset_button,
            self._save_preset_button,
            self._delete_preset_button,
            attachments._list,
            attachments._move_earlier_button,
            attachments._move_later_button,
            attachments._add_button,
            attachments._remove_selected_button,
            attachments._clear_button,
            self._preview_name_edit,
            controls._change_interval_button,
            controls._start_button,
            controls._pause_button,
            controls._stop_button,
            controls._flood_continue_button,
            controls._export_report_button,
        ]

    def _apply_tab_order(self) -> None:
        chain = self.campaign_tab_chain()
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)
        # Containers and the read-only preview aren't stops on the way.
        for scroll in self.findChildren(QScrollArea):
            scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._message_preview._browser.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # ---- theme -----------------------------------------------------------------

    def _apply_theme(self) -> None:
        settings = self._service.settings_repository.load_app_settings()
        try:
            theme.apply_theme(QApplication.instance(), settings.theme)
        except Exception:  # noqa: BLE001 - never let a theming problem crash startup
            theme.set_active_theme(settings.theme)
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
        # Palette, stylesheet (once), title bars of every open window, and
        # theme_changed for whatever paints colours itself.
        theme.apply_theme(QApplication.instance(), theme_name)
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
        _retranslate_card_title(self._preview_card, tr("main_window.campaign_page.preview_card"))
        self._groups_label.setText(tr("main_window.groups.label"))
        self._presets_label.setText(tr("main_window.presets.label"))

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
            tr("main_window.results_page.empty_action"),
        )
        self._failure_categories_title.setText(tr("main_window.results_page.failure_reasons_title"))
        self._results_header.retranslate_ui()
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
        _retranslate_card_title(self._diagnostics_card, tr("main_window.settings.diagnostics_card"))
        self._copy_diagnostics_button.setText(tr("main_window.settings.copy_diagnostics_button"))
        self._export_diagnostic_bundle_button.setText(tr("main_window.settings.export_diagnostic_bundle_button"))
        self._refresh_diagnostics_button.setText(tr("main_window.settings.refresh_diagnostics_button"))
        self._refresh_diagnostics()
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
        self._reset_hint_label.setText(tr("main_window.settings.reset_hint"))
        self._confirm_hint_label.setText(tr("main_window.settings.confirm_before_start_tooltip"))
        self._large_campaign_section_label.setText(tr("main_window.settings.large_campaign_label"))
        self._large_campaign_spin.setPrefix(tr("main_window.settings.large_campaign_prefix"))
        self._large_campaign_spin.setSuffix(tr("main_window.settings.large_campaign_suffix"))
        self._large_campaign_hint_label.setText(tr("main_window.settings.large_campaign_hint"))

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
        self._recipient_widget = RecipientWidget(self, show_chat_picker=True)
        self._message_preview = MessagePreviewWidget(self)
        self._attachments_widget = AttachmentsWidget(self)
        self._campaign_controls = CampaignControlsWidget(self)
        self._journal = JournalWidget(self)

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Demo Mode banner (ROADMAP v2.0): a persistent, unmissable strip
        # above the whole app shell -- not just a status-bar label, which
        # would be too easy to overlook for something this important
        # ("clearly indicate Demo Mode"). Hidden by default; shown only
        # while self._service.is_demo_mode is True.
        self._demo_banner = QFrame(central)
        self._demo_banner.setObjectName("demoBanner")
        self._demo_banner.setVisible(False)
        banner_layout = QHBoxLayout(self._demo_banner)
        banner_layout.setContentsMargins(SPACE_LG, SPACE_SM, SPACE_LG, SPACE_SM)
        self._demo_banner_label = QLabel(tr("main_window.demo_banner.text"), self._demo_banner)
        self._demo_banner_label.setObjectName("demoBannerLabel")
        banner_layout.addWidget(self._demo_banner_label, 1)
        self._demo_exit_button = QPushButton(tr("main_window.demo_banner.exit_button"), self._demo_banner)
        self._demo_exit_button.clicked.connect(self._on_exit_demo_mode_clicked)
        banner_layout.addWidget(self._demo_exit_button)
        outer.addWidget(self._demo_banner)

        row = QWidget(central)
        root = QHBoxLayout(row)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = Sidebar(self)
        root.addWidget(self._sidebar)

        self._stack = QStackedWidget(self)
        self._stack.setObjectName("pageStack")
        self._stack.addWidget(self._build_campaign_page())
        self._stack.addWidget(_scrollable_page(self._build_accounts_page()))
        self._stack.addWidget(_scrollable_page(self._build_results_page()))
        self._stack.addWidget(_scrollable_page(self._build_settings_page()))
        root.addWidget(self._stack, 1)
        # The journal is a side panel on the right, next to the page it
        # describes -- not wedged between the navigation and the page.
        root.addWidget(self._journal)
        outer.addWidget(row, 1)

        self.setCentralWidget(central)
        self._toasts = ToastHost(central)

        status_bar = self.statusBar()
        status_bar.setSizeGripEnabled(False)
        self._connection_dot = QLabel(self)
        self._connection_dot.setObjectName("statusDot")
        status_bar.addPermanentWidget(self._connection_dot)
        self._connection_status_label = QLabel(tr("main_window.status.no_account"), self)
        self._connection_status_label.setObjectName("connectionStatusLabel")
        status_bar.addPermanentWidget(self._connection_status_label)

        self._journal_toggle_button = QToolButton(self)
        self._journal_toggle_button.setObjectName("toolbarButton")
        self._journal_toggle_button.setText(tr("main_window.journal_toggle.text"))
        self._journal_toggle_button.setIcon(icons.themed("journal", "text_secondary", checked_role="accent"))
        self._journal_toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._journal_toggle_button.setCheckable(True)
        self._journal_toggle_button.setToolTip(tr("main_window.journal_toggle.tooltip"))
        status_bar.addPermanentWidget(self._journal_toggle_button)

    def _build_campaign_page(self) -> QWidget:
        """Two columns: Recipients -> Message -> Attachments scroll on the
        left; the chat-like preview and the launch/progress panel stay
        pinned on the right. Below TWO_COLUMN_MIN_WIDTH they fold into one
        column (ResponsiveColumns)."""
        page = QWidget()
        page.setObjectName("page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_LG)
        self._campaign_page_header = _page_header(
            tr("main_window.campaign_page.title"), tr("main_window.campaign_page.subtitle")
        )
        header_row.addWidget(self._campaign_page_header, 1)
        # Optional guided path; the cards below are the fast workflow.
        self._open_wizard_button = QPushButton(tr("main_window.campaign_page.open_wizard_button"), page)
        self._open_wizard_button.setProperty("variant", "ghost")
        self._open_wizard_button.setIcon(icons.themed("wizard"))
        self._open_wizard_button.clicked.connect(self._on_open_campaign_wizard_clicked)
        header_row.addWidget(self._open_wizard_button, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header_row)

        self._campaign_columns = ResponsiveColumns(LAUNCH_PANEL_WIDTH, CAMPAIGN_FOLD_WIDTH, page)
        outer.addWidget(self._campaign_columns, 1)
        left = self._campaign_columns.main_layout
        right = self._campaign_columns.side_layout

        # ---- Recipients ----
        recipients_section = QWidget()
        recipients_layout = QVBoxLayout(recipients_section)
        recipients_layout.setContentsMargins(0, 0, 0, 0)
        recipients_layout.setSpacing(SPACE_SM)
        recipients_layout.addWidget(self._recipient_widget)

        # Label, combo and actions wrap rather than force the column wider.
        groups_row = FlowLayout(spacing=SPACE_XS)
        self._groups_label = QLabel(tr("main_window.groups.label"), recipients_section)
        self._groups_label.setObjectName("helperText")
        groups_row.addWidget(self._groups_label)
        self._groups_combo = QComboBox(recipients_section)
        self._groups_combo.setMinimumWidth(COMBO_MIN_WIDTH)
        self._load_group_button = QPushButton(tr("main_window.groups.load_button"), recipients_section)
        self._load_group_button.setProperty("variant", "ghost")
        self._load_group_button.clicked.connect(self._on_load_group_clicked)
        self._save_group_button = QPushButton(tr("main_window.groups.save_button"), recipients_section)
        self._save_group_button.setProperty("variant", "ghost")
        self._save_group_button.clicked.connect(self._on_save_group_clicked)
        self._delete_group_button = QPushButton(tr("main_window.groups.delete_button"), recipients_section)
        self._delete_group_button.setProperty("variant", "ghost")
        self._delete_group_button.clicked.connect(self._on_delete_group_clicked)
        groups_row.addWidget(self._groups_combo)
        groups_row.addWidget(self._load_group_button)
        groups_row.addWidget(self._save_group_button)
        groups_row.addWidget(self._delete_group_button)
        recipients_layout.addLayout(groups_row)

        self._recipient_count_label = QLabel("0", page)
        self._recipient_count_label.setObjectName("cardCount")
        self._recipients_card = _card(
            tr("main_window.campaign_page.recipients_card"), recipients_section, self._recipient_count_label
        )
        left.addWidget(self._recipients_card)

        # ---- Message ----
        message_section = QWidget()
        message_layout = QVBoxLayout(message_section)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(SPACE_SM)

        message_buttons = FlowLayout(spacing=SPACE_SM)
        self._open_editor_button = QPushButton(tr("main_window.campaign_page.open_editor_button"), message_section)
        self._open_editor_button.setIcon(icons.themed("editor"))
        self._open_editor_button.setToolTip(tr("main_window.campaign_page.open_editor_tooltip"))
        self._open_editor_button.clicked.connect(self._on_open_editor_clicked)
        message_buttons.addWidget(self._open_editor_button)
        self._message_summary_label = QLabel("", message_section)
        self._message_summary_label.setObjectName("helperText")
        message_buttons.addWidget(self._message_summary_label)
        message_layout.addLayout(message_buttons)

        self._name_hint_label = QLabel(tr("main_window.campaign_page.name_placeholder_hint"), message_section)
        self._name_hint_label.setObjectName("helperText")
        self._name_hint_label.setWordWrap(True)
        message_layout.addWidget(self._name_hint_label)

        presets_row = FlowLayout(spacing=SPACE_XS)
        self._presets_label = QLabel(tr("main_window.presets.label"), message_section)
        self._presets_label.setObjectName("helperText")
        presets_row.addWidget(self._presets_label)
        self._presets_combo = QComboBox(message_section)
        self._presets_combo.setMinimumWidth(COMBO_MIN_WIDTH)
        self._load_preset_button = QPushButton(tr("main_window.presets.load_button"), message_section)
        self._load_preset_button.setProperty("variant", "ghost")
        self._load_preset_button.clicked.connect(self._on_load_preset_clicked)
        self._save_preset_button = QPushButton(tr("main_window.presets.save_button"), message_section)
        self._save_preset_button.setProperty("variant", "ghost")
        self._save_preset_button.clicked.connect(self._on_save_preset_clicked)
        self._delete_preset_button = QPushButton(tr("main_window.presets.delete_button"), message_section)
        self._delete_preset_button.setProperty("variant", "ghost")
        self._delete_preset_button.clicked.connect(self._on_delete_preset_clicked)
        presets_row.addWidget(self._presets_combo)
        presets_row.addWidget(self._load_preset_button)
        presets_row.addWidget(self._save_preset_button)
        presets_row.addWidget(self._delete_preset_button)
        message_layout.addLayout(presets_row)

        self._message_card = _card(tr("main_window.campaign_page.message_card"), message_section)
        left.addWidget(self._message_card)
        self._attachments_card = _card(tr("main_window.campaign_page.attachments_card"), self._attachments_widget)
        left.addWidget(self._attachments_card)

        # ---- right column: preview + launch ----
        preview_section = QWidget()
        preview_layout = QVBoxLayout(preview_section)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(SPACE_SM)
        preview_layout.addWidget(self._message_preview, 1)
        preview_name_row = QHBoxLayout()
        preview_name_row.setSpacing(SPACE_SM)
        self._preview_name_label = QLabel(tr("main_window.campaign_page.preview_name_label"), preview_section)
        self._preview_name_label.setObjectName("helperText")
        self._preview_name_edit = QLineEdit(preview_section)
        self._preview_name_edit.setText(tr("main_window.campaign_page.preview_name_default"))
        self._preview_name_edit.setToolTip(tr("main_window.campaign_page.preview_name_tooltip"))
        self._preview_name_edit.setMaximumWidth(PREVIEW_NAME_WIDTH)
        self._preview_name_edit.textChanged.connect(self._update_message_preview)
        preview_name_row.addWidget(self._preview_name_label)
        preview_name_row.addWidget(self._preview_name_edit)
        preview_name_row.addStretch(1)
        preview_layout.addLayout(preview_name_row)
        self._preview_card = _card(tr("main_window.campaign_page.preview_card"), preview_section)
        right.addWidget(self._preview_card, 1)

        self._campaign_card = self._campaign_controls
        right.addWidget(self._campaign_controls)

        self._campaign_columns.finish()
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
        layout.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        layout.setSpacing(SPACE_LG)
        self._results_page_header = _page_header(
            tr("main_window.results_page.title"), tr("main_window.results_page.subtitle")
        )
        layout.addWidget(self._results_page_header)

        self._results_empty_label = build_empty_state(
            tr("main_window.results_page.empty_title"),
            tr("main_window.results_page.empty_body"),
            page,
            icon_name="results",
            action_text=tr("main_window.results_page.empty_action"),
        )
        empty_state_action(self._results_empty_label).clicked.connect(lambda: self._navigate_to_page(_PAGE_CAMPAIGN))
        layout.addWidget(self._results_empty_label)

        status_row = QHBoxLayout()
        status_row.setSpacing(SPACE_SM)
        self._results_status_label = QLabel("", page)
        self._results_status_label.setObjectName("pill")
        status_row.addWidget(self._results_status_label)
        self._results_duration_label = QLabel("", page)
        self._results_duration_label.setObjectName("helperText")
        status_row.addWidget(self._results_duration_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

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

        self._failure_categories_title = QLabel(tr("main_window.results_page.failure_reasons_title"), page)
        self._failure_categories_title.setObjectName("sectionTitle")
        self._failure_categories_label = QLabel("", page)
        self._failure_categories_label.setWordWrap(True)
        self._failure_categories_label.setObjectName("helperText")
        self._failure_categories_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._failure_categories_label.setVisible(False)
        self._failure_categories_title.setVisible(False)
        layout.addWidget(self._failure_categories_title)
        layout.addWidget(self._failure_categories_label)

        # ---- recipients table ----
        self._failed_section_title = _section_title(tr("main_window.results_page.recipients_section"))
        self._failed_section_title.setVisible(False)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(SPACE_SM)
        toolbar.addWidget(self._failed_section_title)
        toolbar.addStretch(1)
        self._results_filter_label = QLabel(tr("main_window.results_page.filter_label"), page)
        self._results_filter_label.setObjectName("helperText")
        toolbar.addWidget(self._results_filter_label)
        self._results_filter_combo = SegmentedControl(page)
        self._results_filter_combo.addItem(tr("main_window.results_page.filter_all"), _RESULTS_FILTER_ALL)
        self._results_filter_combo.addItem(tr("main_window.results_page.filter_sent"), _RESULTS_FILTER_SENT)
        self._results_filter_combo.addItem(tr("main_window.results_page.filter_failed"), _RESULTS_FILTER_FAILED)
        self._results_filter_combo.addItem(tr("main_window.results_page.filter_skipped"), _RESULTS_FILTER_SKIPPED)
        self._results_filter_combo.setCurrentIndex(2)  # Failed -- the original Retry (v1.6) default
        self._results_filter_combo.currentIndexChanged.connect(lambda _i: self._refresh_failed_items())
        toolbar.addWidget(self._results_filter_combo)
        self._results_filter_row_widget = QWidget(page)
        self._results_filter_row_widget.setLayout(toolbar)
        self._results_filter_row_widget.setVisible(False)
        layout.addWidget(self._results_filter_row_widget)

        self._results_header = ResultsHeader(page)
        self._results_header.setVisible(False)
        layout.addWidget(self._results_header)
        self._failed_items_list = QListWidget(page)
        self._failed_items_list.setObjectName("resultsList")
        self._failed_items_list.setItemDelegate(ResultsRowDelegate(self._failed_items_list))
        self._failed_items_list.setMinimumHeight(RESULTS_LIST_MIN_HEIGHT)
        self._failed_items_list.setUniformItemSizes(True)
        self._failed_items_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._failed_items_list.setVisible(False)
        self._failed_items_list.itemChanged.connect(self._on_failed_item_check_changed)
        layout.addWidget(self._failed_items_list)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(SPACE_SM)
        self._retry_selected_button = QPushButton(tr("main_window.results_page.retry_selected_button"), page)
        self._retry_selected_button.setEnabled(False)
        self._retry_selected_button.clicked.connect(self._on_retry_selected_clicked)
        self._retry_all_button = QPushButton(tr("main_window.results_page.retry_all_button"), page)
        self._retry_all_button.setProperty("variant", "primary")
        self._retry_all_button.setIcon(icons.themed("retry", "on_accent"))
        self._retry_all_button.clicked.connect(self._on_retry_all_failures_clicked)
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.addWidget(self._retry_all_button)
        actions_row.addWidget(self._retry_selected_button)
        actions_row.addStretch(1)
        self._retry_row_widget = QWidget(page)
        self._retry_row_widget.setLayout(actions_row)
        self._retry_row_widget.setVisible(False)

        # Two short rows rather than one long one: retry (acting on the
        # failures) and keeping the results (save / export) are different
        # jobs, and five buttons in a row overflow a minimum-size window.
        layout.addWidget(self._retry_row_widget)
        export_row = QHBoxLayout()
        export_row.setSpacing(SPACE_SM)
        self._results_export_button = QPushButton(tr("main_window.results_page.export_csv_button"), page)
        self._results_export_button.setIcon(icons.themed("export"))
        self._results_export_button.setEnabled(False)
        self._results_export_button.clicked.connect(self._on_export_report_requested)
        self._export_failures_button = QPushButton(tr("main_window.results_page.export_failures_button"), page)
        self._export_failures_button.setProperty("variant", "ghost")
        self._export_failures_button.setEnabled(False)
        self._export_failures_button.clicked.connect(self._on_export_failures_clicked)
        self._save_report_button = QPushButton(tr("main_window.results_page.save_report_button"), page)
        self._save_report_button.setIcon(icons.themed("save"))
        self._save_report_button.setEnabled(False)
        self._save_report_button.clicked.connect(self._on_save_report_clicked)
        export_row.addWidget(self._save_report_button)
        export_row.addWidget(self._results_export_button)
        export_row.addWidget(self._export_failures_button)
        export_row.addStretch(1)
        layout.addLayout(export_row)

        self._saved_reports_section_title = _section_title(tr("main_window.results_page.saved_reports_section"))
        layout.addSpacing(SPACE_SM)
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
        layout.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
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
        self._diagnostics_card = _card(tr("main_window.settings.diagnostics_card"), self._build_diagnostics_settings())
        layout.addWidget(self._diagnostics_card)
        # Destructive options last, in their own section.
        self._advanced_card = _card(tr("main_window.settings.advanced_card"), self._build_advanced_settings())
        layout.addWidget(self._advanced_card)
        layout.addStretch(1)
        return page

    @staticmethod
    def _settings_grid(widget: QWidget) -> QGridLayout:
        """Label column on the left, one shared control width on the right,
        the explanation under each control in the secondary colour."""
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(SPACE_XL)
        grid.setVerticalSpacing(SPACE_XS)
        grid.setColumnMinimumWidth(0, SETTINGS_LABEL_WIDTH)
        grid.setColumnStretch(2, 1)
        return grid

    @staticmethod
    def _settings_row(grid: QGridLayout, row: int, label: Optional[QLabel], control, hint: Optional[QLabel]) -> int:
        """Place one setting; returns the next free row."""
        if label is not None:
            label.setObjectName("fieldLabel")
            grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        if isinstance(control, QWidget):
            if not isinstance(control, (QCheckBox, QLineEdit)):
                control.setFixedWidth(CONTROL_WIDTH)
            grid.addWidget(control, row, 1, 1, 2 if isinstance(control, (QCheckBox, QLineEdit)) else 1)
        else:
            grid.addLayout(control, row, 1, 1, 2)
        row += 1
        if hint is not None:
            hint.setObjectName("helperText")
            hint.setWordWrap(True)
            grid.addWidget(hint, row, 1, 1, 2)
            row += 1
        grid.setRowMinimumHeight(row, SPACE_MD)
        return row + 1

    def _build_appearance_settings(self) -> QWidget:
        widget = QWidget()
        grid = self._settings_grid(widget)
        self._theme_section_label = QLabel(tr("main_window.settings.theme_label"), widget)
        self._theme_combo = QComboBox(widget)
        for value in theme.VALID_THEMES:
            self._theme_combo.addItem(theme.THEME_LABELS[value], value)
        self._theme_hint_label = QLabel(tr("main_window.settings.theme_hint"), widget)
        row = self._settings_row(grid, 0, self._theme_section_label, self._theme_combo, self._theme_hint_label)

        self._language_section_label = QLabel(tr("main_window.settings.language_label"), widget)
        self._language_combo = QComboBox(widget)
        for value in VALID_LANGUAGES:
            self._language_combo.addItem(LANGUAGE_LABELS[value], value)
        self._language_hint_label = QLabel(tr("main_window.settings.language_hint"), widget)
        self._settings_row(grid, row, self._language_section_label, self._language_combo, self._language_hint_label)
        return widget

    def _build_sending_settings(self) -> QWidget:
        widget = QWidget()
        grid = self._settings_grid(widget)

        self._interval_section_label = QLabel(tr("main_window.settings.interval_label"), widget)
        interval_box = QWidget(widget)
        interval_row = QHBoxLayout(interval_box)
        interval_row.setContentsMargins(0, 0, 0, 0)
        interval_row.setSpacing(SPACE_SM)
        self._settings_min_spin = QSpinBox(interval_box)
        self._settings_min_spin.setRange(MIN_ALLOWED_DELAY_SECONDS, MAX_ALLOWED_DELAY_SECONDS)
        self._settings_max_spin = QSpinBox(interval_box)
        self._settings_max_spin.setRange(MIN_ALLOWED_DELAY_SECONDS, MAX_ALLOWED_DELAY_SECONDS)
        interval_row.addWidget(self._settings_min_spin, 1)
        self._interval_dash_label = QLabel(tr("main_window.settings.interval_dash"), interval_box)
        interval_row.addWidget(self._interval_dash_label)
        interval_row.addWidget(self._settings_max_spin, 1)
        self._interval_hint_label = QLabel(tr("main_window.settings.interval_hint"), widget)
        row = self._settings_row(grid, 0, self._interval_section_label, interval_box, self._interval_hint_label)
        self._settings_min_spin.editingFinished.connect(self._on_interval_settings_changed)
        self._settings_max_spin.editingFinished.connect(self._on_interval_settings_changed)

        self._confirm_before_start_checkbox = QCheckBox(tr("main_window.settings.confirm_before_start_checkbox"), widget)
        self._confirm_before_start_checkbox.setToolTip(tr("main_window.settings.confirm_before_start_tooltip"))
        self._confirm_before_start_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("confirm_before_start", checked)
        )
        self._confirm_hint_label = QLabel(tr("main_window.settings.confirm_before_start_tooltip"), widget)
        row = self._settings_row(grid, row, None, self._confirm_before_start_checkbox, self._confirm_hint_label)

        self._large_campaign_section_label = QLabel(tr("main_window.settings.large_campaign_label"), widget)
        self._large_campaign_spin = QSpinBox(widget)
        self._large_campaign_spin.setRange(MIN_LARGE_CAMPAIGN_THRESHOLD, MAX_LARGE_CAMPAIGN_THRESHOLD)
        self._large_campaign_spin.setPrefix(tr("main_window.settings.large_campaign_prefix"))
        self._large_campaign_spin.setSuffix(tr("main_window.settings.large_campaign_suffix"))
        self._large_campaign_spin.editingFinished.connect(self._on_large_campaign_threshold_changed)
        self._large_campaign_hint_label = QLabel(tr("main_window.settings.large_campaign_hint"), widget)
        self._settings_row(
            grid, row, self._large_campaign_section_label, self._large_campaign_spin, self._large_campaign_hint_label
        )
        return widget

    def _on_large_campaign_threshold_changed(self) -> None:
        settings = self._service.settings_repository.load_app_settings()
        settings.large_campaign_threshold = self._large_campaign_spin.value()
        try:
            self._service.settings_repository.save_app_settings(settings)
        except SettingsValidationError as exc:  # the spin box range already keeps it valid
            show_error(self, tr("main_window.settings.large_campaign_label"), str(exc))

    def _build_application_settings(self) -> QWidget:
        widget = QWidget()
        grid = self._settings_grid(widget)
        self._remember_window_checkbox = QCheckBox(tr("main_window.settings.remember_window_size_checkbox"), widget)
        self._remember_window_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("remember_window_size", checked)
        )
        row = self._settings_row(grid, 0, None, self._remember_window_checkbox, None)
        self._remember_page_checkbox = QCheckBox(tr("main_window.settings.remember_last_page_checkbox"), widget)
        self._remember_page_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("remember_last_page", checked)
        )
        self._settings_row(grid, row, None, self._remember_page_checkbox, None)
        return widget

    def _build_reports_settings(self) -> QWidget:
        widget = QWidget()
        grid = self._settings_grid(widget)
        self._reports_dir_section_label = QLabel(tr("main_window.settings.reports_directory_label"), widget)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(SPACE_SM)
        self._reports_dir_edit = QLineEdit(widget)
        self._reports_dir_edit.setPlaceholderText(str(get_reports_dir()))
        self._reports_dir_edit.setReadOnly(True)
        self._browse_reports_button = QPushButton(tr("main_window.settings.browse_button"), widget)
        self._browse_reports_button.setIcon(icons.themed("folder"))
        self._browse_reports_button.clicked.connect(self._on_browse_reports_directory)
        self._reset_reports_dir_button = QPushButton(tr("main_window.settings.default_button"), widget)
        self._reset_reports_dir_button.setProperty("variant", "ghost")
        self._reset_reports_dir_button.clicked.connect(self._on_reset_reports_directory)
        dir_row.addWidget(self._reports_dir_edit, 1)
        dir_row.addWidget(self._browse_reports_button)
        dir_row.addWidget(self._reset_reports_dir_button)
        row = self._settings_row(grid, 0, self._reports_dir_section_label, dir_row, None)

        self._auto_save_reports_checkbox = QCheckBox(tr("main_window.settings.auto_save_reports_checkbox"), widget)
        self._auto_save_reports_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("auto_save_reports", checked)
        )
        self._settings_row(grid, row, None, self._auto_save_reports_checkbox, None)
        return widget

    def _build_advanced_settings(self) -> QWidget:
        widget = QWidget()
        grid = self._settings_grid(widget)
        self._debug_logging_checkbox = QCheckBox(tr("main_window.settings.debug_logging_checkbox"), widget)
        self._debug_logging_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("debug_logging", checked)
        )
        row = self._settings_row(grid, 0, None, self._debug_logging_checkbox, None)

        self._reset_settings_button = QPushButton(tr("main_window.settings.reset_settings_button"), widget)
        self._reset_settings_button.setProperty("variant", "danger")
        self._reset_settings_button.clicked.connect(self._on_reset_settings_clicked)
        self._reset_hint_label = QLabel(tr("main_window.settings.reset_hint"), widget)
        self._settings_row(grid, row, None, self._reset_settings_button, self._reset_hint_label)
        return widget

    def _build_diagnostics_settings(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        self._diagnostics_text = QPlainTextEdit(widget)
        self._diagnostics_text.setObjectName("monoText")
        self._diagnostics_text.setReadOnly(True)
        self._diagnostics_text.setMaximumHeight(DIAGNOSTICS_MAX_HEIGHT)
        self._diagnostics_text.setFont(theme.mono_font())
        layout.addWidget(self._diagnostics_text)

        diagnostics_row = QHBoxLayout()
        diagnostics_row.setSpacing(SPACE_SM)
        self._copy_diagnostics_button = QPushButton(tr("main_window.settings.copy_diagnostics_button"), widget)
        self._copy_diagnostics_button.setIcon(icons.themed("copy"))
        self._copy_diagnostics_button.clicked.connect(self._on_copy_diagnostics_clicked)
        self._export_diagnostic_bundle_button = QPushButton(
            tr("main_window.settings.export_diagnostic_bundle_button"), widget
        )
        self._export_diagnostic_bundle_button.setIcon(icons.themed("export"))
        self._export_diagnostic_bundle_button.clicked.connect(self._on_export_diagnostic_bundle_clicked)
        self._refresh_diagnostics_button = QPushButton(tr("main_window.settings.refresh_diagnostics_button"), widget)
        self._refresh_diagnostics_button.setProperty("variant", "ghost")
        self._refresh_diagnostics_button.setIcon(icons.themed("refresh"))
        self._refresh_diagnostics_button.clicked.connect(self._refresh_diagnostics)
        diagnostics_row.addWidget(self._copy_diagnostics_button)
        diagnostics_row.addWidget(self._export_diagnostic_bundle_button)
        diagnostics_row.addWidget(self._refresh_diagnostics_button)
        diagnostics_row.addStretch(1)
        layout.addLayout(diagnostics_row)
        return widget

    def _diagnostics_telegram_status(self) -> str:
        account = self._active_account()
        if account is None:
            return tr("diagnostics.telegram.no_account")
        label = f"@{account.username}" if account.username else account.phone
        return tr("diagnostics.telegram.connected", label=label)

    def _diagnostics_network_status(self) -> str:
        account = self._active_account()
        account_manager = self._service.account_manager
        if account is None or account_manager is None:
            return tr("diagnostics.network.unknown")
        client = account_manager.get_active_client(account.session_name)
        if client is not None and client.is_connected():
            return tr("diagnostics.network.connected")
        return tr("diagnostics.network.unknown")

    def _refresh_diagnostics(self) -> None:
        report = diagnostics.collect_diagnostics(
            self._database, self._diagnostics_telegram_status(), self._diagnostics_network_status()
        )
        self._last_diagnostics_text = diagnostics.format_diagnostics_text(report)
        self._diagnostics_text.setPlainText(self._last_diagnostics_text)

    def _on_copy_diagnostics_clicked(self) -> None:
        self._refresh_diagnostics()
        QApplication.clipboard().setText(self._last_diagnostics_text)
        self._toast(tr("main_window.dialogs.diagnostics_copied_message"))

    def _on_export_diagnostic_bundle_clicked(self) -> None:
        default_name = f"TelegramMassSender_diagnostics_{datetime.now():%Y-%m-%d_%H-%M}.zip"
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            tr("main_window.dialogs.export_diagnostic_bundle_title"),
            default_name,
            tr("main_window.dialogs.export_diagnostic_bundle_file_filter"),
        )
        if not path_str:
            return
        try:
            export_diagnostic_bundle(
                Path(path_str),
                self._database,
                self._service.settings_repository.load_app_settings(),
                self._diagnostics_telegram_status(),
                self._diagnostics_network_status(),
            )
        except OSError as exc:
            show_error(
                self,
                tr("main_window.dialogs.export_diagnostic_bundle_title"),
                tr("main_window.dialogs.export_diagnostic_bundle_write_failed", error=exc),
            )
            return
        show_info(
            self,
            tr("main_window.dialogs.export_diagnostic_bundle_title"),
            tr("main_window.dialogs.export_diagnostic_bundle_saved", path=path_str),
        )

    def _wire_signals(self) -> None:
        self._sidebar.page_selected.connect(self._on_sidebar_page_selected)
        self._sidebar.account_clicked.connect(lambda: self._navigate_to_page(_PAGE_ACCOUNTS))
        self._sidebar.collapsed_changed.connect(lambda collapsed: self._save_setting_field("sidebar_collapsed", collapsed))
        self._journal_toggle_button.clicked.connect(self._on_toggle_journal)
        self._journal.toggle_requested.connect(self._on_toggle_journal)

        self._account_widget.add_account_requested.connect(self._on_add_account_requested)
        self._account_widget.account_selected.connect(self._on_account_selected)
        self._account_widget.delete_account_requested.connect(self._on_delete_account_requested)
        self._account_widget.reconnect_requested.connect(self._on_reconnect_requested)
        self._account_widget.rename_requested.connect(self._on_rename_account_requested)
        self._account_widget.try_demo_mode_requested.connect(self._on_try_demo_mode_requested)

        self._recipient_widget.recipients_changed.connect(self._on_form_state_changed)
        self._recipient_widget.recipients_changed.connect(self._on_recipients_changed)
        self._recipient_widget.pick_chats_requested.connect(lambda: self._on_pick_chats_requested())
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
        self._show_page(index)
        self._sidebar.set_current_index(index)

    def _on_sidebar_page_selected(self, index: int) -> None:
        self._show_page(index)

    def _show_page(self, index: int) -> None:
        if self._stack.currentIndex() == index:
            return
        self._stack.setCurrentIndex(index)
        if self.isVisible():
            fade_in(self._stack.currentWidget())

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
        self._large_campaign_spin.blockSignals(True)
        self._large_campaign_spin.setValue(settings.large_campaign_threshold)
        self._large_campaign_spin.blockSignals(False)

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
        defaults.sidebar_collapsed = self._sidebar.is_collapsed  # a layout choice, like the theme
        self._service.settings_repository.save_app_settings(defaults)
        self._load_settings_into_page(defaults)
        self._campaign_controls.set_interval_summary(defaults.min_delay_seconds, defaults.max_delay_seconds)
        self._toast(tr("main_window.dialogs.settings_reset_message"), "info")

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
        attachments = self._attachments_widget.get_attachments()
        attachment_names = [a.file_name for a in attachments]
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
        self._message_preview.update_preview(preview_text, preview_entities, attachment_names, attachments)
        self._update_message_summary(attachments)
        self._on_form_state_changed()

    def _update_message_summary(self, attachments) -> None:
        if self._message_text.strip():
            text = tr("main_window.campaign_page.message_summary", chars=len(self._message_text))
        else:
            text = tr("main_window.campaign_page.message_empty")
        self._message_summary_label.setText(text)
        self._campaign_controls.set_attachment_count(len(attachments))

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
        self._toast(tr("main_window.dialogs.preset_saved_message", name=saved.name))

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
        self._toast(tr("main_window.dialogs.group_saved_message", name=saved.name))

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

    def _build_campaign_wizard(self) -> CampaignWizardDialog:
        dialog = CampaignWizardDialog(self._service.settings_repository, self)
        wizard_recipients = dialog.recipient_widget
        wizard_recipients.pick_chats_requested.connect(
            lambda: self._on_pick_chats_requested(wizard_recipients, dialog)
        )
        self._campaign_wizard = dialog
        self._update_pick_chats_enabled()
        return dialog

    def _on_open_campaign_wizard_clicked(self) -> None:
        dialog = self._build_campaign_wizard()
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._campaign_wizard = None
        if not accepted:
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
        self._campaign_controls.set_recipient_breakdown(sum(1 for r in summary.valid_recipients if r.is_chat_target))
        self._campaign_controls.set_recipient_count(len(summary.valid_recipients))

    # ---- account management -------------------------------------------------

    def _spawn(self, coro, description: str):
        """Start a background coroutine whose outcome is actually observed.

        Every UI-triggered async operation goes through here instead of a
        bare asyncio.ensure_future(). MainWindow is the right boundary to
        observe them: it started them in response to a user action, and it
        owns the widgets that have to reflect the result. A blanket
        try/except inside each coroutine would instead hide real failures
        (a delete silently not deleting, say) behind a UI that looks fine.
        """
        task = asyncio.ensure_future(coro)
        self._background_tasks.add(task)
        task.add_done_callback(lambda finished: self._on_background_task_done(finished, description))
        return task

    def _on_background_task_done(self, task, description: str) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        # Retrieving the exception here is what stops asyncio reporting it
        # later as "Task exception was never retrieved".
        self._logger.error("Фоновая операция «%s» завершилась ошибкой: %s", description, error)

    async def _cancel_background_tasks(self) -> None:
        """Cancel and await every background task except the caller's own.

        Called during shutdown: an account refresh still in flight would
        otherwise keep using the database and client manager after
        _perform_shutdown has closed them. Awaiting the cancellations
        (rather than just requesting them) is what guarantees none of them
        is still mid-statement when the database closes.
        """
        current = asyncio.current_task()
        pending = [t for t in self._background_tasks if t is not current and not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _can_switch_accounts(self) -> bool:
        return self._current_campaign is None or not self._current_campaign.is_active

    def _ensure_switch_guard(self) -> None:
        if self._service.account_manager is not None:
            self._service.account_manager.set_switch_guard(self._can_switch_accounts)

    async def _refresh_accounts(self, select_id: Optional[int] = None) -> None:
        # Serialized against deletes/switches/demo transitions: this method
        # calls check_status for every account, which builds and connects a
        # Telethon client (and therefore opens its session file). Running
        # that concurrently with a delete reopened the very session file
        # the delete was about to remove.
        async with self._account_lock:
            await self._refresh_accounts_locked(select_id)

    async def _refresh_accounts_locked(self, select_id: Optional[int] = None) -> None:
        self._ensure_switch_guard()
        account_manager = self._service.account_manager
        if account_manager is None:
            self._account_statuses = {}
            self._account_widget.set_accounts([])
            self._on_form_state_changed()
            self._update_connection_status()
            return
        statuses = await account_manager.list_accounts_with_status()
        valid_ids = {s.account.id for s in statuses}
        self._account_statuses = {s.account.id: s for s in statuses}

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
        # The dot is a secondary cue only -- the text always spells out
        # "Connected"/"No account", so state is never colour-only.
        account = self._active_account()
        if account is None:
            dot_status, text = "", tr("main_window.status.no_account")
            self._sidebar.set_account(None)
        else:
            label = f"@{account.username}" if account.username else account.phone
            dot_status, text = "success", tr("main_window.status.connected", label=label)
            status = self._account_statuses.get(account.id)
            if status is not None:
                status_text, dot_status = status_text_and_variant(status)
            else:
                status_text = tr("account_widget.status.connected")
            self._sidebar.set_account((account_initials(account), display_name(account), status_text, dot_status))
        theme.set_status(self._connection_dot, dot_status)
        self._connection_status_label.setText(text)
        self._refresh_diagnostics()

    def _toast(self, text: str, status: str = "success") -> None:
        """Non-blocking confirmation for a successful, non-critical action."""
        self._toasts.show_toast(text, status)

    def _on_add_account_requested(self) -> None:
        if not self._can_switch_accounts():
            show_error(self, tr("main_window.dialogs.unavailable_title"), tr("main_window.dialogs.add_account_unavailable"))
            return
        if self._service.is_demo_mode:
            # In demo mode the login dialog would run against the
            # DemoClientManager, "authorizing" a fabricated account -- and
            # it would still write the entered API credentials to
            # SecureStorage and leave a real account row behind that
            # outlives demo mode. Adding an account is a real-mode action.
            show_error(
                self,
                tr("main_window.dialogs.unavailable_title"),
                tr("main_window.dialogs.add_account_in_demo_mode"),
            )
            return
        dialog = LoginDialog(self._service, self)
        result_holder: dict = {}
        dialog.account_ready.connect(lambda acc: result_holder.__setitem__("account", acc))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            account = result_holder.get("account")
            self._spawn(self._refresh_accounts(select_id=account.id if account else None), "обновление списка аккаунтов")

    def _on_account_selected(self, account_id: int) -> None:
        if self._account_switch_in_progress:
            return  # a switch is already in flight -- ignore the extra click
        # Set synchronously, before scheduling the coroutine: two clicks
        # arriving back-to-back (before the event loop ever runs
        # _switch_account) must both see this guard, not just the second
        # one to actually start executing.
        self._account_switch_in_progress = True
        self._spawn(self._switch_account(account_id), "переключение аккаунта")

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
        if account_id != previous_active_id:
            self._dialog_cache.clear()
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
        self._spawn(self._delete_account(account), "удаление аккаунта")

    async def _delete_account(self, account: Account) -> None:
        account_manager = self._service.account_manager
        if account_manager is None:
            return
        async with self._account_lock:
            if self._is_active_account(account):
                self._dialog_cache.clear()
            try:
                await account_manager.delete_account(account)
            except AccountDeletionError as exc:
                # The account could not be fully removed (most plausibly a
                # session file still held open by Windows). Say so rather
                # than leaving the user with a list that silently did not
                # change, and keep the window usable.
                self._logger.warning("Не удалось удалить аккаунт %s: %s", account.phone, exc)
                show_error(
                    self,
                    tr("main_window.dialogs.delete_account_failed_title"),
                    tr("main_window.dialogs.delete_account_failed"),
                )
        await self._refresh_accounts()

    def _on_reconnect_requested(self, account_id: int) -> None:
        self._spawn(self._refresh_accounts(select_id=account_id), "обновление списка аккаунтов")

    def _on_rename_account_requested(self, account_id: int) -> None:
        # Deliberately not gated by _can_switch_accounts() -- unlike
        # switching or deleting, renaming a purely local, cosmetic alias
        # has no effect on an in-flight campaign's active account, so
        # there's nothing unsafe about allowing it at any time (same
        # reasoning as reconnect, just above, which is likewise ungated).
        account_manager = self._service.account_manager
        if account_manager is None:
            return
        account = self._service.account_repository.get_by_id(account_id)
        if account is None:
            return
        new_alias, ok = QInputDialog.getText(
            self,
            tr("main_window.dialogs.rename_account_title"),
            tr("main_window.dialogs.account_alias_label"),
            text=account.local_alias or "",
        )
        if not ok:
            return
        account_manager.rename_account(account, new_alias)
        self._spawn(self._refresh_accounts(), "обновление списка аккаунтов")

    # ---- demo mode (ROADMAP v2.0) -----------------------------------------------

    def _on_try_demo_mode_requested(self) -> None:
        if not self._can_switch_accounts():
            show_error(self, tr("main_window.dialogs.unavailable_title"), tr("main_window.dialogs.add_account_unavailable"))
            return
        self._enter_demo_mode()

    def _enter_demo_mode(self) -> None:
        self._transition_demo_mode(enter=True)

    def _on_exit_demo_mode_clicked(self) -> None:
        if not self._can_switch_accounts():
            show_error(self, tr("main_window.dialogs.unavailable_title"), tr("main_window.dialogs.delete_account_unavailable"))
            return
        self._transition_demo_mode(enter=False)

    def _transition_demo_mode(self, *, enter: bool) -> None:
        """Both demo-mode transitions.

        The service-side swap itself is synchronous on purpose: it is pure
        in-memory bookkeeping with no network call, and the banner and
        is_demo_mode flag are what the next click is guarded against, so
        deferring them would let a second click act on stale state.

        Only the account refresh that follows is asynchronous, and it is
        serialized behind _account_lock. A refresh already in flight when
        the swap happens may still paint one stale list (it collected its
        statuses from the previous client manager); the refresh queued
        here runs after it and always reflects the mode actually in
        effect, so the settled state is correct either way.
        """
        if enter == self._service.is_demo_mode:
            return  # already in the requested mode
        if enter:
            self._service.enter_demo_mode()
        else:
            self._service.exit_demo_mode()
        self._dialog_cache.clear()
        self._demo_banner.setVisible(enter)
        # A half-finished switch belongs to the mode we just left.
        self._account_switch_in_progress = False
        self._spawn(
            self._refresh_accounts(),
            "вход в демо-режим" if enter else "выход из демо-режима",
        )
        self.statusBar().showMessage(tr("main_window.status.ready"))

    def maybe_show_onboarding(self) -> None:
        """Shown once, the first time the app has no persisted
        onboarding_completed setting -- deliberately NOT called from
        __init__ (a blocking modal dialog started mid-construction would
        hang every test that constructs MainWindow directly, since a
        fresh test database's onboarding_completed is always False).
        Only app.main.main() calls this, once, right after window.show()
        -- the one real entry point that should ever see it."""
        settings = self._service.settings_repository.load_app_settings()
        if settings.onboarding_completed:
            return
        dialog = OnboardingDialog(self)
        dialog.exec()
        settings.onboarding_completed = True
        try:
            self._service.settings_repository.save_app_settings(settings)
        except SettingsValidationError:
            pass
        if dialog.action == ONBOARDING_ACTION_GET_STARTED:
            self._on_add_account_requested()
        elif dialog.action == ONBOARDING_ACTION_TRY_DEMO:
            self._enter_demo_mode()

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
        self._update_pick_chats_enabled()

    # ---- "From my chats…" -------------------------------------------------------

    def _active_account_connected(self) -> bool:
        account = self._active_account()
        if account is None:
            return False
        status = self._account_statuses.get(account.id)
        return status is not None and status.is_authorized and not status.connection_error

    def _update_pick_chats_enabled(self) -> None:
        campaign_busy = self._campaign_starting or (
            self._current_campaign is not None and self._current_campaign.is_active
        )
        enabled = self._active_account_connected() and not campaign_busy and self._chat_picker is None
        self._recipient_widget.set_pick_chats_enabled(enabled)
        if self._campaign_wizard is not None:
            self._campaign_wizard.recipient_widget.set_pick_chats_enabled(enabled)

    def _on_pick_chats_requested(
        self, target: Optional[RecipientWidget] = None, parent: Optional[QWidget] = None
    ) -> None:
        """Open the picker over `parent` (the window, or the Campaign
        Wizard) and fill `target` (the Campaign page's Recipients box, or
        the wizard's). The dialog opens at once and loads in the
        background, so a long dialog list never blocks the window."""
        target = target or self._recipient_widget
        parent = parent or self
        if self._chat_picker is not None or self._campaign_starting:
            return
        if self._current_campaign is not None and self._current_campaign.is_active:
            return
        account = self._active_account()
        if account is None or not self._active_account_connected():
            show_error(parent, tr("chat_picker.title"), tr("chat_picker.error.no_account"))
            return
        target.flush()
        dialog = ChatPickerDialog({r.normalized_key for r in target.valid_recipients()}, parent)
        self._chat_picker = dialog
        dialog.refresh_requested.connect(lambda: self._load_dialogs_into(dialog, account))
        dialog.accepted.connect(lambda: self._add_picked_dialogs(dialog, target))
        dialog.finished.connect(lambda _code: self._on_chat_picker_finished(dialog))
        self._update_pick_chats_enabled()
        dialog.open()
        cached = self._dialog_cache.get(self._dialog_cache_key(account))
        if cached is not None:
            dialog.set_dialogs(cached.dialogs)
        else:
            self._load_dialogs_into(dialog, account)

    @staticmethod
    def _dialog_cache_key(account: Account):
        return (account.id, account.session_name)

    def _load_dialogs_into(self, dialog: ChatPickerDialog, account: Account) -> None:
        """First open, or Refresh: always a fresh read, replacing the cache."""
        self._dialog_cache.clear()
        dialog.set_loading()
        self._spawn(self._load_dialogs(dialog, account), "загрузка списка диалогов")

    async def _load_dialogs(self, dialog: ChatPickerDialog, account: Account) -> None:
        account_manager = self._service.account_manager
        assert account_manager is not None
        snapshot = None
        try:
            # Same lock as refresh/switch/delete: this reads through the
            # account's live client and must not interleave with them.
            async with self._account_lock:
                client = await account_manager.ensure_connected(account)
                authorized = await client.is_user_authorized()
                if authorized:
                    snapshot = await load_dialog_snapshot(client)
            error = None if authorized else tr("chat_picker.error.not_authorized")
        except FloodWaitError as exc:
            # Never retried behind the user's back: they're told how long
            # Telegram wants them to wait and can press Refresh afterwards.
            error = tr("chat_picker.error.flood_wait", seconds=int(exc.seconds))
        except Exception as exc:  # noqa: BLE001 - shown in the picker itself
            self._logger.warning("Не удалось загрузить список диалогов: %s", exc)
            error = tr("chat_picker.error.load_failed", error=exc)
        if snapshot is not None and self._is_active_account(account):
            self._dialog_cache.put(self._dialog_cache_key(account), snapshot)
        if self._chat_picker is not dialog:
            return  # closed while loading (the cache still keeps the result)
        if error is not None:
            dialog.set_error(error)
        else:
            dialog.set_dialogs(snapshot.dialogs)

    def _is_active_account(self, account: Account) -> bool:
        active = self._active_account()
        return active is not None and self._dialog_cache_key(active) == self._dialog_cache_key(account)

    def _add_picked_dialogs(self, dialog: ChatPickerDialog, target: RecipientWidget) -> None:
        added = target.append_lines(dialog.selected_lines())
        if target is self._recipient_widget:
            self._toast(tr("chat_picker.added_status", count=added))

    def _on_chat_picker_finished(self, dialog: ChatPickerDialog) -> None:
        if self._chat_picker is dialog:
            self._chat_picker = None
        dialog.deleteLater()
        self._update_pick_chats_enabled()

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
        if not self._confirm_campaign_start(recipients, settings):
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
        self._update_pick_chats_enabled()
        self._spawn(
            self._start_campaign(
                account, recipients, text, entities, attachments, rate_limiter, settings.retry_count, recipient_names
            ),
            "запуск рассылки",
        )

    def _recipient_breakdown(self, recipients) -> RecipientBreakdown:
        """People / bots / chats / not-yet-known -- from the cached dialogs
        where a recipient is among them, else from its format alone.
        Nothing is resolved before the user confirms."""
        people = bots = chats = unknown = 0
        known = self._cached_categories()
        for recipient in recipients:
            category = known.get(recipient.normalized_key)
            if category is DialogCategory.BOTS:
                bots += 1
            elif category is DialogCategory.PEOPLE:
                people += 1
            elif category is not None or recipient.is_chat_target:
                chats += 1
            elif recipient.kind == RecipientKind.USERNAME:
                unknown += 1
            else:
                people += 1
        return RecipientBreakdown(people=people, bots=bots, chats=chats, unknown=unknown)

    def _cached_categories(self) -> Dict[str, DialogCategory]:
        """normalized recipient key -> category, for the active account's
        cached dialogs: a @username picked there is known to be a person,
        a bot or a chat before anything is resolved."""
        account = self._active_account()
        snapshot = self._dialog_cache.get(self._dialog_cache_key(account)) if account is not None else None
        if snapshot is None:
            return {}
        return {key: dialog.category for dialog in snapshot.dialogs.dialogs for key in dialog_recipient_keys(dialog)}

    def _confirm_campaign_start(self, recipients, settings) -> bool:
        """The one pre-start confirmation for every start path (Campaign
        page, Campaign Wizard, Retry). More recipients than the
        large-campaign threshold always asks, with Cancel as the default,
        whatever confirm_before_start says; otherwise the optional
        confirmation asks only when it is switched on."""
        if len(recipients) > settings.large_campaign_threshold:
            return confirm_large_campaign(
                self, self._recipient_breakdown(recipients), settings.large_campaign_threshold
            )
        if settings.confirm_before_start:
            chat_count = sum(1 for r in recipients if r.is_chat_target)
            username_count = sum(1 for r in recipients if r.kind == RecipientKind.USERNAME)
            return confirm_start_campaign(self, len(recipients), chat_count, username_count)
        return True

    async def _start_campaign(
        self,
        account,
        recipients,
        text,
        entities,
        attachments,
        rate_limiter,
        retry_count,
        recipient_names,
        delivered_chat_ids=None,
        resume_steps=None,
    ) -> None:
        account_manager = self._service.account_manager
        assert account_manager is not None
        try:
            client = await account_manager.ensure_connected(account)
            if not await client.is_user_authorized():
                show_error(self, tr("main_window.dialogs.campaign_title"), tr("main_window.start_error.not_authorized"))
                self._campaign_starting = False
                self._update_pick_chats_enabled()
                return
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            show_error(self, tr("main_window.dialogs.campaign_title"), tr("main_window.start_error.connect_failed", error=exc))
            self._campaign_starting = False
            self._update_pick_chats_enabled()
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
            # Retry only: chats the retried campaign already delivered to,
            # and steps of a partly delivered message that already went out
            # -- neither is ever sent a second time.
            delivered_chat_ids=delivered_chat_ids,
            resume_steps=resume_steps,
            dialog_snapshot=self._dialog_cache.get(self._dialog_cache_key(account)),
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
        self._update_pick_chats_enabled()

        campaign.state_changed.connect(self._on_campaign_state_changed)
        campaign.progress_changed.connect(self._campaign_controls.update_progress)
        campaign.progress_changed.connect(self._update_results_stats)
        campaign.current_item_changed.connect(self._campaign_controls.set_current_item)
        campaign.log_message.connect(self._journal.append)
        campaign.flood_wait_started.connect(self._on_flood_wait_started)
        campaign.flood_wait_tick.connect(self._on_flood_wait_tick)
        campaign.finished.connect(self._on_campaign_finished)

        campaign.start()
        if self._campaign_columns.is_folded:
            # One-column layout: bring the progress panel into view.
            self._campaign_columns.scroll.ensureWidgetVisible(self._campaign_controls)
        self._campaign_controls.start_elapsed_timer()
        self._campaign_controls.set_running_state(True, paused=False)
        self._set_results_status(tr("main_window.results.running"), "info")
        self._update_results_page()
        self.statusBar().showMessage(tr("main_window.status.campaign_running"))

    def _on_campaign_state_changed(self, status_value: str) -> None:
        status = CampaignStatus(status_value)
        if status == CampaignStatus.RUNNING:
            self._campaign_controls.set_running_state(True, paused=False)
            self._campaign_controls.set_flood_wait(None)
            self._campaign_controls.set_status_text("")
            self.statusBar().showMessage(tr("main_window.status.campaign_running"))
        elif status == CampaignStatus.PAUSED:
            self._campaign_controls.set_running_state(True, paused=True)
            self.statusBar().showMessage(tr("main_window.status.campaign_paused"))
        elif status == CampaignStatus.WAITING_FOR_FLOOD:
            self._campaign_controls.set_running_state(True, paused=True)
            self.statusBar().showMessage(tr("main_window.status.campaign_waiting_flood"))

    def _on_flood_wait_started(self, seconds: int) -> None:
        self._campaign_controls.set_flood_wait(seconds)

    def _on_flood_wait_tick(self, remaining: int) -> None:
        self._campaign_controls.set_flood_wait(remaining)

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
            self._set_results_status(tr("main_window.results.completed"), "success")
            self._notify(
                tr("main_window.notifications.campaign_completed_title"),
                tr("main_window.notifications.campaign_completed_body"),
                QSystemTrayIcon.MessageIcon.Information,
            )
        elif status == CampaignStatus.STOPPED:
            self.statusBar().showMessage(tr("main_window.status.campaign_stopped"))
            self._set_results_status(tr("main_window.results.stopped"), "warning")
        elif status == CampaignStatus.ERROR:
            self.statusBar().showMessage(tr("main_window.status.campaign_error"))
            self._set_results_status(tr("main_window.results.error"), "error")
            show_error(
                self,
                tr("main_window.dialogs.campaign_error_title"),
                tr("main_window.dialogs.campaign_error_message"),
            )
            self._notify(
                tr("main_window.notifications.critical_error_title"),
                tr("main_window.notifications.campaign_error_body"),
                QSystemTrayIcon.MessageIcon.Critical,
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
            self._spawn(self._current_campaign.stop(), "остановка рассылки")

    # ---- results page -----------------------------------------------------------

    def _update_results_page(self) -> None:
        has_data = self._report_source is not None and bool(self._report_source.items)
        self._results_empty_label.setVisible(not has_data)
        self._results_stats_widget.setVisible(has_data)
        if self._report_source is not None:
            self._update_results_stats(self._report_source.snapshot())
        self._refresh_failed_items()

    def _set_results_status(self, text: str, status: str) -> None:
        self._results_status_label.setText(text)
        theme.set_status(self._results_status_label, status)

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
            chat_type = _chat_type_of(item)
            if chat_type is not None:
                text += f"  ({target_type_label(chat_type)})"
            if item.error:
                text += f"  —  {item.error}"
            list_item = QListWidgetItem(text)
            if item.status == SendItemStatus.FAILED:
                list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                list_item.setCheckState(Qt.CheckState.Unchecked)
            else:
                list_item.setFlags(list_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            list_item.setToolTip(text)
            self._failed_items_list.addItem(list_item)
        self._failed_items_list.blockSignals(False)

        has_any = bool(all_items)
        self._failed_section_title.setVisible(has_any)
        self._results_filter_row_widget.setVisible(has_any)
        self._failed_items_list.setVisible(has_any)
        self._results_header.setVisible(has_any)
        self._retry_row_widget.setVisible(bool(failed_items))
        self._retry_all_button.setEnabled(bool(failed_items))
        self._export_failures_button.setEnabled(bool(failed_items))
        self._update_retry_selected_enabled()
        self._update_failure_categories(failed_items)

    def _update_failure_categories(self, failed_items: List) -> None:
        if not failed_items:
            self._failure_categories_label.setVisible(False)
            self._failure_categories_title.setVisible(False)
            return
        counts: Dict[str, int] = {}
        for item in failed_items:
            category_key = _ERROR_CATEGORY_LABEL_KEYS.get(item.error_category)
            reason = tr(category_key) if category_key else item.error or tr("main_window.results_page.unknown_error")
            counts[reason] = counts.get(reason, 0) + 1
        parts = [f"{reason}: {count}" for reason, count in sorted(counts.items(), key=lambda kv: -kv[1])]
        self._failure_categories_label.setText("\n".join(parts))
        self._failure_categories_label.setVisible(True)
        self._failure_categories_title.setVisible(True)

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
        if not self._confirm_campaign_start(recipients, settings):
            return
        try:
            rate_limiter = RateLimiter(settings.min_delay_seconds, settings.max_delay_seconds)
        except SettingsValidationError as exc:
            show_error(self, tr("main_window.dialogs.interval_title"), str(exc))
            return
        # "Retry" never re-sends what already arrived: chats the previous
        # run delivered to are skipped (a failed "-100..." line may be the
        # same chat as a delivered "@name" line), and a message that failed
        # half-way resumes after its last delivered part.
        source_items = self._report_source.items if self._report_source is not None else []
        delivered_chat_ids = set(getattr(self._report_source, "delivered_chat_ids", ()) or ())
        resume_steps = {
            item.recipient.normalized_key: item.next_step
            for item in source_items
            if item.status == SendItemStatus.FAILED and item.next_step > 0
        }
        self._campaign_starting = True
        self._update_pick_chats_enabled()
        self._spawn(
            self._start_campaign(
                account,
                recipients,
                text,
                entities,
                attachments,
                rate_limiter,
                settings.retry_count,
                recipient_names,
                delivered_chat_ids=delivered_chat_ids,
                resume_steps=resume_steps,
            ),
            "запуск рассылки",
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
        self._toast(tr("main_window.dialogs.report_saved_message", name=name))

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
        """One saved report as a row: favourite star, name, counts and date,
        Open, and the rest (export / rename / delete) in a "more" menu."""
        card = QFrame()
        card.setObjectName("reportCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(SPACE_MD, SPACE_SM, SPACE_SM, SPACE_SM)
        row.setSpacing(SPACE_SM)

        favorite_button = QToolButton(card)
        favorite_button.setObjectName("favoriteButton")
        favorite_button.setCheckable(True)
        favorite_button.setChecked(report.is_favorite)
        favorite_button.setIcon(icons.themed("favorite", "text_muted", checked_role="favorite"))
        favorite_button.setProperty("active", "true" if report.is_favorite else "false")
        favorite_button.setToolTip(tr("main_window.results_page.report_favorite_tooltip"))
        favorite_button.setAccessibleName(tr("main_window.results_page.report_favorite_tooltip"))
        favorite_button.clicked.connect(lambda: self._on_toggle_favorite(report))
        row.addWidget(favorite_button)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        name_label = QLabel(report.name, card)
        name_label.setObjectName("reportName")
        text_col.addWidget(name_label)
        meta = QLabel(
            tr(
                "main_window.results_page.report_meta_line",
                total=report.total,
                successful=report.successful,
                failed=report.failed,
            )
            + "  ·  "
            + report.created_at,
            card,
        )
        meta.setObjectName("reportMeta")
        text_col.addWidget(meta)
        row.addLayout(text_col, 1)

        open_button = QPushButton(tr("main_window.results_page.report_open_button"), card)
        open_button.setProperty("variant", "ghost")
        open_button.setIcon(icons.themed("open"))
        open_button.clicked.connect(lambda: self._on_open_saved_report(report))
        row.addWidget(open_button)

        more_button = QToolButton(card)
        more_button.setObjectName("iconButton")
        more_button.setIcon(icons.themed("more"))
        more_button.setToolTip(tr("main_window.results_page.report_more_tooltip"))
        more_button.setAccessibleName(tr("main_window.results_page.report_more_tooltip"))
        more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(more_button)
        export_action = more_menu.addAction(icons.themed("export"), tr("main_window.results_page.report_export_button"))
        export_action.triggered.connect(lambda: self._on_export_saved_report(report))
        rename_action = more_menu.addAction(icons.themed("edit"), tr("main_window.results_page.report_rename_action"))
        rename_action.triggered.connect(lambda: self._on_rename_saved_report(report))
        more_menu.addSeparator()
        delete_action = more_menu.addAction(icons.themed("delete", "error"), tr("main_window.results_page.report_delete_action"))
        delete_action.triggered.connect(lambda: self._on_delete_saved_report(report))
        more_button.setMenu(more_menu)
        row.addWidget(more_button)
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

    # ---- system tray -------------------------------------------------------------

    def _setup_system_tray(self) -> None:
        """Always constructed (cheap, and lets tests exercise the wiring),
        but only actually shown when the platform genuinely has a tray to
        show it in -- QSystemTrayIcon.isSystemTrayAvailable() is False
        under the offscreen platform this suite runs under, so this is a
        safe no-op there rather than a real icon appearing anywhere."""
        icon_path = get_resource_path("assets", "icons", "app.ico")
        icon = QIcon(str(icon_path)) if icon_path.exists() else self.windowIcon()
        self._tray_icon = QSystemTrayIcon(icon, self)
        self._tray_icon.setToolTip(WINDOW_TITLE)

        # QSystemTrayIcon.setContextMenu() does NOT take ownership of the
        # menu (per Qt's own docs) -- stored on self so this stays alive
        # for the window's lifetime; a plain local would be eligible for
        # Python/shiboken garbage collection the moment this method
        # returns, leaving the tray icon's context menu pointer dangling
        # (the same class of Qt object-lifetime hazard already caught
        # twice this session with QStyle/QProxyStyle).
        self._tray_menu = QMenu()
        show_action = self._tray_menu.addAction(tr("main_window.tray.show"))
        show_action.triggered.connect(self._restore_from_tray)
        self._tray_menu.addSeparator()
        exit_action = self._tray_menu.addAction(tr("main_window.tray.exit"))
        exit_action.triggered.connect(self.close)
        self._tray_icon.setContextMenu(self._tray_menu)
        self._tray_icon.activated.connect(self._on_tray_icon_activated)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon.show()

    def _on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        if self._restore_maximized_from_tray:
            self.showMaximized()
        else:
            self.showNormal()
        self.activateWindow()
        self.raise_()

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # "Minimize to tray": once minimized, hide from the taskbar
        # entirely rather than leaving a minimized entry there -- only
        # when a tray icon actually exists to restore it from, so the
        # window can never become unreachable (e.g. no tray on this
        # platform/desktop environment).
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self._tray_icon is not None
            and QSystemTrayIcon.isSystemTrayAvailable()
        ):
            self._restore_maximized_from_tray = bool(self.windowState() & Qt.WindowState.WindowMaximized)
            # Deferred rather than calling self.hide() synchronously here:
            # this event fires *during* the window manager's own minimize
            # transition, and a reentrant hide() at that exact point loses
            # the race against it (confirmed directly -- the window stayed
            # visible even though hide() was called). Queuing it for the
            # next event-loop iteration lets the minimize finish first.
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def _notify(self, title: str, message: str, icon: QSystemTrayIcon.MessageIcon) -> None:
        """Best-effort native notification -- only actually shown if the
        tray icon itself is visible (nothing to anchor a notification to
        otherwise); never raises or blocks the caller."""
        if self._tray_icon is not None and self._tray_icon.isVisible():
            self._tray_icon.showMessage(title, message, icon, 8000)

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
        if self._tray_icon is not None:
            self._tray_icon.hide()
        self._spawn(self._perform_shutdown(), "завершение работы")

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
            # Before the database and clients go away underneath them.
            await self._cancel_background_tasks()
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
