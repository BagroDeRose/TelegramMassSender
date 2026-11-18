"""LoginDialog: where the code went, resend, QR login, and the dialog
never leaving a QR task running after it closed. No network: the dialog
runs against a stand-in client (tests/test_authentication.py's)."""
from __future__ import annotations

import asyncio

import pytest
from telethon.errors import PhoneNumberFloodError, SendCodeUnavailableError
from telethon.tl.types import auth as auth_types

from app.database.database import Database
from app.database.repositories import AccountRepository
from app.i18n import get_language, set_language
from app.telegram.account_manager import AccountManager
from app.telegram.authentication import CodeChannel, CodeDelivery
from app.ui import login_dialog as login_dialog_module
from app.ui.login_dialog import (
    PAGE_CODE,
    PAGE_CONNECT,
    PAGE_PASSWORD,
    PAGE_QR,
    PAGE_SUCCESS,
    LoginDialog,
    describe_delivery,
)
from tests.mocks.fake_client_manager import FakeClientManager
from tests.test_authentication import FakeAuthClient, FakeQr, sent_code

PHONE = "+79990001122"


class _Storage:
    def load_api_credentials(self):
        return None


class _ClientManager(FakeClientManager):
    def __init__(self, client) -> None:
        super().__init__()
        self.client = client

    def get_or_create(self, session_name):
        return self.client


class _Service:
    def __init__(self, repo, client) -> None:
        self.secure_storage = _Storage()
        self.client_manager = _ClientManager(client)
        self.account_manager = AccountManager(repo, self.client_manager)
        self.configured = None

    def configure_api_credentials(self, api_id, api_hash):
        self.configured = (api_id, api_hash)


@pytest.fixture
def repo(tmp_path):
    db = Database(db_path=tmp_path / "app.db")
    yield AccountRepository(db)
    db.close()


def make_dialog(repo, client, phone=PHONE):
    service = _Service(repo, client)
    dialog = LoginDialog(service)
    dialog._api_id_edit.setText("1111111")
    dialog._api_hash_edit.setText("0" * 32)  # synthetic, never real
    dialog._phone_edit.setText(phone)
    return dialog, service


async def test_the_code_page_says_the_code_went_by_sms(qapp, repo):
    client = FakeAuthClient(sent=[sent_code(auth_types.SentCodeTypeSms(length=5), next_type=auth_types.CodeTypeCall(), timeout=30)])
    dialog, _ = make_dialog(repo, client)
    await dialog._do_connect()
    assert dialog._stack.currentIndex() == PAGE_CODE
    assert "SMS" in dialog._code_delivery.text()
    assert PHONE in dialog._code_delivery.text()
    # Resend is offered, but only once Telegram's timeout has passed.
    assert not dialog._resend_button.isHidden()
    assert not dialog._resend_button.isEnabled()
    for _ in range(30):
        dialog._on_resend_tick()
    assert dialog._resend_button.isEnabled()


async def test_a_code_sent_to_the_app_without_resend_hides_the_button(qapp, repo):
    client = FakeAuthClient(sent=[sent_code(auth_types.SentCodeTypeApp(length=5))])
    dialog, _ = make_dialog(repo, client)
    await dialog._do_connect()
    assert "Telegram" in dialog._code_delivery.text()
    assert dialog._resend_button.isHidden()
    assert dialog._code_edit.isEnabled()


async def test_email_setup_required_points_to_qr_instead_of_a_code(qapp, repo):
    client = FakeAuthClient(sent=[sent_code(auth_types.SentCodeTypeSetUpEmailRequired())])
    dialog, _ = make_dialog(repo, client)
    await dialog._do_connect()
    assert not dialog._code_edit.isEnabled()
    assert not dialog._code_button.isEnabled()
    assert "QR" in dialog._code_delivery.text()


async def test_resend_shows_the_new_delivery(qapp, repo):
    client = FakeAuthClient(
        sent=[
            sent_code(auth_types.SentCodeTypeApp(length=5), next_type=auth_types.CodeTypeSms()),
            sent_code(auth_types.SentCodeTypeSms(length=5)),
        ]
    )
    dialog, _ = make_dialog(repo, client)
    await dialog._do_connect()
    await dialog._do_resend()
    assert "SMS" in dialog._code_delivery.text()
    assert dialog._resend_button.isHidden()  # no further way offered


async def test_resend_unavailable_says_so_and_hides_resend(qapp, repo):
    client = FakeAuthClient(sent=[sent_code(auth_types.SentCodeTypeApp(length=5), next_type=auth_types.CodeTypeSms())])
    dialog, _ = make_dialog(repo, client)
    await dialog._do_connect()

    async def unavailable(phone):
        raise SendCodeUnavailableError(request=None)

    client.send_code_request = unavailable
    await dialog._do_resend()
    assert dialog._resend_button.isHidden()
    assert "QR" in dialog._code_error.text()


async def test_too_many_attempts_is_named(qapp, repo):
    client = FakeAuthClient()

    async def flood(phone):
        raise PhoneNumberFloodError(request=None)

    client.send_code_request = flood
    dialog, _ = make_dialog(repo, client)
    await dialog._do_connect()
    assert dialog._stack.currentIndex() == PAGE_CONNECT
    assert "QR" in dialog._connect_error.text()
    assert dialog._connect_button.isEnabled()


async def test_qr_login_from_the_first_page_signs_in(qapp, repo):
    client = FakeAuthClient(qr=FakeQr(["timeout", "ok"]))
    dialog, service = make_dialog(repo, client)
    ready = []
    dialog.account_ready.connect(ready.append)
    dialog._on_connect_qr_clicked()
    assert dialog._stack.currentIndex() == PAGE_QR
    await dialog._qr_task
    assert dialog._stack.currentIndex() == PAGE_SUCCESS
    assert not dialog._qr_image.pixmap().isNull()
    assert ready and ready[0].telegram_user_id == 42
    assert service.configured == (1111111, "0" * 32)


async def test_qr_login_takes_the_phone_of_the_account_that_scanned(qapp, repo):
    client = FakeAuthClient(qr=FakeQr(["ok"]))
    dialog, _ = make_dialog(repo, client, phone="+70001112233")
    dialog._on_connect_qr_clicked()
    await dialog._qr_task
    assert [a.phone for a in repo.list_all()] == ["+79990001122"]


async def test_qr_login_with_2fa_continues_with_the_password(qapp, repo):
    client = FakeAuthClient(qr=FakeQr(["password"]))
    dialog, _ = make_dialog(repo, client)
    dialog._on_connect_qr_clicked()
    await dialog._qr_task
    assert dialog._stack.currentIndex() == PAGE_PASSWORD
    dialog._password_edit.setText("synthetic-password")
    await dialog._do_submit_password()
    assert dialog._stack.currentIndex() == PAGE_SUCCESS


async def test_a_qr_scanned_in_an_account_already_added_is_refused(qapp, repo):
    client = FakeAuthClient(qr=FakeQr(["ok"]))
    dialog, service = make_dialog(repo, client, phone="+70001112233")
    existing = service.account_manager.register_account("+79990001122")
    dialog._on_connect_qr_clicked()
    await dialog._qr_task
    assert dialog._stack.currentIndex() == PAGE_QR
    assert "+79990001122" in dialog._qr_error.text()
    assert client.logged_out  # the duplicate session is ended
    assert service.client_manager.removed  # and its dead client dropped
    assert repo.get_by_id(existing.id).telegram_user_id is None  # untouched
    assert dialog._qr_refresh_button.isHidden()
    dialog._on_qr_back_clicked()
    assert dialog._stack.currentIndex() == PAGE_CONNECT


async def test_an_expired_qr_offers_a_refresh(qapp, repo, monkeypatch):
    from app.telegram import authentication

    monkeypatch.setattr(authentication, "QR_MAX_TOKENS", 2)
    client = FakeAuthClient(qr=FakeQr(["timeout", "timeout"]))
    dialog, _ = make_dialog(repo, client)
    dialog._on_connect_qr_clicked()
    await dialog._qr_task
    assert not dialog._qr_refresh_button.isHidden()
    assert dialog._qr_error.text()


class _BlockingQr(FakeQr):
    async def wait(self, timeout=None):
        await asyncio.Event().wait()


async def test_closing_the_dialog_stops_the_qr_login(qapp, repo):
    client = FakeAuthClient(qr=_BlockingQr([]))
    dialog, _ = make_dialog(repo, client)
    dialog._on_connect_qr_clicked()
    task = dialog._qr_task
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    dialog.reject()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert dialog._qr_task is None


async def test_leaving_the_qr_page_stops_the_qr_login(qapp, repo):
    client = FakeAuthClient(qr=_BlockingQr([]))
    dialog, _ = make_dialog(repo, client)
    dialog._on_connect_qr_clicked()
    task = dialog._qr_task
    await asyncio.sleep(0)
    dialog._on_qr_back_clicked()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert dialog._stack.currentIndex() == PAGE_CONNECT


async def test_invalid_input_never_starts_a_qr_login(qapp, repo):
    dialog, _ = make_dialog(repo, FakeAuthClient(), phone="123")
    dialog._on_connect_qr_clicked()
    assert dialog._qr_task is None
    assert dialog._stack.currentIndex() == PAGE_CONNECT
    assert repo.list_all() == []


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("channel", list(CodeChannel))
def test_every_delivery_has_a_sentence(qapp, language, channel):
    previous = get_language()
    set_language(language)
    try:
        for next_channel in [None, *CodeChannel]:
            delivery = CodeDelivery(
                channel=channel,
                next_channel=next_channel,
                length=4,
                email_pattern="a***@m.ru",
                fragment_url="https://fragment.com/x",
            )
            text = describe_delivery(delivery, PHONE)
            assert text and "login_dialog." not in text
    finally:
        set_language(previous)


def test_the_qr_url_is_never_logged(qapp, repo):
    from unittest.mock import patch

    dialog, _ = make_dialog(repo, FakeAuthClient())
    with patch.object(login_dialog_module.logger, "info") as info, patch.object(
        login_dialog_module.logger, "warning"
    ) as warning:
        dialog._show_qr_url("tg://login?token=SECRET")
    calls = info.call_args_list + warning.call_args_list
    assert all("SECRET" not in str(call) for call in calls)
