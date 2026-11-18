"""app.telegram.authentication: where Telegram sent the code, resend, and
QR login -- against real Telethon TL objects and a stand-in client (no
network)."""
from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace

import pytest
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import auth as auth_types

from app.telegram import authentication
from app.telegram.authentication import (
    AuthenticationFlow,
    CodeChannel,
    QrLoginExpiredError,
    describe_sent_code,
    mask_phone,
    normalize_phone,
)


def sent_code(sent_type, next_type=None, timeout=None, phone_code_hash="hash1"):
    return auth_types.SentCode(type=sent_type, phone_code_hash=phone_code_hash, next_type=next_type, timeout=timeout)


@pytest.mark.parametrize(
    "sent_type, channel",
    [
        (auth_types.SentCodeTypeApp(length=5), CodeChannel.APP),
        (auth_types.SentCodeTypeSms(length=5), CodeChannel.SMS),
        (auth_types.SentCodeTypeCall(length=5), CodeChannel.CALL),
        (auth_types.SentCodeTypeFlashCall(pattern="*"), CodeChannel.FLASH_CALL),
        (auth_types.SentCodeTypeMissedCall(prefix="+7", length=4), CodeChannel.MISSED_CALL),
        (auth_types.SentCodeTypeEmailCode(email_pattern="a***@m.ru", length=6), CodeChannel.EMAIL),
        (auth_types.SentCodeTypeSetUpEmailRequired(), CodeChannel.EMAIL_SETUP_REQUIRED),
        (auth_types.SentCodeTypeFragmentSms(url="https://fragment.com/x", length=5), CodeChannel.FRAGMENT),
        (auth_types.SentCodeTypeFirebaseSms(length=5), CodeChannel.FIREBASE_SMS),
    ],
)
def test_every_delivery_type_is_named(sent_type, channel):
    assert describe_sent_code(sent_code(sent_type)).channel == channel


def test_delivery_details_are_kept():
    delivery = describe_sent_code(
        sent_code(
            auth_types.SentCodeTypeEmailCode(email_pattern="a***@m.ru", length=6),
            next_type=auth_types.CodeTypeSms(),
            timeout=60,
        )
    )
    assert delivery.email_pattern == "a***@m.ru"
    assert delivery.length == 6
    assert delivery.next_channel == CodeChannel.SMS
    assert delivery.timeout == 60


def test_no_next_type_means_no_resend():
    delivery = describe_sent_code(sent_code(auth_types.SentCodeTypeApp(length=5)))
    assert delivery.next_channel is None


def test_mask_phone_keeps_only_prefix_and_last_digits():
    assert mask_phone("+79991234567") == "+79*******67"
    assert "1234" not in mask_phone("+79991234567")
    assert mask_phone(None) == "+"


def test_normalize_phone():
    assert normalize_phone("79991234567") == "+79991234567"
    assert normalize_phone("+7 999 123-45-67") == "+79991234567"
    assert normalize_phone("") is None


class FakeQr:
    def __init__(self, outcomes):
        # one per token: "timeout", "password", or "ok"
        self.outcomes = list(outcomes)
        self.token_index = 0
        self.recreated = 0
        self.expires = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(seconds=30)
        self.waits = []

    @property
    def url(self):
        return f"tg://login?token=T{self.token_index}"

    async def recreate(self):
        self.recreated += 1
        self.token_index += 1

    async def wait(self, timeout=None):
        self.waits.append(timeout)
        outcome = self.outcomes.pop(0)
        if outcome == "timeout":
            raise asyncio.TimeoutError()
        if outcome == "password":
            raise SessionPasswordNeededError(request=None)
        return SimpleNamespace(id=5)


class FakeAuthClient:
    def __init__(self, sent=None, qr=None, me=None):
        self.connected = False
        self.sent = list(sent or [])
        self.qr = qr
        self.me = me or SimpleNamespace(id=42, first_name="Ann", last_name=None, username="ann", phone="79990001122")
        self.code_requests = 0
        self.logged_out = False

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True

    async def send_code_request(self, phone):
        self.code_requests += 1
        return self.sent.pop(0)

    async def qr_login(self):
        return self.qr

    async def sign_in(self, **kwargs):
        return None

    async def get_me(self):
        return self.me

    async def log_out(self):
        self.logged_out = True
        return True


async def test_request_code_reports_where_the_code_went():
    client = FakeAuthClient(sent=[sent_code(auth_types.SentCodeTypeSms(length=5), next_type=auth_types.CodeTypeCall(), timeout=30)])
    flow = AuthenticationFlow(client, "+79990001122")
    delivery = await flow.request_code()
    assert client.connected
    assert delivery.channel == CodeChannel.SMS
    assert delivery.next_channel == CodeChannel.CALL


async def test_resend_uses_the_new_hash():
    client = FakeAuthClient(
        sent=[
            sent_code(auth_types.SentCodeTypeApp(length=5), next_type=auth_types.CodeTypeSms(), phone_code_hash="h1"),
            sent_code(auth_types.SentCodeTypeSms(length=5), phone_code_hash="h2"),
        ]
    )
    flow = AuthenticationFlow(client, "+79990001122")
    await flow.request_code()
    delivery = await flow.resend_code()
    assert delivery.channel == CodeChannel.SMS
    assert flow._phone_code_hash == "h2"
    assert client.code_requests == 2


async def test_resend_before_a_request_is_refused():
    flow = AuthenticationFlow(FakeAuthClient(), "+79990001122")
    with pytest.raises(RuntimeError):
        await flow.resend_code()


async def test_qr_login_shows_a_fresh_code_after_each_expiry_and_signs_in():
    qr = FakeQr(["timeout", "timeout", "ok"])
    flow = AuthenticationFlow(FakeAuthClient(qr=qr), "+79990001122")
    shown = []
    user = await flow.qr_login(shown.append)
    assert shown == ["tg://login?token=T0", "tg://login?token=T1", "tg://login?token=T2"]
    assert qr.recreated == 2
    assert user.telegram_user_id == 42
    assert user.phone == "+79990001122"
    # Never waits longer than a token lives, whatever the PC clock says.
    assert all(authentication.QR_MIN_WAIT_SECONDS <= w <= authentication.QR_MAX_WAIT_SECONDS for w in qr.waits)


async def test_qr_login_with_2fa_asks_for_the_password():
    flow = AuthenticationFlow(FakeAuthClient(qr=FakeQr(["password"])), "+79990001122")
    assert await flow.qr_login(lambda url: None) is None


async def test_qr_login_gives_up_after_the_last_token(monkeypatch):
    monkeypatch.setattr(authentication, "QR_MAX_TOKENS", 3)
    qr = FakeQr(["timeout"] * 3)
    flow = AuthenticationFlow(FakeAuthClient(qr=qr), "+79990001122")
    with pytest.raises(QrLoginExpiredError):
        await flow.qr_login(lambda url: None)
    assert qr.recreated == 2


def test_qr_wait_is_clamped_for_a_wrong_pc_clock():
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    assert authentication._qr_wait_seconds(now + datetime.timedelta(hours=5)) == authentication.QR_MAX_WAIT_SECONDS
    assert authentication._qr_wait_seconds(now - datetime.timedelta(hours=5)) == authentication.QR_MIN_WAIT_SECONDS
    assert authentication._qr_wait_seconds(None) == authentication.QR_MAX_WAIT_SECONDS


async def test_a_missing_phone_from_telegram_is_none():
    client = FakeAuthClient(qr=FakeQr(["ok"]), me=SimpleNamespace(id=1, first_name="A", last_name=None, username=None, phone=None))
    user = await AuthenticationFlow(client, "+79990001122").qr_login(lambda url: None)
    assert user.phone is None


async def test_discard_logs_out_and_never_raises():
    client = FakeAuthClient()
    await AuthenticationFlow(client, "+79990001122").discard()
    assert client.logged_out

    async def boom():
        raise ConnectionError("offline")

    client.log_out = boom
    await AuthenticationFlow(client, "+79990001122").discard()  # no exception
