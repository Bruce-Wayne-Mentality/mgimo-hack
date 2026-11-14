"""Demo lessons stay visible across dates without changing imported schedules."""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from hse_schedule.api import create_app
from hse_schedule.cli import DEMO_TOKENS, _service
from hse_schedule.errors import ConfigurationError, InvalidPayload
from hse_schedule.notification_store import NotificationStore
from hse_schedule.notifications import NotificationEngine
from hse_schedule.service import FixtureSource, WeeklyDemoSource


ROOT = Path(__file__).resolve().parents[1]
STUDENTS = ROOT / "examples/students.json"
LESSONS = ROOT / "examples/lessons.json"
ALICE = "alice@demo-university.test"
BOB = "bob@demo-university.test"


class WeeklyDemoTests(unittest.TestCase):
    def setUp(self):
        self.service = _service(STUDENTS, LESSONS, demo=True)

    def test_each_student_has_four_personal_lessons_for_complete_weeks(self):
        for monday in (date(2026, 11, 9), date(2026, 11, 16), date(2026, 12, 28), date(2027, 1, 4)):
            sunday = monday + timedelta(days=6)
            with self.subTest(monday=monday):
                alice = self.service.get_schedule(ALICE, monday, sunday)
                bob = self.service.get_schedule(BOB, monday, sunday)
                self.assertEqual(len(alice), 4)
                self.assertEqual(len(bob), 4)
                self.assertEqual(len(set(alice) & set(bob)), 2)
                self.assertEqual({g.oid for row in alice for g in row.groups}, {"1000", "1001"})
                self.assertEqual({g.oid for row in bob for g in row.groups}, {"1000", "1002"})
                self.assertTrue(all(monday <= row.date <= sunday for row in (*alice, *bob)))

    def test_partial_week_still_respects_the_requested_days(self):
        # Friday is genuinely empty for Alice. Showing the complete week is a
        # UI decision, not permission to leak lessons outside an API interval.
        friday = date(2026, 11, 13)
        self.assertEqual(self.service.get_schedule(ALICE, friday, friday), ())
        bob = self.service.get_schedule(BOB, friday, friday)
        self.assertEqual(len(bob), 1)
        self.assertEqual(bob[0].date, friday)

    def test_ids_are_stable_across_overlapping_requests_and_restart(self):
        start, finish = date(2026, 11, 16), date(2026, 11, 22)
        first = self.service.get_schedule(ALICE, start, finish)
        overlap = self.service.get_schedule(ALICE, start - timedelta(days=2), finish + timedelta(days=1))
        restarted = _service(STUDENTS, LESSONS, demo=True)
        self.assertEqual(first, restarted.get_schedule(ALICE, start, finish))
        self.assertTrue(set(first).issubset(overlap))
        following = self.service.get_schedule(ALICE, start + timedelta(days=7), finish + timedelta(days=7))
        self.assertTrue({row.id for row in first}.isdisjoint(row.id for row in following))
        self.assertEqual({row.source_lesson_id for row in first}, {row.source_lesson_id for row in following})

    def test_saved_exports_keep_exact_dates_and_are_not_repeated(self):
        service = _service(STUDENTS, LESSONS)
        self.assertIsInstance(service.source, FixtureSource)
        self.assertNotIsInstance(service.source, WeeklyDemoSource)
        self.assertEqual(service.get_schedule(ALICE, date(2026, 11, 13), date(2026, 11, 20)), ())
        self.assertEqual(len(service.get_schedule(BOB, date(2026, 11, 13), date(2026, 11, 20))), 1)
        self.assertEqual(service.get_schedule(BOB, date(2026, 11, 16), date(2026, 11, 22)), ())

    def test_actual_api_returns_full_demo_weeks_for_both_accounts(self):
        app = create_app(self.service, DEMO_TOKENS, demo=True)
        with TestClient(app) as client:
            for token in DEMO_TOKENS:
                response = client.get(
                    "/api/me/schedule", params={"start": "2026-11-16", "finish": "2026-11-22"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()["lessons"]), 4)
                self.assertTrue(response.json()["demo"])

    def test_invalid_or_ambiguous_demo_template_is_rejected(self):
        payload = json.loads(LESSONS.read_text())
        payload["Lessons"][-1]["date"] = "2026.11.20"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "template.json"
            path.write_text(json.dumps(payload))
            with self.assertRaises(ConfigurationError):
                WeeklyDemoSource(path).schedule(start=date(2026, 11, 16), finish=date(2026, 11, 22), group_oid="1000")
            path.write_text('{"Lessons":[],"StatusCode":{"Code":1}}')
            with self.assertRaises(InvalidPayload):
                WeeklyDemoSource(path)

    def test_demo_rejects_unconfigured_subject_and_bad_interval(self):
        source = self.service.source
        start, finish = date(2026, 11, 16), date(2026, 11, 22)
        for subject in ({}, {"student_oid": "123"}):
            with self.subTest(subject=subject), self.assertRaises(ConfigurationError):
                source.schedule(start=start, finish=finish, **subject)
        with self.assertRaises(ValueError):
            source.schedule(start=finish, finish=start, group_oid="1000")

    def test_week_rollover_does_not_generate_false_changes_or_repeat_reminders(self):
        store = NotificationStore(":memory:")
        try:
            engine = NotificationEngine(self.service, store)
            engine.refresh_schedules(datetime(2026, 11, 13, 6, tzinfo=timezone.utc))
            engine.refresh_schedules(datetime(2026, 11, 14, 6, tzinfo=timezone.utc))
            self.assertEqual(store.list_notifications(ALICE)["items"], [])
            self.assertEqual(store.list_notifications(BOB)["items"], [])
            reminder_time = datetime(2026, 11, 16, 6, 20, tzinfo=timezone.utc)
            engine.refresh_schedules(reminder_time)
            engine.emit_reminders(reminder_time)
            NotificationEngine(self.service, store).emit_reminders(reminder_time)
            for email in (ALICE, BOB):
                items = store.list_notifications(email)["items"]
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["kind"], "reminder")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
