"""Background refresh, reminder scheduling, outbox delivery and bot updates."""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone

from .directory import StudentDirectory
from .errors import UnknownStudent
from .notification_store import NotificationStore
from .notifications import NotificationEngine
from .push import ChannelDeliveryError

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    def __init__(self, store: NotificationStore, directory: StudentDirectory, *, push_sender=None, telegram_bot=None) -> None:
        self.store = store
        self.directory = directory
        self.push_sender = push_sender
        self.telegram_bot = telegram_bot

    def drain(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        began = time.monotonic()
        sent = 0
        for delivery in self.store.claim_deliveries(now, limit=10, lease_seconds=180):
            delivery_now = now + timedelta(seconds=time.monotonic() - began)
            if not self.store.delivery_is_active(delivery["id"], delivery_now):
                self.store.retry_delivery(delivery["id"], delivery_now, permanent=True)
                continue
            try:
                self.directory.get(delivery["email"])
            except UnknownStudent:
                self.store.retry_delivery(delivery["id"], delivery_now, permanent=True)
                continue
            if not self.store.get_settings(delivery["email"])["enabled"]:
                self.store.retry_delivery(delivery["id"], delivery_now, permanent=True)
                continue
            notification = self.store.get_notification(delivery["email"], delivery["notification"]["id"])
            if notification is None:
                self.store.retry_delivery(delivery["id"], delivery_now, permanent=True)
                continue
            sender = self.push_sender if delivery["channel"] == "webpush" else self.telegram_bot
            if sender is None:
                self.store.retry_delivery(delivery["id"], now)
                continue
            try:
                sender.send(delivery["target"], notification)
            except ChannelDeliveryError as error:
                if error.remove_target:
                    if delivery["channel"] == "webpush":
                        self.store.remove_subscription(delivery["email"], delivery["target"]["endpoint"])
                    else:
                        self.store.unlink_telegram_target(delivery["email"], delivery["target"]["chat_id"])
                self.store.retry_delivery(delivery["id"], now, permanent=error.permanent)
            except Exception:
                # Do not log transport exceptions: Telegram request URLs contain
                # credentials and push endpoints contain subscription secrets.
                logger.warning("Notification delivery failed; keeping the event in the inbox.")
                self.store.retry_delivery(delivery["id"], now)
            else:
                self.store.complete_delivery(delivery["id"], now)
                sent += 1
        return sent


class NotificationRuntime:
    """One refresh loop and independent, short-interval reminder/bot loops.

    Slow timetable HTTP requests cannot hold up cached reminders or bot linking.
    Durable event keys and SQLite leases also protect against multiple workers.
    """

    def __init__(
        self,
        engine: NotificationEngine,
        dispatcher: NotificationDispatcher,
        *,
        telegram_bot=None,
        refresh_interval: float = 60,
        reminder_interval: float = 5,
        telegram_interval: float = 3,
    ) -> None:
        if any(not math.isfinite(value) or value <= 0 for value in (refresh_interval, reminder_interval, telegram_interval)):
            raise ValueError("Интервал фоновой проверки должен быть положительным.")
        self.engine = engine
        self.dispatcher = dispatcher
        self.telegram_bot = telegram_bot
        self.refresh_interval = refresh_interval
        self.reminder_interval = reminder_interval
        self.telegram_interval = telegram_interval
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def _loop(self, callback, interval: float) -> None:
        while not self._stop.is_set():
            try:
                callback()
            except Exception:
                logger.warning("A notification worker failed; it will retry automatically.")
            self._stop.wait(interval)

    def _reminders_and_delivery(self) -> None:
        self.engine.emit_reminders()
        self.dispatcher.drain()

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        callbacks = [
            (self.engine.refresh_schedules, self.refresh_interval, "schedule-refresh"),
            (self._reminders_and_delivery, self.reminder_interval, "notification-delivery"),
        ]
        if self.telegram_bot is not None:
            callbacks.append((
                lambda: self.telegram_bot.poll_once(self.engine.store, datetime.now(timezone.utc)),
                self.telegram_interval,
                "telegram-linking",
            ))
        for callback, interval, name in callbacks:
            thread = threading.Thread(target=self._loop, args=(callback, interval), name=name, daemon=True)
            self._threads.append(thread)
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        deadline = time.monotonic() + 25
        for thread in self._threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        self._threads.clear()
