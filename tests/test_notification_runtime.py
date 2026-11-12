"""Delivery behavior against the durable outbox, without external services."""

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hse_schedule.directory import Student, StudentDirectory
from hse_schedule.notification_runtime import NotificationDispatcher, NotificationRuntime
from hse_schedule.notification_store import NotificationStore
from hse_schedule.push import ChannelDeliveryError


NOW = datetime(2026, 11, 12, 9, 20, tzinfo=timezone.utc)
EMAIL = "alice@example.test"
SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/test-subscription",
    "keys": {"p256dh": "not-used-by-fake-sender", "auth": "test"},
}


def draft(key="event", *, expires_at=None):
    return {
        "kind": "reminder", "event_key": key,
        "title": "Скоро начнётся пара", "body": "Математика, аудитория 101",
        "payload": {"lesson": {"starts_at": (NOW + timedelta(minutes=10)).isoformat()}},
        "expires_at": expires_at,
    }


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = NotificationStore(Path(self.temporary.name) / "notifications.sqlite3")
        self.directory = StudentDirectory([
            Student(EMAIL, "Алиса", group_oids=("1000",)),
        ])
        self.push = Mock()
        self.telegram = Mock()
        self.dispatcher = NotificationDispatcher(
            self.store, self.directory, push_sender=self.push, telegram_bot=self.telegram
        )

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def link_telegram(self, *, chat_id="12345", token="link-token"):
        self.store.create_telegram_link(EMAIL, token, NOW + timedelta(minutes=10))
        self.assertEqual(self.store.consume_telegram_link(token, chat_id, "alice_demo", NOW), EMAIL)

    def prepare(self, *, enabled=True, browser=True, telegram=False, notification=None):
        self.store.set_settings(EMAIL, enabled)
        if browser:
            self.store.add_subscription(EMAIL, SUBSCRIPTION, NOW)
        if telegram:
            self.link_telegram()
        self.store.publish_notifications(EMAIL, [notification or draft()], NOW)

    def test_enabled_sends_both_channels_once_and_marks_delivery_complete(self):
        self.prepare(telegram=True)
        self.assertEqual(self.dispatcher.drain(NOW), 2)
        self.push.send.assert_called_once()
        self.telegram.send.assert_called_once()
        self.assertEqual(self.push.send.call_args.args[0], SUBSCRIPTION)
        self.assertEqual(self.telegram.send.call_args.args[0], {"chat_id": "12345"})
        self.assertEqual(self.push.send.call_args.args[1]["id"], self.telegram.send.call_args.args[1]["id"])
        self.assertEqual(self.dispatcher.drain(NOW + timedelta(minutes=5)), 0)
        self.assertEqual(self.push.send.call_count, 1)
        self.assertEqual(self.store.list_notifications(EMAIL)["unread_count"], 1)

    def test_muted_accounts_keep_bell_without_external_delivery_or_later_replay(self):
        self.prepare(enabled=False, telegram=True)
        self.assertEqual(self.dispatcher.drain(NOW), 0)
        self.store.set_settings(EMAIL, True)
        self.assertEqual(self.dispatcher.drain(NOW + timedelta(minutes=1)), 0)
        self.push.send.assert_not_called()
        self.telegram.send.assert_not_called()
        self.assertEqual(self.store.list_notifications(EMAIL)["unread_count"], 1)

    def test_removed_student_cannot_receive_already_queued_delivery(self):
        self.prepare(telegram=True)
        dispatcher = NotificationDispatcher(
            self.store, StudentDirectory([]), push_sender=self.push, telegram_bot=self.telegram
        )
        self.assertEqual(dispatcher.drain(NOW), 0)
        self.assertEqual(dispatcher.drain(NOW + timedelta(minutes=5)), 0)
        self.push.send.assert_not_called()
        self.telegram.send.assert_not_called()

    def test_transient_failure_is_retried_only_after_the_backoff(self):
        self.prepare()
        self.push.send.side_effect = [ChannelDeliveryError(), None]
        self.assertEqual(self.dispatcher.drain(NOW), 0)
        self.assertEqual(self.dispatcher.drain(NOW + timedelta(seconds=29)), 0)
        self.assertEqual(self.push.send.call_count, 1)
        self.assertEqual(self.dispatcher.drain(NOW + timedelta(seconds=30)), 1)
        self.assertEqual(self.push.send.call_count, 2)
        self.assertEqual(self.dispatcher.drain(NOW + timedelta(minutes=5)), 0)

    def test_dead_subscription_is_removed_while_history_stays_available(self):
        self.prepare()
        self.push.send.side_effect = ChannelDeliveryError(permanent=True, remove_target=True)
        self.assertEqual(self.dispatcher.drain(NOW), 0)
        self.assertEqual(self.store.list_subscriptions(EMAIL), [])
        self.assertEqual(self.dispatcher.drain(NOW + timedelta(minutes=5)), 0)
        self.assertEqual(self.store.list_notifications(EMAIL)["unread_count"], 1)

    def test_failure_of_old_telegram_chat_does_not_unbind_new_chat(self):
        self.prepare(browser=False, telegram=True)

        def rebind_then_fail(target, _notification):
            self.assertEqual(target, {"chat_id": "12345"})
            self.link_telegram(chat_id="67890", token="new-link-token")
            raise ChannelDeliveryError(permanent=True, remove_target=True)

        self.telegram.send.side_effect = rebind_then_fail
        self.assertEqual(self.dispatcher.drain(NOW), 0)
        self.assertEqual(self.store.telegram_status(EMAIL), {"linked": True, "username": "alice_demo"})
        self.store.publish_notifications(EMAIL, [draft("new-event")], NOW)
        self.telegram.send.side_effect = None
        self.assertEqual(self.dispatcher.drain(NOW), 1)
        self.assertEqual(self.telegram.send.call_args.args[0], {"chat_id": "67890"})

    def test_mute_then_enable_between_claim_and_send_does_not_revive_cancelled_delivery(self):
        self.prepare(telegram=True)
        original_claim = self.store.claim_deliveries

        def claim_then_toggle(*args, **kwargs):
            deliveries = original_claim(*args, **kwargs)
            self.store.set_settings(EMAIL, False)
            self.store.set_settings(EMAIL, True)
            return deliveries

        with patch.object(self.store, "claim_deliveries", side_effect=claim_then_toggle):
            self.assertEqual(self.dispatcher.drain(NOW), 0)
        self.push.send.assert_not_called()
        self.telegram.send.assert_not_called()
        self.assertEqual(self.store.list_notifications(EMAIL)["unread_count"], 1)

    def test_unlink_between_claim_and_send_prevents_telegram_delivery(self):
        self.prepare(browser=False, telegram=True)
        original_claim = self.store.claim_deliveries

        def claim_then_unlink(*args, **kwargs):
            deliveries = original_claim(*args, **kwargs)
            self.store.unlink_telegram(EMAIL)
            return deliveries

        with patch.object(self.store, "claim_deliveries", side_effect=claim_then_unlink):
            self.assertEqual(self.dispatcher.drain(NOW), 0)
        self.telegram.send.assert_not_called()

    def test_expired_reminder_is_not_sent_to_telegram(self):
        starts = NOW + timedelta(minutes=10)
        self.prepare(browser=False, telegram=True, notification=draft(expires_at=starts.isoformat()))
        self.assertEqual(self.dispatcher.drain(starts), 0)
        self.telegram.send.assert_not_called()
        self.assertEqual(self.store.list_notifications(EMAIL)["unread_count"], 1)

    def test_unexpected_transport_error_is_retryable_without_logging_secrets(self):
        self.prepare()
        self.push.send.side_effect = RuntimeError("private_endpoint_secret")
        with self.assertLogs("hse_schedule.notification_runtime", level="WARNING") as logs:
            self.assertEqual(self.dispatcher.drain(NOW), 0)
        self.assertNotIn("private_endpoint_secret", " ".join(logs.output))
        self.push.send.side_effect = None
        self.assertEqual(self.dispatcher.drain(NOW + timedelta(seconds=30)), 1)


class RuntimeTests(unittest.TestCase):
    def test_runtime_runs_each_worker_and_stops_without_waiting_for_interval(self):
        refresh, reminders, deliveries, bot_updates = (threading.Event() for _ in range(4))
        engine = SimpleNamespace(
            refresh_schedules=refresh.set,
            emit_reminders=reminders.set,
            store=object(),
        )
        dispatcher = SimpleNamespace(drain=deliveries.set)

        def poll(store, now):
            self.assertIs(store, engine.store)
            self.assertIsNotNone(now.utcoffset())
            bot_updates.set()

        runtime = NotificationRuntime(
            engine, dispatcher, telegram_bot=SimpleNamespace(poll_once=poll),
            refresh_interval=60, reminder_interval=60, telegram_interval=60,
        )
        try:
            runtime.start()
            runtime.start()  # Repeated application startup does not duplicate workers.
            for event in (refresh, reminders, deliveries, bot_updates):
                self.assertTrue(event.wait(timeout=1), "Background callback did not run")
        finally:
            runtime.stop()
        runtime.stop()

    def test_worker_survives_callback_failure_and_retries(self):
        recovered = threading.Event()
        attempts = []

        def refresh():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("private source information")
            recovered.set()

        engine = SimpleNamespace(refresh_schedules=refresh, emit_reminders=lambda: None)
        runtime = NotificationRuntime(
            engine, SimpleNamespace(drain=lambda: None), refresh_interval=0.01,
        )
        try:
            with self.assertLogs("hse_schedule.notification_runtime", level="WARNING") as logs:
                runtime.start()
                self.assertTrue(recovered.wait(timeout=1))
            self.assertNotIn("private source information", " ".join(logs.output))
        finally:
            runtime.stop()

    def test_all_worker_intervals_must_be_positive_finite_numbers(self):
        engine, dispatcher = Mock(), Mock()
        for field in ("refresh_interval", "reminder_interval", "telegram_interval"):
            for invalid in (0, -1, float("nan"), float("inf")):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    NotificationRuntime(engine, dispatcher, **{field: invalid})


if __name__ == "__main__":
    unittest.main()
