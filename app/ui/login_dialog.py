"""Step-by-step Telegram account connection dialog.

Flow: API ID/API Hash + phone -> code from Telegram -> 2FA password (only
if the account has one enabled) -> success. Mirrors spec item 8. Runs
entirely on the shared qasync event loop -- button handlers schedule
coroutines with asyncio.ensure_future so the UI never blocks while
waiting on Telegram.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
)

from app.database.models import Account
from app.i18n import tr
from app.logging.logger import get_logger
from app.telegram.authentication import AuthenticatedUser, AuthenticationFlow
from app.telegram.service import TelegramService

logger = get_logger()

_PHONE_RE = re.compile(r"^\+\d{7,15}$")


class LoginDialog(QDialog):
    account_ready = Signal(object)  # emits app.database.models.Account

    def __init__(self, telegram_service: TelegramService, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = telegram_service
        self._flow: Optional[AuthenticationFlow] = None
        self._account: Optional[Account] = None

        self.setWindowTitle(tr("login_dialog.title"))
        self.setMinimumWidth(420)

        self._stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.addWidget(self._stack)

        self._build_connect_page()
        self._build_code_page()
        self._build_password_page()
        self._build_success_page()

    # ---- Page 0: API ID / API Hash / phone -----------------------------

    def _build_connect_page(self) -> None:
        page = QWidget(self)
        layout = QFormLayout(page)

        creds = self._service.secure_storage.load_api_credentials()

        self._api_id_edit = QLineEdit(page)
        self._api_id_edit.setPlaceholderText(tr("login_dialog.api_id_placeholder"))
        self._api_id_edit.setToolTip(tr("login_dialog.api_id_tooltip"))
        if creds is not None:
            self._api_id_edit.setText(str(creds.api_id))

        self._api_hash_edit = QLineEdit(page)
        self._api_hash_edit.setPlaceholderText(tr("login_dialog.api_hash_placeholder"))
        self._api_hash_edit.setToolTip(tr("login_dialog.api_hash_tooltip"))
        if creds is not None:
            self._api_hash_edit.setText(creds.api_hash)

        self._phone_edit = QLineEdit(page)
        self._phone_edit.setPlaceholderText(tr("login_dialog.phone_placeholder"))
        self._phone_edit.setToolTip(tr("login_dialog.phone_tooltip"))

        self._connect_error = QLabel(page)
        self._connect_error.setObjectName("dialogErrorLabel")
        self._connect_error.setWordWrap(True)

        layout.addRow(tr("login_dialog.api_id_label"), self._api_id_edit)
        layout.addRow(tr("login_dialog.api_hash_label"), self._api_hash_edit)
        layout.addRow(tr("login_dialog.phone_label"), self._phone_edit)
        layout.addRow(self._connect_error)

        self._connect_button = QPushButton(tr("login_dialog.connect_button"), page)
        self._connect_button.clicked.connect(self._on_connect_clicked)
        layout.addRow(self._connect_button)

        self._stack.addWidget(page)

    def _on_connect_clicked(self) -> None:
        asyncio.ensure_future(self._do_connect())

    async def _do_connect(self) -> None:
        self._connect_error.setText("")

        api_id_text = self._api_id_edit.text().strip()
        api_hash = self._api_hash_edit.text().strip()
        phone = self._phone_edit.text().strip()

        if not api_id_text.isdigit():
            self._connect_error.setText(tr("login_dialog.error.api_id_not_a_number"))
            return
        if not api_hash or len(api_hash) < 10:
            self._connect_error.setText(tr("login_dialog.error.invalid_api_hash"))
            return
        if not _PHONE_RE.match(phone):
            self._connect_error.setText(tr("login_dialog.error.invalid_phone_format"))
            return

        self._connect_button.setEnabled(False)
        try:
            self._service.configure_api_credentials(int(api_id_text), api_hash)
            account_manager = self._service.account_manager
            assert account_manager is not None
            self._account = account_manager.register_account(phone)
            client = account_manager.get_client(self._account)

            self._flow = AuthenticationFlow(client, phone)
            await self._flow.request_code()
        except PhoneNumberInvalidError:
            self._connect_error.setText(tr("login_dialog.error.invalid_phone"))
            return
        except FloodWaitError as exc:
            self._connect_error.setText(tr("login_dialog.error.flood_wait", seconds=exc.seconds))
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.warning("Ошибка подключения аккаунта: %s", exc)
            self._connect_error.setText(tr("login_dialog.error.connect_failed", error=exc))
            return
        finally:
            self._connect_button.setEnabled(True)

        self._code_error.setText("")
        self._code_edit.clear()
        self._stack.setCurrentIndex(1)

    # ---- Page 1: confirmation code --------------------------------------

    def _build_code_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(tr("login_dialog.code_label"), page))
        self._code_edit = QLineEdit(page)
        layout.addWidget(self._code_edit)

        self._code_error = QLabel(page)
        self._code_error.setObjectName("dialogErrorLabel")
        self._code_error.setWordWrap(True)
        layout.addWidget(self._code_error)

        self._code_button = QPushButton(tr("login_dialog.confirm_button"), page)
        self._code_button.clicked.connect(self._on_code_clicked)
        layout.addWidget(self._code_button)

        self._stack.addWidget(page)

    def _on_code_clicked(self) -> None:
        asyncio.ensure_future(self._do_submit_code())

    async def _do_submit_code(self) -> None:
        assert self._flow is not None
        code = self._code_edit.text().strip()
        if not code:
            self._code_error.setText(tr("login_dialog.error.code_required"))
            return

        self._code_button.setEnabled(False)
        try:
            user = await self._flow.submit_code(code)
        except PhoneCodeInvalidError:
            self._code_error.setText(tr("login_dialog.error.invalid_code"))
            return
        except PhoneCodeExpiredError:
            self._code_error.setText(tr("login_dialog.error.code_expired"))
            return
        except FloodWaitError as exc:
            self._code_error.setText(tr("login_dialog.error.flood_wait", seconds=exc.seconds))
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ошибка ввода кода: %s", exc)
            self._code_error.setText(tr("login_dialog.error.code_confirm_failed", error=exc))
            return
        finally:
            self._code_button.setEnabled(True)

        if user is None:
            self._password_error.setText("")
            self._password_edit.clear()
            self._stack.setCurrentIndex(2)
        else:
            self._on_authenticated(user)

    # ---- Page 2: 2FA password --------------------------------------------

    def _build_password_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(tr("login_dialog.password_label"), page))
        self._password_edit = QLineEdit(page)
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._password_edit)

        self._password_error = QLabel(page)
        self._password_error.setObjectName("dialogErrorLabel")
        self._password_error.setWordWrap(True)
        layout.addWidget(self._password_error)

        self._password_button = QPushButton(tr("login_dialog.confirm_button"), page)
        self._password_button.clicked.connect(self._on_password_clicked)
        layout.addWidget(self._password_button)

        self._stack.addWidget(page)

    def _on_password_clicked(self) -> None:
        asyncio.ensure_future(self._do_submit_password())

    async def _do_submit_password(self) -> None:
        assert self._flow is not None
        password = self._password_edit.text()
        if not password:
            self._password_error.setText(tr("login_dialog.error.password_required"))
            return

        self._password_button.setEnabled(False)
        try:
            user = await self._flow.submit_password(password)
        except PasswordHashInvalidError:
            self._password_error.setText(tr("login_dialog.error.invalid_password"))
            return
        except FloodWaitError as exc:
            self._password_error.setText(tr("login_dialog.error.flood_wait", seconds=exc.seconds))
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ошибка ввода пароля 2FA: %s", exc)
            self._password_error.setText(tr("login_dialog.error.password_confirm_failed", error=exc))
            return
        finally:
            self._password_button.setEnabled(True)
            # The password itself is discarded here; it is never stored or logged.
            self._password_edit.clear()

        self._on_authenticated(user)

    # ---- Page 3: success ---------------------------------------------------

    def _build_success_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(tr("login_dialog.success_title"), page))

        self._success_phone = QLabel(page)
        self._success_name = QLabel(page)
        self._success_username = QLabel(page)
        layout.addWidget(self._success_phone)
        layout.addWidget(self._success_name)
        layout.addWidget(self._success_username)

        done_button = QPushButton(tr("login_dialog.done_button"), page)
        done_button.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(done_button)
        layout.addLayout(row)

        self._stack.addWidget(page)

    def _on_authenticated(self, user: AuthenticatedUser) -> None:
        assert self._account is not None
        account_manager = self._service.account_manager
        assert account_manager is not None
        refreshed = account_manager.update_profile(
            self._account, user.telegram_user_id, user.username, user.display_name
        )
        self._account = refreshed

        self._success_phone.setText(tr("login_dialog.summary_account", phone=refreshed.phone))
        self._success_name.setText(tr("login_dialog.summary_name", name=refreshed.display_name or "-"))
        self._success_username.setText(
            tr("login_dialog.summary_username", username=refreshed.username)
            if refreshed.username
            else tr("login_dialog.summary_username_none")
        )
        self._stack.setCurrentIndex(3)
        self.account_ready.emit(refreshed)
