import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hse_schedule.notification_store import NotificationStore


NOW = datetime(2026, 11, 12, 9, tzinfo=timezone.utc)
ALICE = "alice@example.test"
BOB = "bob@example.test"


def subscription(suffix="one"):
    return {"endpoint": f"https://push.example.test/{suffix}", "keys": {"p256dh": "key", "auth": "secret"}}


def draft(key="one", **changes):
    value = {"kind": "reminder", "event_key": key, "title": "Скоро пара",
             "body": "Математика через 10 минут", "payload": {"lesson_id": key}, "expires_at": None}
    value.update(changes)
    return value


class NotificationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "notifications.sqlite3"
        self.store = NotificationStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def publish(self, email=ALICE, notifications=None, now=NOW):
        return self.store.publish_notifications(email, notifications or [draft()], now)

    def link_telegram(self, email=ALICE, token="link-token", chat_id="123"):
        self.store.create_telegram_link(email, token, NOW + timedelta(minutes=10))
        self.assertEqual(self.store.consume_telegram_link(token, chat_id, "student", NOW), email)

    def test_muted_default_keeps_inbox_without_external_delivery(self):
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.link_telegram()
        self.assertEqual(self.store.get_settings(ALICE), {"enabled": False})
        self.publish()
        self.assertEqual(self.store.list_notifications(ALICE)["unread_count"], 1)
        self.assertEqual(self.store.claim_deliveries(NOW), [])
        self.store.set_settings(ALICE, True)
        self.assertEqual(self.store.claim_deliveries(NOW), [])

    def test_enabled_fans_out_to_each_browser_and_telegram(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription("one"), NOW)
        self.store.add_subscription(ALICE, subscription("two"), NOW)
        self.link_telegram()
        self.publish()
        deliveries = self.store.claim_deliveries(NOW)
        self.assertEqual(len(deliveries), 3)
        self.assertEqual(sorted(d["channel"] for d in deliveries), ["telegram", "webpush", "webpush"])
        self.assertEqual({d["notification"]["id"] for d in deliveries}, {1})
        self.assertEqual(self.store.claim_deliveries(NOW), [])

    def test_disabling_cancels_pending_and_claimed_deliveries(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.publish(notifications=[draft("one"), draft("two")])
        claimed = self.store.claim_deliveries(NOW, limit=1)
        self.store.set_settings(ALICE, False)
        self.store.retry_delivery(claimed[0]["id"], NOW)
        self.store.set_settings(ALICE, True)
        self.assertEqual(self.store.claim_deliveries(NOW + timedelta(days=1)), [])
        self.assertEqual(len(self.store.list_notifications(ALICE)["items"]), 2)

    def test_read_state_and_pagination_are_account_scoped(self):
        self.publish(notifications=[draft("one"), draft("two"), draft("three")])
        self.publish(email=BOB, notifications=[draft("bob")])
        first = self.store.list_notifications(ALICE, limit=2)
        self.assertEqual([item["id"] for item in first["items"]], [3, 2])
        self.assertEqual(first["next_before"], 2)
        self.assertEqual(first["unread_count"], 3)
        self.assertEqual(self.store.list_notifications(ALICE, before=2)["items"][0]["id"], 1)
        self.assertFalse(self.store.mark_read(BOB, 1, NOW))
        self.assertTrue(self.store.mark_read(ALICE, 1, NOW))
        self.assertTrue(self.store.mark_read(ALICE, 1, NOW + timedelta(minutes=1)))
        self.assertEqual(self.store.list_notifications(ALICE, unread_only=True)["unread_count"], 2)
        self.assertEqual(self.store.mark_all_read(ALICE, NOW), 2)
        self.assertEqual(self.store.list_notifications(BOB)["unread_count"], 1)

    def test_snapshot_cas_and_events_commit_atomically(self):
        fields = {"start": NOW.date(), "finish": NOW.date(), "lessons": [{"id": "one"}],
                  "notifications": [draft()], "now": NOW}
        self.assertTrue(self.store.commit_observation(ALICE, None, **fields))
        self.assertEqual(self.store.load_snapshot(ALICE)["version"], 1)
        fields["notifications"] = [draft("stale")]
        self.assertFalse(self.store.commit_observation(ALICE, None, **fields))
        self.assertEqual(self.store.list_notifications(ALICE)["unread_count"], 1)
        self.assertFalse(self.store.publish_notifications(ALICE, [draft("stale")], NOW, expected_version=2))
        self.assertTrue(self.store.publish_notifications(ALICE, [draft("fresh")], NOW, expected_version=1))
        self.assertEqual(self.store.load_snapshot(ALICE)["version"], 1)

    def test_repeat_event_is_not_inserted_or_replayed(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.publish()
        self.publish()
        self.assertEqual(self.store.list_notifications(ALICE)["unread_count"], 1)
        self.assertEqual(len(self.store.claim_deliveries(NOW)), 1)

    def test_restart_preserves_all_account_state(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.link_telegram()
        self.store.commit_observation(ALICE, None, start=NOW.date(), finish=NOW.date(),
                                      lessons=[{"id": "one"}], notifications=[draft()], now=NOW)
        self.store.mark_read(ALICE, 1, NOW)
        self.store.close()
        self.store = NotificationStore(self.path)
        self.assertTrue(self.store.get_settings(ALICE)["enabled"])
        self.assertTrue(self.store.telegram_status(ALICE)["linked"])
        self.assertEqual(self.store.list_notifications(ALICE)["unread_count"], 0)
        self.assertEqual(self.store.load_snapshot(ALICE)["lessons"], [{"id": "one"}])
        self.assertEqual(len(self.store.claim_deliveries(NOW)), 2)

    def test_telegram_links_expire_are_single_use_and_replace_previous_links(self):
        self.store.create_telegram_link(ALICE, "old", NOW + timedelta(minutes=1))
        self.store.create_telegram_link(ALICE, "new", NOW + timedelta(minutes=1))
        self.assertIsNone(self.store.consume_telegram_link("old", "123", "student", NOW))
        self.assertIsNone(self.store.consume_telegram_link("new", "123", "student", NOW + timedelta(minutes=1)))
        self.link_telegram()
        self.assertIsNone(self.store.consume_telegram_link("link-token", "123", "student", NOW))
        self.assertEqual(self.store.telegram_status(ALICE), {"linked": True, "username": "student"})
        self.store.create_telegram_link(ALICE, "after-unlink", NOW + timedelta(minutes=1))
        self.store.unlink_telegram(ALICE)
        self.assertIsNone(self.store.consume_telegram_link("after-unlink", "123", None, NOW))
        self.assertFalse(self.store.telegram_status(ALICE)["linked"])

    def test_rebinding_chat_and_browser_cannot_deliver_to_previous_owner(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.link_telegram()
        self.publish()
        self.store.add_subscription(BOB, subscription(), NOW)
        self.link_telegram(email=BOB, token="bob-link")
        self.assertFalse(self.store.telegram_status(ALICE)["linked"])
        self.assertEqual(self.store.list_subscriptions(ALICE), [])
        self.assertEqual(self.store.claim_deliveries(NOW), [])
        self.store.set_settings(BOB, True)
        self.publish(email=BOB)
        self.assertEqual({d["email"] for d in self.store.claim_deliveries(NOW)}, {BOB})

    def test_removed_channels_cancel_pending_deliveries(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.link_telegram()
        self.publish()
        self.store.remove_subscription(BOB, subscription()["endpoint"])
        self.assertEqual(len(self.store.list_subscriptions(ALICE)), 1)
        self.store.remove_subscription(ALICE, subscription()["endpoint"])
        self.store.unlink_telegram(ALICE)
        self.assertEqual(self.store.claim_deliveries(NOW), [])

    def test_expired_delivery_stays_in_bell_but_is_not_sent(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.publish(notifications=[draft(expires_at=(NOW + timedelta(seconds=10)).isoformat())])
        self.assertEqual(self.store.claim_deliveries(NOW + timedelta(seconds=10)), [])
        self.assertEqual(self.store.list_notifications(ALICE)["unread_count"], 1)

    def test_leases_retry_backoff_and_completion(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.publish()
        item = self.store.claim_deliveries(NOW)[0]
        self.assertEqual(item["attempts"], 1)
        self.assertEqual(self.store.claim_deliveries(NOW + timedelta(seconds=59)), [])
        item = self.store.claim_deliveries(NOW + timedelta(seconds=60))[0]
        self.assertEqual(item["attempts"], 2)
        self.store.retry_delivery(item["id"], NOW + timedelta(seconds=60))
        self.assertEqual(self.store.claim_deliveries(NOW + timedelta(seconds=119)), [])
        item = self.store.claim_deliveries(NOW + timedelta(seconds=120))[0]
        self.assertEqual(item["attempts"], 3)
        self.store.complete_delivery(item["id"], NOW + timedelta(seconds=121))
        self.assertEqual(self.store.claim_deliveries(NOW + timedelta(days=1)), [])

    def test_attempt_limit_and_permanent_failure(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.publish(notifications=[draft("permanent"), draft("retry")])
        first, second = self.store.claim_deliveries(NOW)
        self.store.retry_delivery(first["id"], NOW, permanent=True)
        self.store.retry_delivery(second["id"], NOW)
        for attempt in range(2, 6):
            now = NOW + timedelta(seconds=1000 * attempt)
            deliveries = self.store.claim_deliveries(now)
            self.assertEqual(len(deliveries), 1)
            self.assertEqual(deliveries[0]["attempts"], attempt)
            self.store.retry_delivery(deliveries[0]["id"], now)
        self.assertEqual(self.store.claim_deliveries(NOW + timedelta(days=1)), [])

    def test_stale_reminders_are_cancelled_without_removing_history(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.publish(notifications=[draft("old"), draft("current"), draft("change", kind="schedule_changed")])
        self.store.cancel_stale_reminders(ALICE, {"current"})
        deliveries = self.store.claim_deliveries(NOW)
        self.assertEqual({d["notification"]["payload"]["lesson_id"] for d in deliveries}, {"current", "change"})
        self.assertEqual(len(self.store.list_notifications(ALICE)["items"]), 3)

    def test_separate_store_connections_cannot_claim_same_delivery(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.publish()
        other = NotificationStore(self.path)
        try:
            self.assertEqual(len(self.store.claim_deliveries(NOW)), 1)
            self.assertEqual(other.claim_deliveries(NOW), [])
        finally:
            other.close()

    def test_stale_cancellation_does_not_override_a_newer_snapshot(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.store.commit_observation(ALICE, None, start=NOW.date(), finish=NOW.date(),
                                      lessons=[], notifications=[draft()], now=NOW)
        self.store.cancel_stale_reminders(ALICE, set(), expected_version=2)
        self.assertEqual(len(self.store.claim_deliveries(NOW)), 1)

    def test_failed_old_telegram_target_does_not_remove_a_new_binding(self):
        self.link_telegram(chat_id="old-chat")
        self.link_telegram(token="new-link", chat_id="new-chat")
        self.store.unlink_telegram_target(ALICE, "old-chat")
        self.assertTrue(self.store.telegram_status(ALICE)["linked"])
        self.store.unlink_telegram_target(ALICE, "new-chat")
        self.assertFalse(self.store.telegram_status(ALICE)["linked"])

    def test_reminder_details_update_is_scoped_versioned_and_does_not_replay(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.store.commit_observation(ALICE, None, start=NOW.date(), finish=NOW.date(),
                                      lessons=[], notifications=[draft()], now=NOW)
        new_draft = draft(body="Новая аудитория 202", payload={"room": "202"})
        self.assertFalse(self.store.update_reminder_details(ALICE, [new_draft], expected_version=2))
        self.assertNotEqual(self.store.get_notification(ALICE, 1)["body"], new_draft["body"])
        self.assertTrue(self.store.update_reminder_details(ALICE, [new_draft, draft("not-existing")], expected_version=1))
        self.assertIsNone(self.store.get_notification(BOB, 1))
        self.assertEqual(self.store.get_notification(ALICE, 1)["payload"], {"room": "202"})
        deliveries = self.store.claim_deliveries(NOW)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["notification"]["body"], new_draft["body"])
        self.store.complete_delivery(deliveries[0]["id"], NOW)
        self.assertTrue(self.store.update_reminder_details(ALICE, [draft(body="Позже")], expected_version=1))
        self.assertEqual(self.store.claim_deliveries(NOW + timedelta(days=1)), [])
        self.assertEqual(len(self.store.list_notifications(ALICE)["items"]), 1)

    def test_delivery_is_rechecked_before_send_after_mute_or_target_changes(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.publish()
        self.assertFalse(self.store.delivery_is_active(1, NOW))
        item = self.store.claim_deliveries(NOW)[0]
        self.assertTrue(self.store.delivery_is_active(item["id"], NOW))
        self.store.set_settings(ALICE, False)
        self.store.set_settings(ALICE, True)
        self.assertFalse(self.store.delivery_is_active(item["id"], NOW))
        self.publish(notifications=[draft("new")])
        item = self.store.claim_deliveries(NOW)[0]
        self.assertTrue(self.store.delivery_is_active(item["id"], NOW))
        self.store.add_subscription(BOB, subscription(), NOW)
        self.assertFalse(self.store.delivery_is_active(item["id"], NOW))

    def test_delivery_recheck_rejects_expired_and_stale_reminders(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, subscription(), NOW)
        self.publish(notifications=[draft(expires_at=(NOW + timedelta(seconds=10)).isoformat())])
        item = self.store.claim_deliveries(NOW)[0]
        self.assertFalse(self.store.delivery_is_active(item["id"], NOW + timedelta(seconds=10)))
        self.publish(notifications=[draft("stale")])
        item = self.store.claim_deliveries(NOW)[0]
        self.assertTrue(self.store.delivery_is_active(item["id"], NOW))
        self.store.cancel_stale_reminders(ALICE, set())
        self.assertFalse(self.store.delivery_is_active(item["id"], NOW))


if __name__ == "__main__":
    unittest.main()
