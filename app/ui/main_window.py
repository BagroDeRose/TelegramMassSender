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
from typing import List, Optional

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
from app.campaign import report_library
from app.config.paths import get_reports_dir
from app.config.settings import (
    MAX_ALLOWED_DELAY_SECONDS,
    MIN_ALLOWED_DELAY_SECONDS,
    AppSettings,
    SettingsValidationError,
)
from app.database.database import Database
from app.database.models import SavedReport
from app.database.repositories import SavedReportRepository
from app.logging.logger import get_logger
from app.telegram.account_manager import Account
from app.telegram.exceptions import AccountSwitchBlockedError
from app.telegram.service import TelegramService
from app.ui import theme
from app.ui.account_widget import AccountWidget
from app.ui.attachments_widget import AttachmentsWidget
from app.ui.campaign_controls import CampaignControlsWidget
from app.ui.dialogs import (
    confirm_delete_account,
    confirm_exit_during_campaign,
    confirm_reset_settings,
    confirm_start_campaign,
    show_error,
    show_info,
)
from app.ui.empty_state import build_empty_state
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


def _format_duration(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, int(total_seconds)), 60)
    if minutes:
        return f"{minutes} мин {seconds} сек"
    return f"{seconds} сек"


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
        self._apply_theme()
        self._build_ui()
        self._wire_signals()

        self._campaign_controls.set_interval_summary(settings.min_delay_seconds, settings.max_delay_seconds)
        self._theme_combo.blockSignals(True)
        combo_index = self._theme_combo.findData(theme.get_active_theme())
        self._theme_combo.setCurrentIndex(max(0, combo_index))
        self._theme_combo.blockSignals(False)
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
        self.statusBar().showMessage("Готово")

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

        self._connection_status_label = QLabel("Нет подключённого аккаунта", self)
        self._connection_status_label.setObjectName("connectionStatusLabel")
        self.statusBar().addPermanentWidget(self._connection_status_label)

        self._journal_toggle_button = QToolButton(self)
        self._journal_toggle_button.setObjectName("toolbarButton")
        self._journal_toggle_button.setText("Журнал")
        self._journal_toggle_button.setCheckable(True)
        self._journal_toggle_button.setToolTip("Показать/скрыть журнал")
        self.statusBar().addPermanentWidget(self._journal_toggle_button)

    def _build_campaign_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SPACE_XXL, SPACE_XXL, SPACE_XXL, SPACE_XXL)
        layout.setSpacing(SPACE_LG)

        layout.addWidget(_page_header("Кампания", "Создайте и запустите рассылку в Telegram"))

        self._recipient_count_label = QLabel("0", page)
        self._recipient_count_label.setObjectName("cardCount")
        layout.addWidget(_card("Получатели", self._recipient_widget, self._recipient_count_label))

        message_section = QWidget()
        message_layout = QVBoxLayout(message_section)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(SPACE_SM)
        message_layout.addWidget(self._message_preview)

        message_buttons = QHBoxLayout()
        self._open_editor_button = QPushButton("✏  Открыть редактор", message_section)
        self._open_editor_button.setToolTip("Полноразмерный редактор для длинных сообщений с форматированием")
        self._open_editor_button.clicked.connect(self._on_open_editor_clicked)
        message_buttons.addWidget(self._open_editor_button)
        message_buttons.addStretch(1)
        message_layout.addLayout(message_buttons)

        name_hint = QLabel("{name} — имя получателя в Telegram, подставляется при отправке", message_section)
        name_hint.setObjectName("helperText")
        message_layout.addWidget(name_hint)

        layout.addWidget(_card("Сообщение", message_section))
        layout.addWidget(_card("Вложения", self._attachments_widget))
        layout.addWidget(_card("Рассылка", self._campaign_controls))
        layout.addStretch(1)
        return page

    def _build_accounts_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SPACE_XXL, SPACE_XXL, SPACE_XXL, SPACE_XXL)
        layout.setSpacing(SPACE_LG)
        layout.addWidget(_page_header("Аккаунты", "Подключённые Telegram-аккаунты"))
        layout.addWidget(self._account_widget)
        layout.addStretch(1)
        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SPACE_XXL, SPACE_XXL, SPACE_XXL, SPACE_XXL)
        layout.setSpacing(SPACE_LG)
        layout.addWidget(_page_header("Результаты", "Статистика текущей рассылки и сохранённые отчёты"))

        self._results_empty_label = build_empty_state(
            "Нет данных о рассылке",
            "Запустите рассылку на странице «Кампания», чтобы увидеть статистику здесь.",
            page,
        )
        layout.addWidget(self._results_empty_label)

        self._results_status_label = QLabel("", page)
        self._results_status_label.setObjectName("statusLabel")
        layout.addWidget(self._results_status_label)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(SPACE_MD)
        self._stat_total = StatCard("Всего")
        self._stat_success = StatCard("Успешно", variant="success")
        self._stat_failed = StatCard("Ошибок", variant="error")
        self._stat_skipped = StatCard("Пропущено", variant="warning")
        for card in (self._stat_total, self._stat_success, self._stat_failed, self._stat_skipped):
            stats_row.addWidget(card, 1)
        self._results_stats_widget = QWidget(page)
        self._results_stats_widget.setLayout(stats_row)
        layout.addWidget(self._results_stats_widget)

        export_row = QHBoxLayout()
        self._results_export_button = QPushButton("Экспорт CSV-отчёта", page)
        self._results_export_button.setObjectName("primaryButton")
        self._results_export_button.setEnabled(False)
        self._results_export_button.clicked.connect(self._on_export_report_requested)
        self._save_report_button = QPushButton("Сохранить отчёт", page)
        self._save_report_button.setEnabled(False)
        self._save_report_button.clicked.connect(self._on_save_report_clicked)
        export_row.addWidget(self._results_export_button)
        export_row.addWidget(self._save_report_button)
        export_row.addStretch(1)
        layout.addLayout(export_row)

        layout.addWidget(_section_title("Сохранённые отчёты"))
        self._saved_reports_empty_label = build_empty_state(
            "Нет сохранённых отчётов", "Сохраните отчёт о рассылке, чтобы найти его здесь позже.", page
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
        layout.addWidget(_page_header("Настройки", "Параметры приложения"))

        layout.addWidget(_card("Внешний вид", self._build_appearance_settings()))
        layout.addWidget(_card("Отправка", self._build_sending_settings()))
        layout.addWidget(_card("Приложение", self._build_application_settings()))
        layout.addWidget(_card("Отчёты", self._build_reports_settings()))
        layout.addWidget(_card("Дополнительно", self._build_advanced_settings()))
        layout.addStretch(1)
        return page

    def _build_appearance_settings(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        layout.addWidget(QLabel("Тема оформления", widget))
        self._theme_combo = QComboBox(widget)
        for value in theme.VALID_THEMES:
            self._theme_combo.addItem(theme.THEME_LABELS[value], value)
        self._theme_combo.setMaximumWidth(220)
        layout.addWidget(self._theme_combo)
        help_label = QLabel("Выбор темы сохраняется и восстанавливается при следующем запуске", widget)
        help_label.setObjectName("helperText")
        layout.addWidget(help_label)
        return widget

    def _build_sending_settings(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        layout.addWidget(QLabel("Интервал отправки, сек", widget))
        interval_row = QHBoxLayout()
        interval_row.setSpacing(SPACE_SM)
        self._settings_min_spin = QSpinBox(widget)
        self._settings_min_spin.setRange(MIN_ALLOWED_DELAY_SECONDS, MAX_ALLOWED_DELAY_SECONDS)
        self._settings_max_spin = QSpinBox(widget)
        self._settings_max_spin.setRange(MIN_ALLOWED_DELAY_SECONDS, MAX_ALLOWED_DELAY_SECONDS)
        interval_row.addWidget(self._settings_min_spin)
        interval_row.addWidget(QLabel("—", widget))
        interval_row.addWidget(self._settings_max_spin)
        interval_row.addStretch(1)
        layout.addLayout(interval_row)
        interval_help = QLabel(
            "Случайная пауза перед отправкой каждому следующему получателю. "
            "Снижает интенсивность работы программы, но не гарантирует "
            "отсутствие ограничений со стороны Telegram.",
            widget,
        )
        interval_help.setObjectName("helperText")
        interval_help.setWordWrap(True)
        layout.addWidget(interval_help)
        self._settings_min_spin.editingFinished.connect(self._on_interval_settings_changed)
        self._settings_max_spin.editingFinished.connect(self._on_interval_settings_changed)

        self._confirm_before_start_checkbox = QCheckBox("Подтверждать запуск рассылки", widget)
        self._confirm_before_start_checkbox.setToolTip(
            "Показывать диалог подтверждения перед стартом каждой рассылки"
        )
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

        self._remember_window_checkbox = QCheckBox("Запоминать размер окна", widget)
        self._remember_window_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("remember_window_size", checked)
        )
        layout.addWidget(self._remember_window_checkbox)

        self._remember_page_checkbox = QCheckBox("Открывать последний раздел при запуске", widget)
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

        layout.addWidget(QLabel("Папка для отчётов", widget))
        dir_row = QHBoxLayout()
        dir_row.setSpacing(SPACE_SM)
        self._reports_dir_edit = QLineEdit(widget)
        self._reports_dir_edit.setPlaceholderText(str(get_reports_dir()))
        self._reports_dir_edit.setReadOnly(True)
        browse_button = QPushButton("Обзор…", widget)
        browse_button.clicked.connect(self._on_browse_reports_directory)
        reset_dir_button = QPushButton("По умолчанию", widget)
        reset_dir_button.setObjectName("ghostButton")
        reset_dir_button.clicked.connect(self._on_reset_reports_directory)
        dir_row.addWidget(self._reports_dir_edit, 1)
        dir_row.addWidget(browse_button)
        dir_row.addWidget(reset_dir_button)
        layout.addLayout(dir_row)

        self._auto_save_reports_checkbox = QCheckBox("Автоматически сохранять отчёт после рассылки", widget)
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

        self._debug_logging_checkbox = QCheckBox("Расширенное логирование (для диагностики)", widget)
        self._debug_logging_checkbox.toggled.connect(
            lambda checked: self._save_setting_field("debug_logging", checked)
        )
        layout.addWidget(self._debug_logging_checkbox)

        reset_row = QHBoxLayout()
        reset_button = QPushButton("Сбросить настройки приложения", widget)
        reset_button.setObjectName("dangerButton")
        reset_button.clicked.connect(self._on_reset_settings_clicked)
        reset_row.addWidget(reset_button)
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
            show_error(self, "Интервал отправки", str(exc))
            self._settings_min_spin.setValue(settings.min_delay_seconds)
            self._settings_max_spin.setValue(settings.max_delay_seconds)
            return
        self._campaign_controls.set_interval_summary(min_delay, max_delay)

    def _on_browse_reports_directory(self) -> None:
        current = self._reports_dir_edit.text() or str(get_reports_dir())
        chosen = QFileDialog.getExistingDirectory(self, "Папка для отчётов", current)
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
        defaults.theme = theme.get_active_theme()  # theme reset is handled via its own control, not silently flipped
        self._service.settings_repository.save_app_settings(defaults)
        self._load_settings_into_page(defaults)
        self._campaign_controls.set_interval_summary(defaults.min_delay_seconds, defaults.max_delay_seconds)
        show_info(self, "Настройки", "Настройки приложения сброшены к значениям по умолчанию.")

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
        self._message_preview.update_preview(self._message_text, self._message_entities, attachment_names)
        self._on_form_state_changed()

    def _on_recipients_changed(self, summary) -> None:
        self._recipient_count_label.setText(str(len(summary.valid_recipients)))

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
            dot_color, text = tokens.text_muted, "Нет подключённого аккаунта"
        else:
            account = self._active_account()
            label = f"@{account.username}" if account.username else account.phone
            dot_color, text = tokens.success, f"Подключён: {label}"
        self._connection_status_label.setText(f'<span style="color:{dot_color};">●</span>&nbsp;&nbsp;{text}')

    def _on_add_account_requested(self) -> None:
        if not self._can_switch_accounts():
            show_error(self, "Недоступно", "Добавление аккаунта недоступно во время рассылки.")
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
            show_error(self, "Недоступно", str(exc))
            self._account_widget.refresh_active_state(previous_active_id)
            self._account_switch_in_progress = False
            return
        except Exception as exc:  # noqa: BLE001 - surfaced as a friendly message, logged for detail
            self._logger.warning("Не удалось переключить аккаунт %s: %s", account_id, exc)
            show_error(
                self,
                "Переключение аккаунта",
                "Не удалось переключить аккаунт.\nПроверьте подключение и состояние сессии.",
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
            show_error(self, "Недоступно", "Удаление аккаунта недоступно во время рассылки.")
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
            show_error(self, "Рассылка", "Для этого аккаунта уже выполняется рассылка.")
            return

        account = self._active_account()
        if account is None:
            show_error(self, "Рассылка", "Сначала подключите и выберите Telegram-аккаунт.")
            return

        self._recipient_widget.flush()
        recipients = self._recipient_widget.valid_recipients()
        if not recipients:
            show_error(self, "Рассылка", "Список получателей пуст или не содержит корректных значений.")
            return

        text, entities = self._message_text, self._message_entities
        attachments = self._attachments_widget.get_attachments()
        missing = self._attachments_widget.missing_files()
        if missing:
            names = ", ".join(p.name for p in missing)
            show_error(self, "Рассылка", f"Не найдены прикреплённые файлы: {names}")
            return
        if not text.strip() and not attachments:
            show_error(self, "Рассылка", "Введите текст сообщения или добавьте вложение.")
            return

        settings = self._service.settings_repository.load_app_settings()
        if settings.confirm_before_start and not confirm_start_campaign(self, len(recipients)):
            return

        try:
            rate_limiter = RateLimiter(settings.min_delay_seconds, settings.max_delay_seconds)
        except SettingsValidationError as exc:
            show_error(self, "Интервал отправки", str(exc))
            return

        # Set synchronously, before scheduling the coroutine: two clicks
        # arriving back-to-back (before the event loop ever runs
        # _start_campaign, e.g. while ensure_connected's network round-trip
        # is still pending) must both see this guard, not just the second
        # one to actually start executing -- see _switch_account for the
        # same pattern applied to account switching.
        self._campaign_starting = True
        asyncio.ensure_future(
            self._start_campaign(account, recipients, text, entities, attachments, rate_limiter, settings.retry_count)
        )

    async def _start_campaign(
        self, account, recipients, text, entities, attachments, rate_limiter, retry_count
    ) -> None:
        account_manager = self._service.account_manager
        assert account_manager is not None
        try:
            client = await account_manager.ensure_connected(account)
            if not await client.is_user_authorized():
                show_error(self, "Рассылка", "Аккаунт не авторизован. Подключите аккаунт заново.")
                self._campaign_starting = False
                return
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            show_error(self, "Рассылка", f"Не удалось подключиться к Telegram: {exc}")
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
            # No Qt parent on purpose: with parent=self, Qt's ownership
            # hierarchy would keep every past campaign alive forever as a
            # child of MainWindow. Plain Python refcounting reclaims it as
            # soon as self._current_campaign is reassigned to the next one.
            parent=None,
        )
        self._current_campaign = campaign
        self._campaign_starting = False
        self._report_source = campaign
        self._campaign_controls.set_report_available(True)
        self._results_export_button.setEnabled(True)
        self._save_report_button.setEnabled(True)
        self._journal.clear()
        self._account_widget.set_enabled_switching(False)

        campaign.state_changed.connect(self._on_campaign_state_changed)
        campaign.progress_changed.connect(self._campaign_controls.update_progress)
        campaign.progress_changed.connect(self._update_results_stats)
        campaign.log_message.connect(self._journal.append)
        campaign.flood_wait_started.connect(self._on_flood_wait_started)
        campaign.flood_wait_tick.connect(self._on_flood_wait_tick)
        campaign.finished.connect(self._on_campaign_finished)

        campaign.start()
        self._campaign_controls.set_running_state(True, paused=False)
        self._results_status_label.setText("Рассылка выполняется…")
        self._update_results_page()
        self.statusBar().showMessage("Рассылка выполняется…")

    def _on_campaign_state_changed(self, status_value: str) -> None:
        status = CampaignStatus(status_value)
        if status == CampaignStatus.RUNNING:
            self._campaign_controls.set_running_state(True, paused=False)
            self._campaign_controls.set_status_text("")
            self.statusBar().showMessage("Рассылка выполняется…")
        elif status == CampaignStatus.PAUSED:
            self._campaign_controls.set_running_state(True, paused=True)
            self.statusBar().showMessage("Рассылка на паузе")
        elif status == CampaignStatus.WAITING_FOR_FLOOD:
            self._campaign_controls.set_running_state(True, paused=True)
            self.statusBar().showMessage("Ожидание ограничения Telegram…")

    def _on_flood_wait_started(self, seconds: int) -> None:
        self._campaign_controls.set_status_text(
            f"Telegram временно ограничил отправку. Необходимо подождать: {_format_duration(seconds)}"
        )

    def _on_flood_wait_tick(self, remaining: int) -> None:
        self._campaign_controls.set_status_text(
            f"Ожидание окончания ограничения Telegram: {_format_duration(remaining)}"
        )

    def _on_campaign_finished(self, status_value: str) -> None:
        self._campaign_controls.set_running_state(False)
        self._campaign_controls.set_status_text("")
        self._account_widget.set_enabled_switching(True)
        status = CampaignStatus(status_value)
        if status == CampaignStatus.COMPLETED:
            self.statusBar().showMessage("Рассылка завершена")
            self._results_status_label.setText("✓ Рассылка завершена")
        elif status == CampaignStatus.STOPPED:
            self.statusBar().showMessage("Рассылка остановлена")
            self._results_status_label.setText("■ Рассылка остановлена")
        elif status == CampaignStatus.ERROR:
            self.statusBar().showMessage("Рассылка остановлена из-за ошибки")
            self._results_status_label.setText("! Рассылка остановлена из-за критической ошибки")
            show_error(
                self,
                "Рассылка остановлена",
                "Рассылка остановлена из-за критической ошибки аккаунта. Подробности см. в журнале.",
            )
        self._current_campaign = None
        self._on_form_state_changed()

        settings = self._service.settings_repository.load_app_settings()
        if settings.auto_save_reports and self._report_source is not None and self._report_source.items:
            self._auto_save_report()

    def _auto_save_report(self) -> None:
        if self._report_source is None:
            return
        snapshot = self._report_source.snapshot()
        name = f"Рассылка {datetime.now():%Y-%m-%d %H:%M}"
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

    def _update_results_stats(self, snapshot: ProgressSnapshot) -> None:
        self._results_empty_label.setVisible(False)
        self._results_stats_widget.setVisible(True)
        self._stat_total.set_value(snapshot.total)
        self._stat_success.set_value(snapshot.sent)
        self._stat_failed.set_value(snapshot.failed)
        self._stat_skipped.set_value(snapshot.skipped)

    def _on_save_report_clicked(self) -> None:
        if self._report_source is None or not self._report_source.items:
            return
        default_name = f"Рассылка {datetime.now():%Y-%m-%d %H:%M}"
        name, ok = QInputDialog.getText(self, "Сохранить отчёт", "Название:", text=default_name)
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
            show_error(self, "Сохранение отчёта", f"Не удалось сохранить отчёт: {exc}")
            return
        self._refresh_saved_reports()
        show_info(self, "Отчёт сохранён", f"Отчёт «{name}» добавлен в сохранённые отчёты.")

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
        favorite_button.setText("★" if report.is_favorite else "☆")
        favorite_button.setProperty("active", "true" if report.is_favorite else "false")
        favorite_button.setToolTip("Избранное")
        favorite_button.clicked.connect(lambda: self._on_toggle_favorite(report))
        header.addWidget(favorite_button)
        name_label = QLabel(report.name, card)
        name_label.setObjectName("reportName")
        header.addWidget(name_label, 1)
        layout.addLayout(header)

        meta = QLabel(
            f"{report.total} получателей · {report.successful} успешно · {report.failed} ошибок",
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
        open_button = QPushButton("Открыть", card)
        open_button.setObjectName("ghostButton")
        open_button.clicked.connect(lambda: self._on_open_saved_report(report))
        export_button = QPushButton("Экспорт", card)
        export_button.setObjectName("ghostButton")
        export_button.clicked.connect(lambda: self._on_export_saved_report(report))
        actions.addWidget(open_button)
        actions.addWidget(export_button)

        more_button = QPushButton("⋯", card)
        more_button.setObjectName("ghostButton")
        more_button.setToolTip("Ещё")
        more_menu = QMenu(more_button)
        rename_action = more_menu.addAction("Переименовать")
        rename_action.triggered.connect(lambda: self._on_rename_saved_report(report))
        delete_action = more_menu.addAction("Удалить")
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
            show_error(self, "Отчёт", f"Файл отчёта не найден: {path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_export_saved_report(self, report: SavedReport) -> None:
        default_name = Path(report.file_path).name
        path_str, _ = QFileDialog.getSaveFileName(self, "Экспорт отчёта", default_name, "CSV файлы (*.csv)")
        if not path_str:
            return
        try:
            report_library.export_report(report, Path(path_str))
        except (ReportFileMissingError, OSError) as exc:
            show_error(self, "Экспорт отчёта", str(exc))
            return
        show_info(self, "Экспорт отчёта", f"Отчёт сохранён: {path_str}")

    def _on_rename_saved_report(self, report: SavedReport) -> None:
        new_name, ok = QInputDialog.getText(self, "Переименовать отчёт", "Название:", text=report.name)
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
            self, "Экспорт отчёта", suggest_report_filename(), "CSV файлы (*.csv)"
        )
        if not path_str:
            return
        try:
            write_csv_report(self._report_source.items, Path(path_str))
        except OSError as exc:
            show_error(self, "Экспорт отчёта", f"Не удалось сохранить файл: {exc}")
            return
        show_info(self, "Экспорт отчёта", f"Отчёт сохранён: {path_str}")

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
