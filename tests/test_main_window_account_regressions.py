"""Post-v2.0.0 MainWindow-level regression tests.

These drive the real window: real signal handlers, real background tasks,
real state transitions -- the layer where the reported bugs actually bit.
The service-level behaviour is covered in
tests/test_account_lifecycle_regressions.py; what matters here is that the
window wires it up correctly and that nothing escapes as an unobserved
asyncio task exception.

Isolated throughout: temp Database + temp SecureStorage, so the machine's
real credential store and account list are never touched.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from app.database.database import Database
from app.security.secure_storage import SecureStorage
from app.telegram.demo_client import DEMO_ACCOUNT_PHONE
from app.telegram.exceptions import AccountDeletionError
from app.ui.main_window import MainWindow
from tests.mocks.fake_client_manager import FakeClientManager


def _make_window(tmp_path: Path) -> MainWindow:
    storage = SecureStorage(tmp_path / "secrets.dat")
    storage.save_api_credentials(1111111, "0" * 32)  # synthetic, never real
    window = MainWindow(database=Database(tmp_path / "app.db"), secure_storage=storage)
    # The real ClientManager would open genuine Telethon connections (and
    # real session files) the moment a status refresh runs. Swap in the
    # suite's existing fake so these tests exercise the window's own wiring
    # without any network or on-disk session at all.
    _install_fake_client_manager(window._service)
    return window


def _install_fake_client_manager(service) -> None:
    from app.telegram.account_manager import AccountManager

    fake = FakeClientManager()
    service._client_manager = fake
    service.account_manager = AccountManager(service.account_repository, fake)


async def _drain(window) -> None:
    """Let every background task the window started finish."""
    for _ in range(40):
        pending = [t for t in window._background_tasks if not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
    return


# ---- unobserved task exceptions ---------------------------------------------


@pytest.mark.asyncio
async def test_a_failing_background_task_is_observed_not_left_to_asyncio(qapp, tmp_path):
    # The exact shape of the reported terminal output: a task raised and
    # nothing ever retrieved its exception, so asyncio printed
    # "Task exception was never retrieved" at collection time. _spawn's
    # done-callback must retrieve it.
    window = _make_window(tmp_path)

    async def boom():
        raise RuntimeError("synthetic failure")

    with patch.object(window._logger, "error") as logged:
        task = window._spawn(boom(), "тестовая операция")
        await asyncio.gather(task, return_exceptions=True)

    assert task.done()
    assert task.exception() is not None  # retrieved -> asyncio stays quiet
    assert logged.called
    assert task not in window._background_tasks


@pytest.mark.asyncio
async def test_a_cancelled_background_task_is_not_reported_as_an_error(qapp, tmp_path):
    window = _make_window(tmp_path)

    async def forever():
        await asyncio.sleep(3600)

    with patch.object(window._logger, "error") as logged:
        task = window._spawn(forever(), "долгая операция")
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert logged.called is False
    assert task not in window._background_tasks


@pytest.mark.asyncio
async def test_background_tasks_are_held_until_they_finish(qapp, tmp_path):
    # asyncio documents that a task nothing holds a reference to can be
    # garbage collected mid-flight; the window keeps them alive.
    window = _make_window(tmp_path)
    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.sleep(0)

    task = window._spawn(work(), "работа")
    assert task in window._background_tasks
    await asyncio.gather(task, return_exceptions=True)
    assert task not in window._background_tasks


@pytest.mark.asyncio
async def test_delete_account_failure_is_surfaced_to_the_user_not_swallowed(qapp, tmp_path):
    # A locked session file must produce a visible message and leave the
    # window usable -- not a silent no-op, and not a raw traceback.
    window = _make_window(tmp_path)
    account = window._service.account_repository.create("+70000000031", "account_ui_del")

    async def failing_delete(_account):
        raise AccountDeletionError("session file locked")

    with patch.object(window._service.account_manager, "delete_account", failing_delete):
        with patch("app.ui.main_window.show_error") as shown:
            task = window._spawn(window._delete_account(account), "удаление аккаунта")
            await asyncio.gather(task, return_exceptions=True)

    assert task.exception() is None  # handled inside, not left to escape
    assert shown.called


@pytest.mark.asyncio
async def test_a_successful_delete_removes_the_account_and_refreshes(qapp, tmp_path):
    window = _make_window(tmp_path)
    repo = window._service.account_repository
    account = repo.create("+70000000032", "account_ui_ok")

    deleted = []

    async def fake_delete(acc):
        deleted.append(acc.id)
        repo.delete(acc.id)

    with patch.object(window._service.account_manager, "delete_account", fake_delete):
        task = window._spawn(window._delete_account(account), "удаление аккаунта")
        await asyncio.gather(task, return_exceptions=True)

    assert deleted == [account.id]
    assert repo.get_by_id(account.id) is None


# ---- account operations are serialized --------------------------------------


@pytest.mark.asyncio
async def test_a_refresh_cannot_run_while_a_delete_is_in_progress(qapp, tmp_path):
    # This is the WinError 32 race: a status refresh rebuilding a Telethon
    # client (and reopening its session file) partway through a delete is
    # exactly what made the delete fail. They must not interleave.
    window = _make_window(tmp_path)
    account = window._service.account_repository.create("+70000000033", "account_race_ui")
    # MainWindow spawns its own refresh during construction; let that
    # finish first so the ordering measured below is only this scenario's.
    await _drain(window)

    order = []
    delete_started = asyncio.Event()

    async def slow_delete(_acc):
        order.append("delete:start")
        delete_started.set()
        await asyncio.sleep(0.05)
        order.append("delete:end")

    async def marking_refresh(select_id=None):
        order.append("refresh")

    with patch.object(window._service.account_manager, "delete_account", slow_delete):
        with patch.object(window, "_refresh_accounts_locked", marking_refresh):
            delete_task = window._spawn(window._delete_account(account), "удаление")
            await delete_started.wait()
            refresh_task = window._spawn(window._refresh_accounts(), "обновление")
            await asyncio.gather(delete_task, refresh_task, return_exceptions=True)

    # The refresh must not have slipped between the delete's start and end.
    assert order[:3] == ["delete:start", "delete:end", "refresh"]


# ---- demo mode transitions through the real window --------------------------


@pytest.mark.asyncio
async def test_switching_to_a_real_account_works_after_leaving_demo_mode(qapp, tmp_path):
    # The headline bug: after a demo round trip the user could no longer
    # switch accounts, because exit_demo_mode left the window without a
    # usable account manager.
    window = _make_window(tmp_path)
    real = window._service.account_repository.create("+70000000040", "account_real_ui")

    window._enter_demo_mode()
    await _drain(window)
    assert window._service.is_demo_mode is True

    window._on_exit_demo_mode_clicked()
    await _drain(window)
    assert window._service.is_demo_mode is False

    assert window._service.account_manager is not None
    window._service.account_manager.switch_active_account(real.id)
    assert window._service.account_manager.active_account_id == real.id


@pytest.mark.asyncio
async def test_the_demo_account_is_gone_from_the_account_list_after_exiting(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._service.account_repository.create("+70000000041", "account_keep_me")

    window._enter_demo_mode()
    await _drain(window)
    window._on_exit_demo_mode_clicked()
    await _drain(window)

    phones = [a.phone for a in window._service.account_repository.list_all()]
    assert DEMO_ACCOUNT_PHONE not in phones
    assert "+70000000041" in phones


@pytest.mark.asyncio
async def test_repeated_demo_round_trips_through_the_window_stay_consistent(qapp, tmp_path):
    window = _make_window(tmp_path)
    real = window._service.account_repository.create("+70000000042", "account_repeat_ui")
    real_manager = window._service._client_manager

    for _ in range(3):
        window._enter_demo_mode()
        await _drain(window)
        assert window._service.is_demo_mode is True
        # isHidden() reflects the explicit setVisible() call regardless of
        # whether the never-shown top-level window is actually on screen.
        assert window._demo_banner.isHidden() is False

        window._on_exit_demo_mode_clicked()
        await _drain(window)
        assert window._service.is_demo_mode is False
        assert window._demo_banner.isHidden() is True

    assert window._service._client_manager is real_manager
    phones = [a.phone for a in window._service.account_repository.list_all()]
    assert phones == [real.phone]


@pytest.mark.asyncio
async def test_entering_demo_mode_twice_in_a_row_is_a_no_op(qapp, tmp_path):
    window = _make_window(tmp_path)
    real_manager = window._service._client_manager

    window._enter_demo_mode()
    demo_manager = window._service._client_manager
    window._enter_demo_mode()  # second click before anything settles
    await _drain(window)

    assert window._service._client_manager is demo_manager
    window._on_exit_demo_mode_clicked()
    await _drain(window)
    assert window._service._client_manager is real_manager


@pytest.mark.asyncio
async def test_exiting_demo_mode_when_not_in_demo_mode_is_a_no_op(qapp, tmp_path):
    window = _make_window(tmp_path)
    real_manager = window._service._client_manager

    window._on_exit_demo_mode_clicked()
    await _drain(window)

    assert window._service._client_manager is real_manager
    assert window._service.is_demo_mode is False


@pytest.mark.asyncio
async def test_demo_mode_leaves_stored_credentials_untouched_through_the_window(qapp, tmp_path):
    window = _make_window(tmp_path)
    before = window._service.secure_storage.load_api_credentials()

    window._enter_demo_mode()
    await _drain(window)
    window._on_exit_demo_mode_clicked()
    await _drain(window)

    after = window._service.secure_storage.load_api_credentials()
    assert before is not None and after is not None
    assert (after.api_id, after.api_hash) == (before.api_id, before.api_hash)


@pytest.mark.asyncio
async def test_shutdown_cancels_in_flight_background_work(qapp, tmp_path):
    # An account refresh still running when the database closes would keep
    # using it underneath the shutdown. Shutdown cancels and awaits the
    # others first -- and must not cancel the shutdown task itself, which
    # is started through the same _spawn().
    window = _make_window(tmp_path)
    await _drain(window)

    started = asyncio.Event()

    async def long_refresh():
        started.set()
        await asyncio.sleep(3600)

    victim = window._spawn(long_refresh(), "долгое обновление")
    await started.wait()

    shutdown = window._spawn(window._perform_shutdown(), "завершение работы")
    await asyncio.gather(shutdown, return_exceptions=True)

    assert victim.cancelled() is True
    assert shutdown.cancelled() is False
    assert shutdown.exception() is None


# ---- transition matrix: the awkward moments --------------------------------


@pytest.mark.asyncio
async def test_entering_demo_mode_immediately_after_startup(qapp, tmp_path):
    # No _drain() first: the window's own construction-time refresh is
    # still in flight, which is exactly when a user clicking straight
    # through onboarding would hit this.
    window = _make_window(tmp_path)
    real = window._service.account_repository.create("+70000000050", "account_startup")

    window._enter_demo_mode()
    await _drain(window)
    assert window._service.is_demo_mode is True

    window._on_exit_demo_mode_clicked()
    await _drain(window)
    assert window._service.is_demo_mode is False
    window._service.account_manager.switch_active_account(real.id)
    assert window._service.account_manager.active_account_id == real.id


@pytest.mark.asyncio
async def test_a_demo_transition_does_not_interleave_with_a_running_refresh(qapp, tmp_path):
    # The refresh collects statuses from whichever client manager was in
    # use when it started. It must finish before the queued refresh runs,
    # so the list the user is left looking at reflects the mode actually
    # in effect.
    window = _make_window(tmp_path)
    window._service.account_repository.create("+70000000051", "account_interleave")
    await _drain(window)

    order = []
    first_started = asyncio.Event()
    release = asyncio.Event()

    async def slow_refresh(select_id=None):
        order.append("refresh:start")
        if not first_started.is_set():
            first_started.set()
            await release.wait()
        order.append("refresh:end")

    with patch.object(window, "_refresh_accounts_locked", slow_refresh):
        slow = window._spawn(window._refresh_accounts(), "медленное обновление")
        await first_started.wait()
        window._enter_demo_mode()  # queues its own refresh behind the lock
        release.set()
        await _drain(window)
        await asyncio.gather(slow, return_exceptions=True)

    assert order[0] == "refresh:start"
    assert order[1] == "refresh:end"  # the first refresh was never cut in half
    assert window._service.is_demo_mode is True


@pytest.mark.asyncio
async def test_switching_accounts_after_deleting_one(qapp, tmp_path):
    window = _make_window(tmp_path)
    repo = window._service.account_repository
    first = repo.create("+70000000052", "account_del_then_switch_a")
    second = repo.create("+70000000053", "account_del_then_switch_b")
    await _drain(window)

    async def fake_delete(acc):
        repo.delete(acc.id)

    with patch.object(window._service.account_manager, "delete_account", fake_delete):
        await asyncio.gather(
            window._spawn(window._delete_account(first), "удаление"), return_exceptions=True
        )

    window._service.account_manager.switch_active_account(second.id)
    assert window._service.account_manager.active_account_id == second.id
    assert repo.get_by_id(first.id) is None


@pytest.mark.asyncio
async def test_demo_mode_right_before_shutdown_shuts_down_cleanly(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._service.account_repository.create("+70000000054", "account_before_shutdown")
    await _drain(window)

    window._enter_demo_mode()
    shutdown = window._spawn(window._perform_shutdown(), "завершение работы")
    await asyncio.gather(shutdown, return_exceptions=True)

    assert shutdown.exception() is None
    assert not [t for t in window._background_tasks if not t.done()]


@pytest.mark.asyncio
async def test_demo_mode_is_blocked_while_a_campaign_is_active(qapp, tmp_path):
    # Entering demo mode swaps the client manager the running campaign is
    # sending through, so it must be refused, not merely discouraged.
    window = _make_window(tmp_path)
    await _drain(window)

    class _ActiveCampaign:
        is_active = True

    window._current_campaign = _ActiveCampaign()
    with patch("app.ui.main_window.show_error") as shown:
        window._on_try_demo_mode_requested()

    assert shown.called
    assert window._service.is_demo_mode is False


@pytest.mark.asyncio
async def test_adding_an_account_is_refused_while_in_demo_mode(qapp, tmp_path):
    # Demo Mode swaps in a client manager that fabricates everything, so
    # the login dialog would "authorize" an invented account -- while
    # still writing the entered API credentials to SecureStorage and
    # leaving a real account row behind that outlives demo mode.
    window = _make_window(tmp_path)
    await _drain(window)

    window._enter_demo_mode()
    await _drain(window)
    before = [a.phone for a in window._service.account_repository.list_all()]

    with patch("app.ui.main_window.LoginDialog") as dialog_cls:
        with patch("app.ui.main_window.show_error") as shown:
            window._on_add_account_requested()

    assert shown.called
    assert dialog_cls.called is False  # the dialog never even opened
    assert [a.phone for a in window._service.account_repository.list_all()] == before

    window._on_exit_demo_mode_clicked()
    await _drain(window)
    with patch("app.ui.main_window.LoginDialog") as dialog_cls:
        dialog_cls.return_value.exec.return_value = 0
        window._on_add_account_requested()
    assert dialog_cls.called is True  # allowed again in real mode
