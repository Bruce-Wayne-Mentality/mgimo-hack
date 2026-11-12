"""Observable notification behavior, without a real clock or external network."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from hse_schedule.directory import Student, StudentDirectory
from hse_schedule.errors import SourceUnavailable
from hse_schedule.notification_store import NotificationStore
from hse_schedule.notifications import NotificationEngine
from hse_schedule.parser import parse_lessons
from hse_schedule.service import ScheduleService


BASE = datetime(2026, 11, 12, 6, tzinfo=timezone.utc)
ALICE = "alice@example.test"


def lesson(source_id="100", *, starts=BASE + timedelta(minutes=30), **changes):
    local = starts.astimezone(ZoneInfo("Europe/Moscow"))
    value = {
        "lessonOid": source_id, "date": local.strftime("%Y.%m.%d"),
        "beginLesson": local.strftime("%H:%M"),
        "endLesson": (local + timedelta(minutes=80)).strftime("%H:%M"),
        "discipline": "Математика", "kindOfWork": "Лекция", "lecturer": "Лектор Демо",
        "auditorium": "101", "building": "Учебный корпус",
        "groupOid": "1000", "group": "Учебная группа",
    }
    value.update(changes)
    return parse_lessons([value])[0]


class FakeClock:
    def __init__(self):
        self.now = BASE

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)
        return self.now


class MutableSource:
    timezone = "Europe/Moscow"

    def __init__(self):
        self.lessons = ()
        self.error = None

    def schedule(self, **kwargs):
        if self.error:
            raise self.error
        return tuple(item for item in self.lessons if kwargs["start"] <= item.date <= kwargs["finish"])


class NotificationEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "notifications.sqlite3"
        self.store = NotificationStore(self.path)
        self.clock = FakeClock()
        self.source = MutableSource()
        directory = StudentDirectory([Student(ALICE, "Алиса", group_oids=("1000",))])
        self.service = ScheduleService(directory, self.source)
        self.engine = NotificationEngine(self.service, self.store)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def refresh(self, *lessons):
        self.source.lessons = lessons
        return self.engine.refresh_schedules(self.clock.now)

    def inbox(self, kind=None):
        items = self.store.list_notifications(ALICE)["items"]
        return [item for item in items if kind is None or item["kind"] == kind]

    def enable(self):
        self.store.set_settings(ALICE, True)
        self.store.add_subscription(ALICE, {
            "endpoint": "https://push.example.test/one", "keys": {"p256dh": "key", "auth": "secret"}
        }, self.clock.now)

    def test_first_successful_snapshot_is_not_a_schedule_change(self):
        self.assertEqual(self.refresh(lesson()), {"refreshed": 1, "failed": 0})
        self.assertEqual(self.inbox(), [])
        self.assertEqual(len(self.store.load_snapshot(ALICE)["lessons"]), 1)

    def test_reminder_threshold_is_ten_minutes_and_never_after_start(self):
        item = lesson()
        self.refresh(item)
        self.engine.emit_reminders(self.clock.advance(minutes=19, seconds=59))
        self.assertEqual(self.inbox(), [])
        self.engine.emit_reminders(self.clock.advance(seconds=1))
        reminders = self.inbox("reminder")
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0]["payload"]["scheduled_for"], "2026-11-12T09:20:00+03:00")
        self.assertEqual(self.store.claim_deliveries(self.clock.now), [])
        self.engine.emit_reminders(self.clock.advance(minutes=10))
        self.assertEqual(len(self.inbox("reminder")), 1)

    def test_reminder_repeated_ticks_and_restart_do_not_duplicate(self):
        self.refresh(lesson())
        self.clock.advance(minutes=20)
        self.engine.emit_reminders(self.clock.now)
        self.engine.emit_reminders(self.clock.advance(seconds=1))
        self.store.close()
        self.store = NotificationStore(self.path)
        self.engine = NotificationEngine(self.service, self.store)
        self.engine.emit_reminders(self.clock.advance(seconds=1))
        self.assertEqual(len(self.inbox()), 1)

    def test_enabled_reminder_appears_in_bell_and_delivery_outbox(self):
        self.enable()
        self.refresh(lesson())
        self.engine.emit_reminders(self.clock.advance(minutes=20))
        deliveries = self.store.claim_deliveries(self.clock.now)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["channel"], "webpush")
        self.assertEqual(deliveries[0]["notification"]["id"], self.inbox()[0]["id"])

    def test_changed_room_time_and_teacher_are_each_detected_once(self):
        original = lesson()
        self.refresh(original)
        updates = (
            lesson(auditorium="202"),
            lesson(auditorium="202", lecturer="Другой преподаватель"),
            lesson(starts=BASE + timedelta(hours=1), auditorium="202", lecturer="Другой преподаватель"),
        )
        for index, updated in enumerate(updates, start=1):
            self.clock.advance(seconds=10)
            self.refresh(updated)
            self.refresh(updated)
            changes = self.inbox("schedule_changed")
            self.assertEqual(len(changes), index)
            self.assertIsNotNone(changes[0]["payload"]["before"])
            self.assertIsNotNone(changes[0]["payload"]["after"])
        self.assertEqual(len(self.inbox()), 3)

    def test_repeated_source_ids_on_different_days_preserve_occurrences(self):
        today = lesson()
        tomorrow = lesson(starts=BASE + timedelta(days=1, minutes=30))
        self.refresh(today, tomorrow)
        changed_tomorrow = lesson(starts=BASE + timedelta(days=1, minutes=30), auditorium="202")
        self.refresh(today, changed_tomorrow)
        changes = self.inbox()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["kind"], "schedule_changed")
        self.assertEqual(changes[0]["payload"]["before"]["date"], tomorrow.date.isoformat())
        self.assertEqual(len(self.store.load_snapshot(ALICE)["lessons"]), 2)

    def test_additions_and_cancellations_are_separate_from_baseline(self):
        original = lesson()
        added = lesson("200", starts=BASE + timedelta(hours=2), discipline="Экономика")
        self.refresh(original)
        self.refresh(original, added)
        self.assertEqual([item["kind"] for item in self.inbox()], ["schedule_added"])
        self.refresh(added)
        self.assertEqual([item["kind"] for item in self.inbox()], ["schedule_cancelled", "schedule_added"])
        self.assertEqual(self.inbox()[0]["payload"]["before"]["source_lesson_id"], "100")

    def test_failed_source_retains_snapshot_and_does_not_cancel_classes(self):
        self.refresh(lesson())
        snapshot = self.store.load_snapshot(ALICE)
        self.source.error = SourceUnavailable("network down")
        with self.assertLogs("hse_schedule.notifications", level="WARNING"):
            result = self.engine.refresh_schedules(self.clock.now)
        self.assertEqual(result, {"refreshed": 0, "failed": 1})
        self.assertEqual(self.store.load_snapshot(ALICE), snapshot)
        self.assertEqual(self.inbox(), [])
        self.engine.emit_reminders(self.clock.advance(minutes=20))
        self.assertEqual(len(self.inbox("reminder")), 1)

    def test_rolling_window_edges_do_not_create_addition_or_cancellation_noise(self):
        first_day = lesson()
        shared_day = lesson("200", starts=BASE + timedelta(days=3, minutes=30))
        added_edge = lesson("300", starts=BASE + timedelta(days=7, minutes=30))
        self.refresh(first_day, shared_day)
        self.clock.advance(days=1)
        self.refresh(shared_day, added_edge)
        self.assertEqual(self.inbox(), [])

    def test_moved_class_cancels_old_pending_reminder_and_gets_new_one_at_new_time(self):
        self.enable()
        self.refresh(lesson())
        self.engine.emit_reminders(self.clock.advance(minutes=20))
        moved = lesson(starts=BASE + timedelta(hours=1))
        self.refresh(moved)
        deliveries = self.store.claim_deliveries(self.clock.now)
        self.assertEqual([item["notification"]["kind"] for item in deliveries], ["schedule_changed"])
        self.store.complete_delivery(deliveries[0]["id"], self.clock.now)
        self.engine.emit_reminders(self.clock.advance(minutes=30))
        deliveries = self.store.claim_deliveries(self.clock.now)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["notification"]["kind"], "reminder")
        self.assertEqual(len(self.inbox("reminder")), 2)

    def test_removed_class_cancels_pending_reminder_but_keeps_bell_history(self):
        self.enable()
        self.refresh(lesson())
        self.engine.emit_reminders(self.clock.advance(minutes=20))
        self.refresh()
        deliveries = self.store.claim_deliveries(self.clock.now)
        self.assertEqual([item["notification"]["kind"] for item in deliveries], ["schedule_cancelled"])
        self.assertEqual(len(self.inbox("reminder")), 1)

    def test_reenabling_does_not_push_muted_reminder_backlog(self):
        self.refresh(lesson())
        self.engine.emit_reminders(self.clock.advance(minutes=20))
        self.enable()
        self.engine.emit_reminders(self.clock.advance(seconds=1))
        self.assertEqual(len(self.inbox("reminder")), 1)
        self.assertEqual(self.store.claim_deliveries(self.clock.now), [])

    def test_pending_reminder_uses_latest_room_without_an_extra_reminder(self):
        self.enable()
        self.refresh(lesson())
        self.engine.emit_reminders(self.clock.advance(minutes=20))
        reminder_id = self.inbox("reminder")[0]["id"]
        self.refresh(lesson(auditorium="202"))
        reminder = self.store.get_notification(ALICE, reminder_id)
        self.assertEqual(reminder["payload"]["lesson"]["room"], "202")
        self.assertIn("202", reminder["body"])
        self.assertEqual(len(self.inbox("reminder")), 1)
        deliveries = self.store.claim_deliveries(self.clock.now)
        self.assertEqual(len([item for item in deliveries if item["notification"]["kind"] == "reminder"]), 1)


if __name__ == "__main__":
    unittest.main()
