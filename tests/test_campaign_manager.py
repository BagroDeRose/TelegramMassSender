"""Campaign engine tests (spec item 58): state transitions, retry limits,
and FloodWait handling, driven through MockTelegramClient so nothing here
touches the real Telegram network.
"""
from __future__ import annotations

import asyncio

import pytest

from app.campaign.campaign_manager import CampaignManager
from app.campaign.campaign_state import (
    CampaignStateMachine,
    CampaignStatus,
    InvalidStateTransitionError,
)
from app.campaign.send_queue import SendItemStatus
from app.recipients.parser import parse_recipient_line
from app.telegram.media_sender import Attachment
from tests.mocks.mock_telegram_client import MockTelegramClient, make_flood_wait
from tests.mocks.mock_telegram_client import PERMANENT_ERROR_FACTORIES


class FakeRateLimiter:
    """CampaignManager only needs .next_delay() (duck typing); using a
    fixed, fast delay here keeps tests quick without weakening the real
    RateLimiter's production floor (covered separately in
    test_rate_limiter.py)."""

    def __init__(self, delay: float = 0.01) -> None:
        self._delay = delay

    def next_delay(self) -> float:
        return self._delay


def make_recipients(*usernames: str):
    return [parse_recipient_line(f"@{u}") for u in usernames]


def make_manager(usernames, client=None, max_retries=2, delay=0.01):
    client = client or MockTelegramClient()
    manager = CampaignManager(
        client=client,
        recipients=make_recipients(*usernames),
        message_text="hello",
        message_entities=[],
        attachments=[],
        rate_limiter=FakeRateLimiter(delay),
        max_retries=max_retries,
    )
    return manager, client


async def run_to_finish(manager, timeout=10):
    fut = asyncio.get_event_loop().create_future()
    manager.finished.connect(lambda status: fut.done() or fut.set_result(status))
    manager.start()
    return await asyncio.wait_for(fut, timeout=timeout)


# ---- state machine (pure, no network) --------------------------------------


def test_state_machine_happy_transitions():
    sm = CampaignStateMachine()
    sm.transition(CampaignStatus.RUNNING)
    sm.transition(CampaignStatus.PAUSED)
    sm.transition(CampaignStatus.RUNNING)
    sm.transition(CampaignStatus.STOPPING)
    sm.transition(CampaignStatus.STOPPED)
    assert sm.status == CampaignStatus.STOPPED
    assert sm.is_terminal


def test_state_machine_rejects_invalid_transition():
    sm = CampaignStateMachine()
    with pytest.raises(InvalidStateTransitionError):
        sm.transition(CampaignStatus.COMPLETED)  # can't complete an idle campaign


def test_state_machine_completed_is_terminal():
    sm = CampaignStateMachine(initial=CampaignStatus.RUNNING)
    sm.transition(CampaignStatus.COMPLETED)
    assert sm.is_terminal
    with pytest.raises(InvalidStateTransitionError):
        sm.transition(CampaignStatus.RUNNING)


# ---- full engine, driven via MockTelegramClient ----------------------------


async def test_happy_path_completes(qapp):
    manager, client = make_manager(["alice", "bobby", "carol"])
    status = await run_to_finish(manager)
    assert status == CampaignStatus.COMPLETED.value
    snap = manager.snapshot()
    assert snap.sent == 3 and snap.failed == 0
    assert len(client.sent_messages) == 3


async def test_permanent_error_marks_failed_but_continues(qapp):
    client = MockTelegramClient()
    manager, client = make_manager(["alice", "bobby", "carol"], client=client)
    client.entity_behavior["bobby"] = "not_found"
    status = await run_to_finish(manager)
    assert status == CampaignStatus.COMPLETED.value
    snap = manager.snapshot()
    assert snap.sent == 2 and snap.failed == 1
    items = {i.recipient.value: i for i in manager._queue.items}
    assert items["bobby"].status == SendItemStatus.FAILED


@pytest.mark.parametrize("behavior", list(PERMANENT_ERROR_FACTORIES.keys()))
async def test_all_permanent_error_categories_are_terminal_not_retried(qapp, behavior):
    # These categories (UsernameNotOccupied/UserIsBlocked/PeerIdInvalid/
    # ChatWriteForbidden/UserPrivacyRestricted) are modelled in
    # campaign_manager as SEND-time permanent errors -- raised here from
    # send_message (resolution succeeds first, matching e.g. a user who
    # blocks the account, or a chat where writing is forbidden).
    client = MockTelegramClient()

    async def failing_send(entity, text, formatting_entities=None):
        raise PERMANENT_ERROR_FACTORIES[behavior]()

    client.send_message = failing_send
    manager, client = make_manager(["target"], client=client, max_retries=3)
    status = await run_to_finish(manager)
    assert status == CampaignStatus.COMPLETED.value
    item = manager._queue.items[0]
    assert item.status == SendItemStatus.FAILED
    assert item.attempts == 1, "permanent errors must never be retried"


async def test_transient_error_retries_then_succeeds(qapp):
    client = MockTelegramClient()
    calls = {"n": 0}

    manager, client = make_manager(["alice"], client=client, max_retries=3, delay=0.01)

    # Force the first send attempt to fail with a transient error, then succeed.
    async def flaky_send_message(entity, text, formatting_entities=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("blip")
        client.sent_messages.append(("message", entity, text, formatting_entities))

    client.send_message = flaky_send_message

    status = await run_to_finish(manager, timeout=15)
    assert status == CampaignStatus.COMPLETED.value
    assert calls["n"] == 2
    assert manager.snapshot().sent == 1


async def test_transient_error_exhausts_retries(qapp):
    client = MockTelegramClient()

    async def always_fails(entity, text, formatting_entities=None):
        raise ConnectionError("down")

    client.send_message = always_fails
    manager, client = make_manager(["alice"], client=client, max_retries=2, delay=0.01)

    status = await run_to_finish(manager, timeout=15)
    assert status == CampaignStatus.COMPLETED.value
    item = manager._queue.items[0]
    assert item.status == SendItemStatus.FAILED
    assert item.attempts == 2


async def test_floodwait_pauses_campaign_and_requeues_item(qapp):
    client = MockTelegramClient()
    calls = {"n": 0}

    async def send_with_floodwait(entity, text, formatting_entities=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise make_flood_wait(1)
        client.sent_messages.append(("message", entity, text, formatting_entities))

    client.send_message = send_with_floodwait
    manager, client = make_manager(["alice", "bobby"], client=client, delay=0.01)

    paused = asyncio.get_event_loop().create_future()
    manager.state_changed.connect(
        lambda s: paused.done() or (s == CampaignStatus.PAUSED.value and paused.set_result(True))
    )
    manager.start()
    await asyncio.wait_for(paused, timeout=10)
    assert manager.status == CampaignStatus.PAUSED

    # The campaign stops issuing new sends as soon as a FloodWait is hit
    # (spec: no auto-continuing past a flood limit), so the recipient that
    # triggered it is re-queued as PENDING and the one after it in the
    # queue was never attempted -- both remain PENDING, nothing was
    # skipped or marked sent/failed.
    pending_items = [i for i in manager._queue.items if i.status == SendItemStatus.PENDING]
    assert len(pending_items) == 2
    assert manager.snapshot().sent == 0

    finished = asyncio.get_event_loop().create_future()
    manager.finished.connect(lambda s: finished.done() or finished.set_result(s))
    manager.resume()
    status = await asyncio.wait_for(finished, timeout=10)
    assert status == CampaignStatus.COMPLETED.value
    assert manager.snapshot().sent == 2


async def test_stop_prevents_further_sends(qapp):
    manager, client = make_manager(["alice", "bobby", "carol"], delay=0.5)
    manager.start()
    await asyncio.sleep(0.05)
    await manager.stop()
    assert manager.status == CampaignStatus.STOPPED
    assert len(client.sent_messages) <= 1


async def test_double_start_raises(qapp):
    manager, client = make_manager(["alice"])
    manager.start()
    with pytest.raises(RuntimeError):
        manager.start()
    await manager.stop()


# ---- partial multi-step send: retry/FloodWait must never resend an
# already-delivered step (P0 regression: a recipient's plan can involve
# more than one Telegram delivery call -- e.g. two attachments each become
# their own single-file "step" -- and a failure on a *later* step must not
# cause an *earlier, already-successful* step to be repeated) -------------


def _two_document_attachments(tmp_path):
    """Two non-album-eligible attachments -> build_media_send_plan produces
    two separate single-file groups (steps), never combined into one album
    call -- the simplest shape with more than one delivery step."""
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"a")
    file_b = tmp_path / "b.pdf"
    file_b.write_bytes(b"b")
    return file_a, file_b, [Attachment(path=file_a), Attachment(path=file_b)]


async def test_transient_error_after_first_of_two_steps_does_not_resend_first_step(qapp, tmp_path):
    file_a, file_b, attachments = _two_document_attachments(tmp_path)

    client = MockTelegramClient()
    step0_sends = []
    step1_sends = []
    b_attempts = {"n": 0}

    async def flaky_send_file(entity, files, caption=None, formatting_entities=None):
        if files == str(file_a):
            step0_sends.append(files)
            return None
        b_attempts["n"] += 1
        if b_attempts["n"] == 1:
            raise ConnectionError("blip")
        step1_sends.append(files)
        return None

    client.send_file = flaky_send_file

    manager = CampaignManager(
        client=client,
        recipients=make_recipients("alice"),
        message_text="hi",
        message_entities=[],
        attachments=attachments,
        rate_limiter=FakeRateLimiter(0.01),
        max_retries=3,
    )

    status = await run_to_finish(manager, timeout=15)

    assert status == CampaignStatus.COMPLETED.value
    item = manager._queue.items[0]
    assert item.status == SendItemStatus.SENT
    assert len(step0_sends) == 1, "step 0 (already successful) must not be re-sent on retry"
    assert len(step1_sends) == 1


async def test_floodwait_after_first_of_two_steps_does_not_resend_first_step(qapp, tmp_path):
    file_a, file_b, attachments = _two_document_attachments(tmp_path)

    client = MockTelegramClient()
    step0_sends = []
    step1_sends = []
    b_attempts = {"n": 0}

    async def send_file_with_floodwait(entity, files, caption=None, formatting_entities=None):
        if files == str(file_a):
            step0_sends.append(files)
            return None
        b_attempts["n"] += 1
        if b_attempts["n"] == 1:
            raise make_flood_wait(1)
        step1_sends.append(files)
        return None

    client.send_file = send_file_with_floodwait

    manager = CampaignManager(
        client=client,
        recipients=make_recipients("alice"),
        message_text="hi",
        message_entities=[],
        attachments=attachments,
        rate_limiter=FakeRateLimiter(0.01),
        max_retries=3,
    )

    paused = asyncio.get_event_loop().create_future()
    manager.state_changed.connect(
        lambda s: paused.done() or (s == CampaignStatus.PAUSED.value and paused.set_result(True))
    )
    manager.start()
    await asyncio.wait_for(paused, timeout=10)
    assert manager.status == CampaignStatus.PAUSED
    assert len(step0_sends) == 1, "step 0 must have been sent exactly once before the flood wait"

    finished = asyncio.get_event_loop().create_future()
    manager.finished.connect(lambda s: finished.done() or finished.set_result(s))
    manager.resume()
    status = await asyncio.wait_for(finished, timeout=10)

    assert status == CampaignStatus.COMPLETED.value
    item = manager._queue.items[0]
    assert item.status == SendItemStatus.SENT
    assert len(step0_sends) == 1, "step 0 must not be repeated after resume"
    assert len(step1_sends) == 1
