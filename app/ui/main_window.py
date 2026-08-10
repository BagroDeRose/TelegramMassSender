"""Main application window: wires every layer together into the
account -> recipients -> message -> attachments -> interval -> start ->
progress flow (spec item 68), organized as clearly numbered sections so
the app is understandable without reading documentation.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from telethon.tl.types import TypeMessageEntity

from app.campaign.campaign_manager import CampaignManager
from app.campaign.campaign_state import CampaignStatus
from app.campaign.rate_limiter import RateLimiter
from app.config.paths import get_resource_path
from app.config.settings import SettingsValidationError
from app.database.database import Database
from app.logging.logger import get_logger
from app.recipients.validator import validate_single_recipient
from app.telegram.account_manager import Account
from app.telegram.exceptions import AccountSwitchBlockedError
from app.telegram.recipient_resolver import RecipientResolver
from app.telegram.sender import send_to_recipient
from app.telegram.service import TelegramService
from app.ui.account_widget import AccountWidget
from app.ui.attachments_widget import AttachmentsWidget
from app.ui.campaign_controls import CampaignControlsWidget
from app.ui.dialogs import confirm_delete_account, confirm_exit_during_campaign, show_error, show_test_send_result
from app.ui.log_widget import LogWidget
from app.ui.login_dialog import LoginDialog
from app.ui.message_editor_dialog import MessageEditorDialog
from app.ui.message_preview import MessagePreviewWidget
from app.ui.recipient_widget import RecipientWidget

WINDOW_TITLE = "Telegram Mass Sender"
_MIN_WINDOW_SIZE = (900, 700)


def _format_duration(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, int(total_seconds)), 60)
    if minutes:
        return f"{minutes} мин {seconds} сек"
    return f"{seconds} сек"


def _card(title: str, widget: QWidget) -> QGroupBox:
    box = QGroupBox(title)
    box.setObjectName("sectionCard")
    layout = QVBoxLayout(box)
    layout.addWidget(widget)
    return box


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
        # Set directly by _perform_shutdown() once cleanup is done, to
        # unblock main.py's loop.run_until_complete(close_event.wait()).
        # QApplication.quit() alone is NOT reliable here: this window's
        # close event is always ignore()'d (async cleanup must run first),
        # so the window never goes through Qt's normal close/accept path,
        # and aboutToQuit does not reliably fire on qasync's QEventLoop in
        # that situation -- confirmed by reproduction, see PR notes.
        self._close_event = close_event

        # database is injectable so tests don't have to touch the real
        # %APPDATA% database; app/main.py relies on the default.
        self._database = database if database is not None else Database()
        self._service = TelegramService(self._database)

        # Source of truth for the message: the inline preview is read-only,
        # actual editing happens in MessageEditorDialog (spec: large
        # messages need a real resizable editor, not a cramped inline box).
        self._message_text: str = ""
        self._message_entities: List[TypeMessageEntity] = []

        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1020, 900)
        self.setMinimumSize(*_MIN_WINDOW_SIZE)
        self._apply_theme()
        self._build_ui()
        self._wire_signals()

        settings = self._service.settings_repository.load_app_settings()
        self._campaign_controls.set_interval(settings.min_delay_seconds, settings.max_delay_seconds)

        self._update_message_preview()
        self.statusBar().showMessage("Готово")

        asyncio.ensure_future(self._refresh_accounts())

    # ---- UI construction ---------------------------------------------------

    def _apply_theme(self) -> None:
        qss_path = get_resource_path("assets", "styles", "dark.qss")
        try:
            self.setStyleSheet(qss_path.read_text(encoding="utf-8"))
        except OSError:
            self._logger.warning("Не удалось загрузить тему оформления: %s", qss_path)

    def _build_ui(self) -> None:
        self._account_widget = AccountWidget(self)
        self._recipient_widget = RecipientWidget(self)
        self._message_preview = MessagePreviewWidget(self)
        self._attachments_widget = AttachmentsWidget(self)
        self._campaign_controls = CampaignControlsWidget(self)
        self._log_widget = LogWidget(self)

        message_section = QWidget()
        message_layout = QVBoxLayout(message_section)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.addWidget(self._message_preview)

        message_buttons = QHBoxLayout()
        self._open_editor_button = QPushButton("✏ Открыть редактор", message_section)
        self._open_editor_button.setObjectName("primaryButton")
        self._open_editor_button.setToolTip("Полноразмерный редактор для длинных сообщений с форматированием")
        self._open_editor_button.clicked.connect(self._on_open_editor_clicked)
        message_buttons.addWidget(self._open_editor_button)
        message_buttons.addStretch(1)
        message_layout.addLayout(message_buttons)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(16)
        content_layout.addWidget(_card("1. Аккаунт", self._account_widget))
        content_layout.addWidget(_card("2. Получатели", self._recipient_widget))
        content_layout.addWidget(_card("3. Сообщение", message_section))
        content_layout.addWidget(_card("4. Вложения", self._attachments_widget))
        content_layout.addWidget(_card("5. Рассылка", self._campaign_controls))
        content_layout.addWidget(_card("Журнал", self._log_widget))
        content_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)

    def _wire_signals(self) -> None:
        self._account_widget.add_account_requested.connect(self._on_add_account_requested)
        self._account_widget.account_selected.connect(self._on_account_selected)
        self._account_widget.delete_account_requested.connect(self._on_delete_account_requested)

        self._recipient_widget.recipients_changed.connect(self._on_form_state_changed)
        self._attachments_widget.attachments_changed.connect(self._update_message_preview)

        self._campaign_controls.start_requested.connect(self._on_start_requested)
        self._campaign_controls.pause_requested.connect(self._on_pause_requested)
        self._campaign_controls.resume_requested.connect(self._on_resume_requested)
        self._campaign_controls.stop_requested.connect(self._on_stop_requested)
        self._campaign_controls.test_send_requested.connect(self._on_test_send_requested)

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
            return
        statuses = await account_manager.list_accounts_with_status()
        selected = select_id if select_id is not None else account_manager.active_account_id
        if selected is None and statuses:
            selected = statuses[0].account.id
        self._account_widget.set_accounts(statuses, selected)
        if selected is not None:
            try:
                account_manager.switch_active_account(selected)
            except AccountSwitchBlockedError:
                pass
        self._on_form_state_changed()

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
        account_manager = self._service.account_manager
        if account_manager is None:
            return
        try:
            account_manager.switch_active_account(account_id)
        except AccountSwitchBlockedError as exc:
            show_error(self, "Недоступно", str(exc))
            if account_manager.active_account_id is not None:
                self._account_widget.select_account(account_manager.active_account_id)
        self._on_form_state_changed()

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

        min_delay, max_delay = self._campaign_controls.get_interval()
        try:
            rate_limiter = RateLimiter(min_delay, max_delay)
        except SettingsValidationError as exc:
            show_error(self, "Интервал отправки", str(exc))
            return

        settings = self._service.settings_repository.load_app_settings()
        settings.min_delay_seconds = min_delay
        settings.max_delay_seconds = max_delay
        self._service.settings_repository.save_app_settings(settings)

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
                return
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            show_error(self, "Рассылка", f"Не удалось подключиться к Telegram: {exc}")
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
            # child of MainWindow (each Start/restart leaking one more dead
            # CampaignManager). Plain Python refcounting reclaims it as
            # soon as self._current_campaign is reassigned to the next one.
            parent=None,
        )
        self._current_campaign = campaign
        self._log_widget.clear()
        self._account_widget.set_enabled_switching(False)

        campaign.state_changed.connect(self._on_campaign_state_changed)
        campaign.progress_changed.connect(self._campaign_controls.update_progress)
        campaign.log_message.connect(self._log_widget.append)
        campaign.flood_wait_started.connect(self._on_flood_wait_started)
        campaign.flood_wait_tick.connect(self._on_flood_wait_tick)
        campaign.finished.connect(self._on_campaign_finished)

        campaign.start()
        self._campaign_controls.set_running_state(True, paused=False)
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
        elif status == CampaignStatus.STOPPED:
            self.statusBar().showMessage("Рассылка остановлена")
        elif status == CampaignStatus.ERROR:
            self.statusBar().showMessage("Рассылка остановлена из-за ошибки")
            show_error(
                self,
                "Рассылка остановлена",
                "Рассылка остановлена из-за критической ошибки аккаунта. Подробности см. в журнале.",
            )
        self._current_campaign = None
        self._on_form_state_changed()

    def _on_pause_requested(self) -> None:
        if self._current_campaign is not None:
            self._current_campaign.pause()

    def _on_resume_requested(self) -> None:
        if self._current_campaign is not None:
            self._current_campaign.resume()

    def _on_stop_requested(self) -> None:
        if self._current_campaign is not None:
            asyncio.ensure_future(self._current_campaign.stop())

    # ---- test send -----------------------------------------------------------

    def _on_test_send_requested(self, raw_recipient: str) -> None:
        if not raw_recipient:
            show_error(self, "Тестовая отправка", "Введите получателя для теста.")
            return
        account = self._active_account()
        if account is None:
            show_error(self, "Тестовая отправка", "Сначала выберите Telegram-аккаунт.")
            return

        parsed = validate_single_recipient(raw_recipient)
        if not parsed.is_valid:
            show_test_send_result(self, False, parsed.error or "Некорректный формат получателя")
            return

        text, entities = self._message_text, self._message_entities
        attachments = self._attachments_widget.get_attachments()
        missing = self._attachments_widget.missing_files()
        if missing:
            show_test_send_result(
                self, False, "Не найдены прикреплённые файлы: " + ", ".join(p.name for p in missing)
            )
            return

        asyncio.ensure_future(self._run_test_send(account, parsed, text, entities, attachments))

    async def _run_test_send(self, account, parsed, text, entities, attachments) -> None:
        account_manager = self._service.account_manager
        assert account_manager is not None
        try:
            client = await account_manager.ensure_connected(account)
            resolver = RecipientResolver(client)
            resolved = await resolver.resolve(parsed)
            if not resolved.is_ready:
                show_test_send_result(self, False, resolved.error or "Получатель недоступен")
                return
            await send_to_recipient(client, resolved.entity, text, entities, attachments)
            show_test_send_result(self, True)
            self._logger.info("Тестовое сообщение отправлено: %s", parsed.display_label)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self._logger.warning("Ошибка тестовой отправки: %s", exc)
            show_test_send_result(self, False, str(exc))

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

    async def _perform_shutdown(self) -> None:
        self._logger.info("Начинается корректное завершение работы приложения")
        try:
            if self._current_campaign is not None and self._current_campaign.is_active:
                await self._current_campaign.stop()
            await self._service.shutdown()
        finally:
            self._database.close()
            self._logger.info("Приложение завершает работу")
            self.hide()
            # Setting close_event directly is what actually unblocks
            # main.py's run_until_complete(close_event.wait()) -- see the
            # note in __init__. app.quit() is also called for good measure
            # (harmless if redundant) in case anything else is listening
            # on aboutToQuit, but it must never be the only mechanism relied
            # on to end the process.
            if self._close_event is not None:
                self._close_event.set()
            app = QApplication.instance()
            if app is not None:
                app.quit()
