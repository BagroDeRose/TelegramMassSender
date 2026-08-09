"""Campaign engine: drives the send queue through Start/Pause/Resume/Stop,
handling FloodWait and per-recipient errors correctly (spec items 21-33).

One CampaignManager instance = one campaign run on one Telegram account.
app.telegram.account_manager enforces that only one campaign can be
active per account at a time (spec item 52) via AccountManager's switch
guard combined with the caller (main_window) refusing to start a second
CampaignManager for an account whose existing one is still active.

Runs entirely on the shared qasync event loop as a single asyncio.Task;
Pause/Stop never touch a blocking call -- only asyncio.sleep, polled in
short, cancellable increments, and never mid-item (spec item 25: a Pause
takes effect only *between* recipients, never interrupting a send that
is already in flight).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QObject, Signal
from telethon import TelegramClient
from telethon.errors import (
    AuthKeyError,
    ChatWriteForbiddenError,
    FloodWaitError,
    PeerIdInvalidError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    UserIsBlockedError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)
from telethon.tl.types import TypeMessageEntity

from app.campaign.campaign_state import CampaignStateMachine, CampaignStatus
from app.campaign.rate_limiter import RateLimiter
from app.campaign.send_queue import SendItem, SendItemStatus, SendQueue
from app.logging.logger import get_logger
from app.recipients.parser import ParsedRecipient
from app.telegram.media_sender import Attachment
from app.telegram.recipient_resolver import RecipientResolver
from app.telegram.sender import send_to_recipient

logger = get_logger()

_PERMANENT_ERROR_MESSAGES = {
    UsernameNotOccupiedError: "пользователь не найден",
    UserIsBlockedError: "пользователь заблокировал аккаунт",
    PeerIdInvalidError: "некорректный Telegram ID",
    ChatWriteForbiddenError: "отправка сообщения запрещена",
    UserPrivacyRestrictedError: "Telegram ограничил возможность отправки",
}
_PERMANENT_ERROR_TYPES = tuple(_PERMANENT_ERROR_MESSAGES.keys())

_CRITICAL_ERROR_TYPES = (AuthKeyError, UserDeactivatedError, UserDeactivatedBanError)

_TRANSIENT_ERROR_TYPES = (ConnectionError, OSError, asyncio.TimeoutError, TimeoutError)

_MAX_BACKOFF_SECONDS = 30


@dataclass
class ProgressSnapshot:
    total: int
    sent: int
    failed: int
    skipped: int
    pending: int


class CampaignManager(QObject):
    state_changed = Signal(str)
    item_result = Signal(object)  # SendItem
    progress_changed = Signal(object)  # ProgressSnapshot
    flood_wait_started = Signal(int)  # total seconds
    flood_wait_tick = Signal(int)  # remaining seconds
    log_message = Signal(str)
    finished = Signal(str)  # final CampaignStatus value

    def __init__(
        self,
        client: TelegramClient,
        recipients: List[ParsedRecipient],
        message_text: str,
        message_entities: List[TypeMessageEntity],
        attachments: List[Attachment],
        rate_limiter: RateLimiter,
        max_retries: int,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._queue = SendQueue(recipients)
        self._text = message_text
        self._entities = message_entities
        self._attachments = attachments
        self._rate_limiter = rate_limiter
        self._max_retries = max_retries
        self._resolver = RecipientResolver(client)

        self._state = CampaignStateMachine()
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    @property
    def status(self) -> CampaignStatus:
        return self._state.status

    @property
    def is_active(self) -> bool:
        return self._state.is_active

    def snapshot(self) -> ProgressSnapshot:
        counts = self._queue.counts()
        return ProgressSnapshot(
            total=len(self._queue),
            sent=counts[SendItemStatus.SENT],
            failed=counts[SendItemStatus.FAILED],
            skipped=counts[SendItemStatus.SKIPPED],
            pending=counts[SendItemStatus.PENDING] + counts[SendItemStatus.SENDING],
        )

    # ---- lifecycle control -------------------------------------------------

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Кампания уже запущена")
        self._task = asyncio.ensure_future(self._run())

    def pause(self) -> None:
        if self._state.status != CampaignStatus.RUNNING:
            return
        self._pause_event.clear()
        self._state.transition(CampaignStatus.PAUSED)
        self._emit_state()
        self._log("⏸ Рассылка поставлена на паузу")

    def resume(self) -> None:
        if self._state.status != CampaignStatus.PAUSED:
            return
        self._state.transition(CampaignStatus.RUNNING)
        self._emit_state()
        self._log("▶ Рассылка возобновлена")
        self._pause_event.set()

    async def stop(self) -> None:
        if self._state.is_terminal:
            return
        if self._state.status in (CampaignStatus.RUNNING, CampaignStatus.PAUSED, CampaignStatus.WAITING_FOR_FLOOD):
            self._state.transition(CampaignStatus.STOPPING)
            self._emit_state()
        self._stop_event.set()
        self._pause_event.set()  # unblock a paused loop so it can observe the stop
        if self._task is not None:
            await self._task

    # ---- internals -----------------------------------------------------------

    def _log(self, text: str) -> None:
        logger.info(text)
        self.log_message.emit(text)

    def _emit_state(self) -> None:
        self.state_changed.emit(self._state.status.value)

    def _emit_progress(self, item: Optional[SendItem] = None) -> None:
        if item is not None:
            self.item_result.emit(item)
        self.progress_changed.emit(self.snapshot())

    async def _sleep_interruptible(self, duration: float, on_tick=None) -> bool:
        """Sleep up to `duration` seconds in short steps so Stop can cut it
        short. Returns False if interrupted by a stop request."""
        remaining = duration
        step = 1.0
        while remaining > 0:
            if self._stop_event.is_set():
                return False
            this_step = min(step, remaining)
            await asyncio.sleep(this_step)
            remaining -= this_step
            if on_tick is not None:
                on_tick(max(0, round(remaining)))
        return not self._stop_event.is_set()

    async def _run(self) -> None:
        self._state.transition(CampaignStatus.RUNNING)
        self._emit_state()
        self._log(f"▶ Рассылка запущена: получателей {len(self._queue)}")

        try:
            while not self._stop_event.is_set():
                await self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                item = self._queue.next_pending()
                if item is None:
                    self._state.transition(CampaignStatus.COMPLETED)
                    self._emit_state()
                    self._log("✓ Рассылка завершена")
                    break

                item.status = SendItemStatus.SENDING
                outcome = await self._attempt_send(item)

                if outcome == "critical":
                    self._state.transition(CampaignStatus.ERROR)
                    self._emit_state()
                    self._emit_progress(item)
                    break

                if outcome == "floodwait":
                    if self._stop_event.is_set():
                        break
                    self._state.transition(CampaignStatus.PAUSED)
                    self._emit_state()
                    self._pause_event.clear()
                    self._log("Рассылка приостановлена после ограничения Telegram. Нажмите «Продолжить», чтобы продолжить.")
                    self._emit_progress(item)
                    continue

                self._emit_progress(item)

                if self._stop_event.is_set():
                    break
                if not self._queue.has_pending():
                    continue

                delay = self._rate_limiter.next_delay()
                self._log(f"Следующая отправка через {round(delay)} сек.")
                completed = await self._sleep_interruptible(delay)
                if not completed:
                    break
        finally:
            if self._stop_event.is_set() and self._state.status not in (
                CampaignStatus.COMPLETED,
                CampaignStatus.ERROR,
            ):
                if self._state.can_transition(CampaignStatus.STOPPING):
                    self._state.transition(CampaignStatus.STOPPING)
                if self._state.can_transition(CampaignStatus.STOPPED):
                    self._state.transition(CampaignStatus.STOPPED)
                self._emit_state()
                self._log("■ Рассылка остановлена")
            self.finished.emit(self._state.status.value)

    async def _attempt_send(self, item: SendItem) -> str:
        resolved = await self._resolver.resolve(item.recipient)
        if not resolved.is_ready:
            item.status = SendItemStatus.FAILED
            item.error = resolved.error or "Получатель недоступен"
            self._log(f"✗ {item.recipient.display_label} — {item.error}")
            return "failed"

        attempt = 0
        while True:
            attempt += 1
            item.attempts = attempt
            try:
                await send_to_recipient(
                    self._client, resolved.entity, self._text, self._entities, self._attachments
                )
            except FloodWaitError as exc:
                item.status = SendItemStatus.PENDING
                wait_seconds = int(exc.seconds)
                self._log(
                    f"Telegram временно ограничил отправку. Необходимо подождать: {wait_seconds} сек."
                )
                self.flood_wait_started.emit(wait_seconds)
                self._state.transition(CampaignStatus.WAITING_FOR_FLOOD)
                self._emit_state()
                await self._sleep_interruptible(wait_seconds, on_tick=self.flood_wait_tick.emit)
                return "floodwait"
            except _CRITICAL_ERROR_TYPES as exc:
                item.status = SendItemStatus.FAILED
                item.error = "Аккаунт недоступен"
                logger.error("Критическая ошибка аккаунта: %s", exc)
                self._log(f"✗ Критическая ошибка аккаунта: {exc}")
                return "critical"
            except _PERMANENT_ERROR_TYPES as exc:
                item.status = SendItemStatus.FAILED
                item.error = _PERMANENT_ERROR_MESSAGES.get(type(exc), str(exc))
                self._log(f"✗ {item.recipient.display_label} — {item.error}")
                return "failed"
            except _TRANSIENT_ERROR_TYPES:
                if attempt >= self._max_retries:
                    item.status = SendItemStatus.FAILED
                    item.error = "Сетевая ошибка"
                    self._log(f"✗ {item.recipient.display_label} — сетевая ошибка")
                    return "failed"
                backoff = min(2 ** attempt, _MAX_BACKOFF_SECONDS)
                self._log(
                    f"… повтор {attempt}/{self._max_retries} для "
                    f"{item.recipient.display_label} через {backoff} сек."
                )
                completed = await self._sleep_interruptible(backoff)
                if not completed:
                    item.status = SendItemStatus.SKIPPED
                    return "failed"
                continue
            except Exception as exc:  # noqa: BLE001 - last-resort, categorized as a normal failure
                logger.exception("Непредвиденная ошибка при отправке %s", item.recipient.display_label)
                item.status = SendItemStatus.FAILED
                item.error = "Непредвиденная ошибка"
                self._log(f"✗ {item.recipient.display_label} — непредвиденная ошибка: {exc}")
                return "failed"
            else:
                item.status = SendItemStatus.SENT
                self._log(f"✓ {item.recipient.display_label} — отправлено")
                return "sent"
