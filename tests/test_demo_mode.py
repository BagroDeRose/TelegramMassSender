"""Tests for Demo Mode (ROADMAP v2.0): app.telegram.demo_client's
DemoTelegramClient/DemoClientManager, and TelegramService.enter_demo_mode.
No prior coverage existed for either app.telegram.service.py or Demo Mode
itself.
"""
from __future__ import annotations

import asyncio

import pytest

from app.campaign.campaign_manager import CampaignManager
from app.database.database import Database
from app.recipients.parser import parse_recipient_line
from app.telegram.demo_client import (
    DEMO_ACCOUNT_DISPLAY_NAME,
    DEMO_ACCOUNT_PHONE,
    DEMO_ACCOUNT_USERNAME,
    DemoClientManager,
    DemoTelegramClient,
    make_demo_user,
)
from app.security.secure_storage import SecureStorage
from app.telegram.service import TelegramService


class FakeRateLimiter:
    def __init__(self, delay: float = 0.01) -> None:
        self._delay = delay

    def next_delay(self) -> float:
        return self._delay


def make_recipients(*usernames: str):
    return [parse_recipient_line(f"@{u}") for u in usernames]


async def run_to_finish(manager, timeout=15):
    fut = asyncio.get_event_loop().create_future()
    manager.finished.connect(lambda status: fut.done() or fut.set_result(status))
    manager.start()
    return await asyncio.wait_for(fut, timeout=timeout)


# ---- DemoTelegramClient / DemoClientManager -- duck-compatibility ----------


async def test_client_starts_disconnected_and_connects():
    client = DemoTelegramClient()
    assert client.is_connected() is False
    await client.connect()
    assert client.is_connected() is True


async def test_client_disconnect_and_log_out_both_clear_connected_state():
    client = DemoTelegramClient()
    await client.connect()
    await client.disconnect()
    assert client.is_connected() is False

    await client.connect()
    await client.log_out()
    assert client.is_connected() is False


async def test_client_is_always_authorized():
    client = DemoTelegramClient()
    assert await client.is_user_authorized() is True


async def test_get_entity_returns_a_real_user_instance_on_success():
    from telethon.tl.types import User

    client = DemoTelegramClient()
    # Force the success branch deterministically -- see the failure-rate
    # test below for the other branch.
    import app.telegram.demo_client as demo_client_module

    original_rate = demo_client_module.FAILURE_RATE
    demo_client_module.FAILURE_RATE = 0.0
    try:
        entity = await client.get_entity("someone")
        assert isinstance(entity, User)
        assert entity.username == "someone"
    finally:
        demo_client_module.FAILURE_RATE = original_rate


async def test_get_entity_can_simulate_a_not_found_failure():
    from telethon.errors import UsernameNotOccupiedError

    import app.telegram.demo_client as demo_client_module

    original_rate = demo_client_module.FAILURE_RATE
    demo_client_module.FAILURE_RATE = 1.0
    try:
        client = DemoTelegramClient()
        with pytest.raises(UsernameNotOccupiedError):
            await client.get_entity("someone")
    finally:
        demo_client_module.FAILURE_RATE = original_rate


async def test_send_message_records_the_send_on_success():
    import app.telegram.demo_client as demo_client_module

    original_rate = demo_client_module.FAILURE_RATE
    demo_client_module.FAILURE_RATE = 0.0
    try:
        client = DemoTelegramClient()
        await client.send_message("entity", "hello", None)
        assert client.sent_messages == [("message", "entity", "hello", None)]
    finally:
        demo_client_module.FAILURE_RATE = original_rate


async def test_send_message_can_simulate_a_blocked_failure():
    from telethon.errors import UserIsBlockedError

    import app.telegram.demo_client as demo_client_module

    original_rate = demo_client_module.FAILURE_RATE
    demo_client_module.FAILURE_RATE = 1.0
    try:
        client = DemoTelegramClient()
        with pytest.raises(UserIsBlockedError):
            await client.send_message("entity", "hello")
    finally:
        demo_client_module.FAILURE_RATE = original_rate


async def test_failure_rate_produces_both_outcomes_over_many_attempts():
    # Not a statistical precision test -- just proves FAILURE_RATE's
    # default value is neither 0 nor 1 in practice, i.e. the demo
    # genuinely shows a realistic mix rather than always succeeding or
    # always failing.
    client = DemoTelegramClient()
    outcomes = set()
    for i in range(200):
        try:
            await client.get_entity(f"user{i}")
            outcomes.add("success")
        except Exception:  # noqa: BLE001
            outcomes.add("failure")
        if outcomes == {"success", "failure"}:
            break
    assert outcomes == {"success", "failure"}


def test_make_demo_user_gives_stable_first_name_for_the_same_identifier():
    a = make_demo_user("alice")
    b = make_demo_user("alice")
    assert a.first_name == b.first_name


async def test_manager_get_or_create_returns_the_same_client_for_a_session():
    manager = DemoClientManager()
    first = manager.get_or_create("session_a")
    second = manager.get_or_create("session_a")
    assert first is second


async def test_manager_connect_and_is_authorized():
    manager = DemoClientManager()
    assert await manager.is_authorized("session_a") is True


async def test_manager_disconnect_all_disconnects_every_tracked_client():
    manager = DemoClientManager()
    await manager.connect("session_a")
    await manager.connect("session_b")
    await manager.disconnect_all()
    assert manager.get_active_client("session_a").is_connected() is False
    assert manager.get_active_client("session_b").is_connected() is False


async def test_manager_log_out_is_safe_when_never_connected():
    manager = DemoClientManager()
    await manager.log_out("never_created")  # must not raise


async def test_manager_remove_stops_tracking_the_session():
    manager = DemoClientManager()
    manager.get_or_create("session_a")
    manager.remove("session_a")
    assert manager.get_active_client("session_a") is None


# ---- TelegramService.enter_demo_mode ---------------------------------------


@pytest.fixture
def service(tmp_path):
    # An isolated SecureStorage pointed at a tmp_path file, NOT the real
    # default (machine-wide DPAPI-backed) one -- without this,
    # TelegramService() would read whatever real Telegram API credentials
    # genuinely happen to be stored on whatever machine runs this test
    # (confirmed directly against this repo's own dev machine, which has
    # real ones from actual prior app use). See TelegramService's
    # secure_storage parameter docstring for the incident that caused
    # this to be added.
    db = Database(db_path=tmp_path / "app.db")
    storage = SecureStorage(tmp_path / "secrets.dat")
    yield TelegramService(db, secure_storage=storage)
    db.close()


def test_enter_demo_mode_does_not_require_real_api_credentials(service):
    assert service.is_configured is False  # no API ID/Hash ever provided to this isolated instance
    service.enter_demo_mode()
    assert service.is_demo_mode is True


def test_enter_demo_mode_seeds_a_recognizable_demo_account(service):
    account = service.enter_demo_mode()
    assert account.phone == DEMO_ACCOUNT_PHONE
    assert account.username == DEMO_ACCOUNT_USERNAME
    assert account.display_name == DEMO_ACCOUNT_DISPLAY_NAME


def test_enter_demo_mode_switches_to_the_demo_account(service):
    account = service.enter_demo_mode()
    assert service.account_manager.active_account_id == account.id


def test_enter_demo_mode_never_touches_secure_storage(service):
    service.enter_demo_mode()
    # is_configured reflects whether a *real* ClientManager (from real
    # API credentials) was ever activated -- entering demo mode replaces
    # _client_manager with a DemoClientManager, so this must NOT flip to
    # True as a side effect.
    assert service.secure_storage.load_api_credentials() is None


def test_enter_demo_mode_is_safe_to_call_twice(service):
    first = service.enter_demo_mode()
    second = service.enter_demo_mode()
    assert first.phone == second.phone
    assert service.is_demo_mode is True


# ---- end-to-end: a real CampaignManager run against the demo client -------


async def test_a_real_campaign_runs_to_completion_against_the_demo_client(qapp):
    # The actual point of Demo Mode: CampaignManager (unmodified,
    # production code) must be able to run a full campaign against
    # DemoTelegramClient exactly as it would against a real Telethon
    # client -- proving the duck-typing is genuinely sufficient, not just
    # plausible-looking.
    client = DemoTelegramClient()
    manager = CampaignManager(
        client=client,
        recipients=make_recipients("alice", "bob", "carol", "dave", "erin"),
        message_text="hello from demo mode",
        message_entities=[],
        attachments=[],
        rate_limiter=FakeRateLimiter(0.01),
        max_retries=1,
    )

    from app.campaign.campaign_state import CampaignStatus

    status = await run_to_finish(manager)

    assert CampaignStatus(status) == CampaignStatus.COMPLETED
    total = len(manager.items)
    assert total == 5
    # Every item reached a terminal state -- nothing left pending/stuck.
    from app.campaign.send_queue import SendItemStatus

    for item in manager.items:
        assert item.status in (SendItemStatus.SENT, SendItemStatus.FAILED, SendItemStatus.SKIPPED)
