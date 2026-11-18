"""Step-by-step Telegram account connection dialog.

Flow: API ID/API Hash + phone -> code from Telegram -> 2FA password (only
if the account has one enabled) -> success; or, from the first page or the
code page, a QR code scanned with Telegram on the phone -> 2FA password if
any -> success. Mirrors spec item 8. Runs entirely on the shared qasync
event loop -- button handlers schedule coroutines with
asyncio.ensure_future so the UI never blocks while waiting on Telegram.

The code page says where Telegram actually sent the code (app, SMS, call,
email, Fragment -- app.telegram.authentication.describe_sent_code) and
offers Telegram's own resend once its timeout has passed. QR login exists
because Telegram has been silently not delivering codes to third-party
clients for some accounts (see app.telegram.authentication).

The QR coroutine is the one task here that runs on its own for minutes:
it is held in ``_qr_task`` and cancelled whenever the QR page is left or
the dialog closes (``done``), so a closed dialog never keeps requesting
login tokens. Like the other coroutines here it catches everything except
cancellation itself and writes the failure into the page's error label.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
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
    PhoneNumberBannedError,
    PhoneNumberFloodError,
    PhoneNumberInvalidError,
    SendCodeUnavailableError,
)

from app.database.models import Account
from app.i18n import tr
from app.ui.dialog_frame import build_dialog_frame
from app.ui.qr_code import qr_pixmap
from app.ui.theme import DIALOG_WIDTH
from app.ui.theme.tokens import QR_IMAGE_SIZE
from app.logging.logger import get_logger
from app.telegram.authentication import (
    UNUSABLE_CHANNELS,
    AuthenticatedUser,
    AuthenticationFlow,
    CodeChannel,
    CodeDelivery,
    QrLoginExpiredError,
)
from app.telegram.exceptions import AccountAlreadyAddedError
from app.telegram.service import TelegramService

logger = get_logger()

_PHONE_RE = re.compile(r"^\+\d{7,15}$")

PAGE_CONNECT = 0
PAGE_CODE = 1
PAGE_PASSWORD = 2
PAGE_SUCCESS = 3
PAGE_QR = 4

_RESEND_TICK_MS = 1000

# The ways Telegram can name for a resend (auth.CodeType*), each with its
# own "a resent code will come ..." sentence.
_NEXT_SENTENCES = frozenset(
    {CodeChannel.SMS, CodeChannel.CALL, CodeChannel.FLASH_CALL, CodeChannel.MISSED_CALL, CodeChannel.FRAGMENT}
)


def describe_delivery(delivery: CodeDelivery, phone: str) -> str:
    """The code page's "where did the code go" line."""
    channel = delivery.channel
    if channel == CodeChannel.EMAIL:
        text = tr("login_dialog.code_sent.email", email=delivery.email_pattern or "-")
    elif channel == CodeChannel.FRAGMENT:
        text = tr("login_dialog.code_sent.fragment", url=delivery.fragment_url or "fragment.com")
    elif channel == CodeChannel.MISSED_CALL:
        text = tr("login_dialog.code_sent.missed_call", phone=phone, length=delivery.length or "-")
    elif channel in (CodeChannel.SMS, CodeChannel.CALL, CodeChannel.FLASH_CALL):
        text = tr(f"login_dialog.code_sent.{channel.value}", phone=phone)
    else:
        text = tr(f"login_dialog.code_sent.{channel.value}")
    if delivery.next_channel is not None and channel not in UNUSABLE_CHANNELS:
        next_channel = delivery.next_channel if delivery.next_channel in _NEXT_SENTENCES else CodeChannel.UNKNOWN
        text += " " + tr(f"login_dialog.code_next.{next_channel.value}")
    return text


class LoginDialog(QDialog):
    account_ready = Signal(object)  # emits app.database.models.Account

    def __init__(self, telegram_service: TelegramService, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = telegram_service
        self._flow: Optional[AuthenticationFlow] = None
        self._account: Optional[Account] = None
        self._qr_task: Optional[asyncio.Future] = None
        self._qr_return_page = PAGE_CONNECT
        self._resend_seconds_left = 0
        self._resend_available = False

        self.setWindowTitle(tr("login_dialog.title"))
        self.setMinimumWidth(DIALOG_WIDTH)

        frame = build_dialog_frame(self, tr("login_dialog.title"))
        frame.footer.setVisible(False)  # each step carries its own action
        self._stack = QStackedWidget(self)
        frame.content.addWidget(self._stack)

        self._resend_timer = QTimer(self)
        self._resend_timer.setInterval(_RESEND_TICK_MS)
        self._resend_timer.timeout.connect(self._on_resend_tick)

        self._build_connect_page()
        self._build_code_page()
        self._build_password_page()
        self._build_success_page()
        self._build_qr_page()

    @staticmethod
    def _error_label(parent: QWidget) -> QLabel:
        label = QLabel(parent)
        label.setObjectName("dialogErrorLabel")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _helper_label(text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setObjectName("helperText")
        label.setWordWrap(True)
        return label

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

        self._connect_error = self._error_label(page)

        layout.addRow(tr("login_dialog.api_id_label"), self._api_id_edit)
        layout.addRow(tr("login_dialog.api_hash_label"), self._api_hash_edit)
        layout.addRow(tr("login_dialog.phone_label"), self._phone_edit)
        layout.addRow(self._connect_error)

        self._connect_button = QPushButton(tr("login_dialog.connect_button"), page)
        self._connect_button.setProperty("variant", "primary")
        self._connect_button.clicked.connect(self._on_connect_clicked)
        self._connect_qr_button = QPushButton(tr("login_dialog.qr_button"), page)
        self._connect_qr_button.clicked.connect(self._on_connect_qr_clicked)
        row = QHBoxLayout()
        row.addWidget(self._connect_qr_button)
        row.addStretch(1)
        row.addWidget(self._connect_button)
        layout.addRow(row)
        layout.addRow(self._helper_label(tr("login_dialog.qr_hint"), page))

        self._stack.addWidget(page)

    def _prepare_flow(self) -> bool:
        """Validate page 0 and set up the attempt's account, client and
        flow. Synchronous; a False return has already written the reason
        into the page's error label. Reuses the existing flow while the
        phone is unchanged, so a second request on the same client is
        Telegram's resend rather than a fresh code."""
        self._connect_error.setText("")
        api_id_text = self._api_id_edit.text().strip()
        api_hash = self._api_hash_edit.text().strip()
        phone = self._phone_edit.text().strip()

        if not api_id_text.isdigit():
            self._connect_error.setText(tr("login_dialog.error.api_id_not_a_number"))
            return False
        if not api_hash or len(api_hash) < 10:
            self._connect_error.setText(tr("login_dialog.error.invalid_api_hash"))
            return False
        if not _PHONE_RE.match(phone):
            self._connect_error.setText(tr("login_dialog.error.invalid_phone_format"))
            return False

        if self._flow is not None and self._account is not None and self._account.phone == phone:
            return True
        self._service.configure_api_credentials(int(api_id_text), api_hash)
        account_manager = self._service.account_manager
        assert account_manager is not None
        self._account = account_manager.register_account(phone)
        client = account_manager.get_client(self._account)
        self._flow = AuthenticationFlow(client, phone)
        return True

    def _set_connect_busy(self, busy: bool) -> None:
        self._connect_button.setEnabled(not busy)
        self._connect_qr_button.setEnabled(not busy)

    def _on_connect_clicked(self) -> None:
        asyncio.ensure_future(self._do_connect())

    async def _do_connect(self) -> None:
        self._set_connect_busy(True)
        try:
            if not self._prepare_flow():
                return
            assert self._flow is not None
            delivery = await self._flow.request_code()
        except PhoneNumberInvalidError:
            self._connect_error.setText(tr("login_dialog.error.invalid_phone"))
            return
        except PhoneNumberBannedError:
            self._connect_error.setText(tr("login_dialog.error.phone_banned"))
            return
        except PhoneNumberFloodError:
            self._connect_error.setText(tr("login_dialog.error.phone_flood"))
            return
        except FloodWaitError as exc:
            self._connect_error.setText(tr("login_dialog.error.flood_wait", seconds=exc.seconds))
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.warning("Ошибка подключения аккаунта: %s", exc)
            self._connect_error.setText(tr("login_dialog.error.connect_failed", error=exc))
            return
        finally:
            self._set_connect_busy(False)

        self._code_error.setText("")
        self._code_edit.clear()
        self._show_delivery(delivery)
        self._stack.setCurrentIndex(PAGE_CODE)

    def _on_connect_qr_clicked(self) -> None:
        try:
            prepared = self._prepare_flow()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.warning("Ошибка подключения аккаунта: %s", exc)
            self._connect_error.setText(tr("login_dialog.error.connect_failed", error=exc))
            return
        if prepared:
            self._start_qr(return_page=PAGE_CONNECT)

    # ---- Page 1: confirmation code --------------------------------------

    def _build_code_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)

        self._code_delivery = QLabel(page)
        self._code_delivery.setWordWrap(True)
        self._code_delivery.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._code_delivery)

        layout.addWidget(QLabel(tr("login_dialog.code_label"), page))
        self._code_edit = QLineEdit(page)
        layout.addWidget(self._code_edit)

        self._code_error = self._error_label(page)
        layout.addWidget(self._code_error)

        self._code_button = QPushButton(tr("login_dialog.confirm_button"), page)
        self._code_button.setProperty("variant", "primary")
        self._code_button.clicked.connect(self._on_code_clicked)
        self._resend_button = QPushButton(tr("login_dialog.resend_button"), page)
        self._resend_button.clicked.connect(self._on_resend_clicked)
        self._code_qr_button = QPushButton(tr("login_dialog.qr_button"), page)
        self._code_qr_button.clicked.connect(lambda: self._start_qr(return_page=PAGE_CODE))
        row = QHBoxLayout()
        row.addWidget(self._code_qr_button)
        row.addWidget(self._resend_button)
        row.addStretch(1)
        row.addWidget(self._code_button)
        layout.addLayout(row)

        layout.addWidget(self._helper_label(tr("login_dialog.code_not_arriving"), page))
        layout.addStretch(1)

        self._stack.addWidget(page)

    def _show_delivery(self, delivery: CodeDelivery) -> None:
        assert self._account is not None
        self._code_delivery.setText(describe_delivery(delivery, self._account.phone))
        usable = delivery.channel not in UNUSABLE_CHANNELS
        self._code_edit.setEnabled(usable)
        self._code_button.setEnabled(usable)
        self._resend_available = delivery.next_channel is not None
        self._resend_seconds_left = max(0, int(delivery.timeout or 0)) if self._resend_available else 0
        self._update_resend_button()
        if self._resend_seconds_left > 0:
            self._resend_timer.start()
        else:
            self._resend_timer.stop()

    def _update_resend_button(self) -> None:
        self._resend_button.setVisible(self._resend_available)
        if self._resend_seconds_left > 0:
            self._resend_button.setText(tr("login_dialog.resend_button_wait", seconds=self._resend_seconds_left))
            self._resend_button.setEnabled(False)
        else:
            self._resend_button.setText(tr("login_dialog.resend_button"))
            self._resend_button.setEnabled(self._resend_available)

    def _on_resend_tick(self) -> None:
        self._resend_seconds_left = max(0, self._resend_seconds_left - 1)
        if self._resend_seconds_left == 0:
            self._resend_timer.stop()
        self._update_resend_button()

    def _on_resend_clicked(self) -> None:
        asyncio.ensure_future(self._do_resend())

    async def _do_resend(self) -> None:
        assert self._flow is not None
        self._code_error.setText("")
        self._resend_button.setEnabled(False)
        try:
            delivery = await self._flow.resend_code()
        except SendCodeUnavailableError:
            self._resend_available = False
            self._update_resend_button()
            self._code_error.setText(tr("login_dialog.error.resend_unavailable"))
            return
        except PhoneNumberFloodError:
            self._update_resend_button()
            self._code_error.setText(tr("login_dialog.error.phone_flood"))
            return
        except FloodWaitError as exc:
            self._update_resend_button()
            self._code_error.setText(tr("login_dialog.error.flood_wait", seconds=exc.seconds))
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.warning("Ошибка повторной отправки кода: %s", exc)
            self._update_resend_button()
            self._code_error.setText(tr("login_dialog.error.resend_failed", error=exc))
            return
        self._code_edit.clear()
        self._show_delivery(delivery)

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
            self._show_password_page()
        else:
            await self._on_authenticated(user, self._code_error)

    # ---- Page 2: 2FA password --------------------------------------------

    def _build_password_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(tr("login_dialog.password_label"), page))
        self._password_edit = QLineEdit(page)
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._password_edit)

        self._password_error = self._error_label(page)
        layout.addWidget(self._password_error)

        self._password_button = QPushButton(tr("login_dialog.confirm_button"), page)
        self._password_button.setProperty("variant", "primary")
        self._password_button.clicked.connect(self._on_password_clicked)
        layout.addWidget(self._password_button)

        self._stack.addWidget(page)

    def _show_password_page(self) -> None:
        self._resend_timer.stop()
        self._password_error.setText("")
        self._password_edit.clear()
        self._stack.setCurrentIndex(PAGE_PASSWORD)

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

        await self._on_authenticated(user, self._password_error)

    # ---- Page 3: success ---------------------------------------------------

    def _build_success_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)

        success_title = QLabel(tr("login_dialog.success_title"), page)
        success_title.setObjectName("dialogTitle")
        success_title.setProperty("status", "success")
        layout.addWidget(success_title)

        self._success_phone = QLabel(page)
        self._success_name = QLabel(page)
        self._success_username = QLabel(page)
        layout.addWidget(self._success_phone)
        layout.addWidget(self._success_name)
        layout.addWidget(self._success_username)

        done_button = QPushButton(tr("login_dialog.done_button"), page)
        done_button.setProperty("variant", "primary")
        done_button.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(done_button)
        layout.addLayout(row)

        self._stack.addWidget(page)

    async def _on_authenticated(self, user: AuthenticatedUser, error_label: QLabel) -> None:
        assert self._account is not None
        assert self._flow is not None
        account_manager = self._service.account_manager
        assert account_manager is not None
        account = self._account
        if user.phone:
            try:
                account = account_manager.adopt_phone(account, user.phone)
            except AccountAlreadyAddedError as exc:
                # The scanned account is already in the app under its own
                # row: this attempt's session would be a duplicate of it.
                await self._flow.discard()
                # log_out() leaves that client unusable; the next attempt
                # for this row must build a fresh one.
                account_manager.drop_client(self._account)
                self._flow = None
                self._account = None
                error_label.setText(tr("login_dialog.error.account_already_added", phone=exc.phone))
                return
        refreshed = account_manager.update_profile(
            account, user.telegram_user_id, user.username, user.display_name
        )
        self._account = refreshed

        self._success_phone.setText(tr("login_dialog.summary_account", phone=refreshed.phone))
        self._success_name.setText(tr("login_dialog.summary_name", name=refreshed.display_name or "-"))
        self._success_username.setText(
            tr("login_dialog.summary_username", username=refreshed.username)
            if refreshed.username
            else tr("login_dialog.summary_username_none")
        )
        self._resend_timer.stop()
        self._stack.setCurrentIndex(PAGE_SUCCESS)
        self.account_ready.emit(refreshed)

    # ---- Page 4: QR code ----------------------------------------------------

    def _build_qr_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)

        instructions = QLabel(tr("login_dialog.qr_instructions"), page)
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self._qr_image = QLabel(page)
        self._qr_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_image.setMinimumSize(QR_IMAGE_SIZE, QR_IMAGE_SIZE)
        layout.addWidget(self._qr_image, 0, Qt.AlignmentFlag.AlignHCenter)

        self._qr_status = self._helper_label("", page)
        self._qr_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._qr_status)

        self._qr_error = self._error_label(page)
        layout.addWidget(self._qr_error)

        self._qr_back_button = QPushButton(tr("login_dialog.back_button"), page)
        self._qr_back_button.clicked.connect(self._on_qr_back_clicked)
        self._qr_refresh_button = QPushButton(tr("login_dialog.qr_refresh_button"), page)
        self._qr_refresh_button.setProperty("variant", "primary")
        self._qr_refresh_button.clicked.connect(lambda: self._start_qr(return_page=self._qr_return_page))
        row = QHBoxLayout()
        row.addWidget(self._qr_back_button)
        row.addStretch(1)
        row.addWidget(self._qr_refresh_button)
        layout.addLayout(row)

        self._stack.addWidget(page)

    def _start_qr(self, return_page: int) -> None:
        if self._flow is None:
            return
        self._cancel_qr()
        self._resend_timer.stop()
        self._qr_return_page = return_page
        self._qr_image.clear()
        self._qr_error.setText("")
        self._qr_status.setText(tr("login_dialog.qr_loading"))
        self._qr_refresh_button.setVisible(False)
        self._stack.setCurrentIndex(PAGE_QR)
        self._qr_task = asyncio.ensure_future(self._run_qr_login(self._flow))

    def _show_qr_url(self, url: str) -> None:
        # The URL carries a login token: shown as a picture only, never
        # logged or put anywhere it could be copied from.
        self._qr_image.setPixmap(qr_pixmap(url, QR_IMAGE_SIZE))
        self._qr_status.setText(tr("login_dialog.qr_waiting"))

    async def _run_qr_login(self, flow: AuthenticationFlow) -> None:
        try:
            user = await flow.qr_login(self._show_qr_url)
        except QrLoginExpiredError:
            self._qr_image.clear()
            self._qr_status.setText("")
            self._qr_error.setText(tr("login_dialog.qr_expired"))
            self._qr_refresh_button.setVisible(True)
            return
        except FloodWaitError as exc:
            self._qr_status.setText("")
            self._qr_error.setText(tr("login_dialog.error.flood_wait", seconds=exc.seconds))
            self._qr_refresh_button.setVisible(True)
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.warning("Ошибка входа по QR-коду: %s", type(exc).__name__)
            self._qr_image.clear()
            self._qr_status.setText("")
            self._qr_error.setText(tr("login_dialog.error.qr_failed", error=exc))
            self._qr_refresh_button.setVisible(True)
            return
        finally:
            if self._qr_task is asyncio.current_task():
                self._qr_task = None

        if user is None:
            self._show_password_page()
            return
        await self._on_authenticated(user, self._qr_error)
        if self._stack.currentIndex() == PAGE_QR:
            # Not signed in (the account was already added): offer another scan.
            self._qr_image.clear()
            self._qr_status.setText("")
            self._qr_refresh_button.setVisible(self._flow is not None)

    def _cancel_qr(self) -> None:
        task, self._qr_task = self._qr_task, None
        if task is not None and not task.done():
            task.cancel()

    def _on_qr_back_clicked(self) -> None:
        self._cancel_qr()
        self._stack.setCurrentIndex(PAGE_CONNECT if self._flow is None else self._qr_return_page)
        if self._stack.currentIndex() == PAGE_CODE and self._resend_seconds_left > 0:
            self._resend_timer.start()

    def done(self, result: int) -> None:
        # accept(), reject(), Esc and the close button all end here.
        self._cancel_qr()
        self._resend_timer.stop()
        super().done(result)
