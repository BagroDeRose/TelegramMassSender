---
name: qt-async-development
description: Use when changing GUI code in app/ui/**, app/main.py, or anything mixing PySide6 signals/slots with asyncio/qasync — to avoid blocking the event loop, hanging tasks, or a non-terminating EXE.
---

# PySide6 + qasync development rules

This app runs Qt's event loop and asyncio together via `qasync`
(`app/main.py`, `app/ui/*`, `app/telegram/qt_bridge.py`,
`app/campaign/send_queue.py`). Mixing the two incorrectly causes UI freezes
or a process that never exits after the window closes.

## Rules

- Never call blocking I/O (network, `time.sleep`, synchronous Telethon calls,
  large file reads) directly on the Qt/asyncio event loop thread. Long
  operations (sending, media upload, entity resolution) must be
  `async`/awaited coroutines scheduled on the qasync loop, or explicitly
  offloaded — check how `app/telegram/qt_bridge.py` and
  `app/campaign/campaign_manager.py` already do this before adding a new
  pattern.
- Every `asyncio.create_task`/background coroutine started from a Qt
  slot must have a clear owner responsible for cancelling or awaiting it — no
  fire-and-forget tasks that can outlive the widget or window that created
  them.
- Respect cancellation: a running campaign must be stoppable mid-flight
  (`app/campaign/campaign_state.py`, `send_queue.py`) without leaving Telethon
  calls half-finished in a way that corrupts state.
- On window close (`closeEvent` / `WM_CLOSE`), all background tasks and the
  Telethon client must shut down cleanly before the process exits — test this
  explicitly (`tests/test_main_window_shutdown.py` already covers part of
  this; extend it for new background work rather than adding an untested
  shutdown path).
- After any change touching startup/shutdown or task lifecycle, verify the
  **packaged EXE** actually terminates (no lingering process in Task
  Manager) — not just that the dev-run window closes. See
  [[windows-exe-release]].
- Signals/slots crossing threads (if any thread other than the Qt/asyncio
  loop thread is introduced) must use Qt's thread-safe signal mechanism, not
  direct widget mutation from a foreign thread.

## Tests

- GUI/async behavior changes should be covered by `tests/test_main_window_*`
  and related tests using `pytest-asyncio` (`asyncio_mode = auto` per
  `pytest.ini`). See [[regression-testing]].
