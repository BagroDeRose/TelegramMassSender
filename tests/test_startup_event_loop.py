"""The first-run onboarding must not open before the asyncio loop runs.

Reported: "Не удалось подключиться: no running event loop" when adding an
account straight from the onboarding's "Get Started". main() called
maybe_show_onboarding() -- a modal exec() that opens the login dialog --
before run_event_loop(). Qt's nested loop still ran the dialog's
coroutines (qasync schedules them on Qt timers), but asyncio only marks
its loop as running inside run_until_complete, so the first
asyncio.get_running_loop() (Telethon's connect) raised.
"""
from __future__ import annotations

import asyncio

import qasync

from app import main as main_module


def _fresh_loop(qapp):
    loop = qasync.QEventLoop(qapp)
    asyncio.set_event_loop(loop)
    return loop


def _close(loop):
    asyncio.set_event_loop(None)
    loop.close()


def test_the_reported_error_is_what_runs_before_the_loop_does(qapp):
    # The mechanism itself: a coroutine scheduled on the qasync loop but
    # driven only by Qt's own event processing, as inside a modal exec()
    # before run_event_loop(), has no running asyncio loop.
    loop = _fresh_loop(qapp)
    errors = []

    async def connect_like_telethon():
        try:
            asyncio.get_running_loop()
        except RuntimeError as exc:
            errors.append(str(exc))

    try:
        task = asyncio.ensure_future(connect_like_telethon(), loop=loop)
        for _ in range(20):
            qapp.processEvents()
            if task.done():
                break
        assert errors == ["no running event loop"]
    finally:
        _close(loop)


def test_onboarding_waits_for_the_running_loop(qapp):
    loop = _fresh_loop(qapp)
    seen = []

    class Window:
        def maybe_show_onboarding(self):
            seen.append(asyncio._get_running_loop())

    try:
        main_module.schedule_onboarding(Window())
        assert seen == []  # not shown synchronously, before the loop runs
        loop.run_until_complete(asyncio.sleep(0.05))
    finally:
        _close(loop)
    assert seen == [loop]
