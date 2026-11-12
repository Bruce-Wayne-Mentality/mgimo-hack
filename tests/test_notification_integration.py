"""The actual application lifespan refreshes schedules and fills the bell."""

import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from hse_schedule.api import create_app
from hse_schedule.directory import Student, StudentDirectory
from hse_schedule.notification_store import NotificationStore
from hse_schedule.service import FixtureSource, ScheduleService


class NotificationAppIntegrationTests(unittest.TestCase):
    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Background notification worker did not finish its observation")

    def test_app_worker_detects_fixture_edits_and_persists_a_muted_personal_event(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "lessons.json"
            raw = [{
                "lessonOid": 100, "date": datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y.%m.%d"),
                "beginLesson": "09:30", "endLesson": "10:50", "discipline": "Экономика",
                "groupOid": 1000, "group": "Учебная группа", "auditorium": "101",
            }]
            fixture.write_text(json.dumps(raw), encoding="utf-8")
            directory = StudentDirectory([
                Student("alice@example.test", "Алиса", group_oids=("1000",)),
                Student("bob@example.test", "Борис", group_oids=("1001",)),
            ])
            service = ScheduleService(directory, FixtureSource(fixture))
            store = NotificationStore(root / "notifications.sqlite3")
            try:
                app = create_app(
                    service, {"alice": "alice@example.test", "bob": "bob@example.test"},
                    notification_store=store, run_workers=True, refresh_interval=0.02,
                )
                with TestClient(app) as client:
                    self.wait_for(lambda: store.load_snapshot("alice@example.test") is not None)
                    raw[0]["auditorium"] = "202"
                    replacement = root / "replacement.json"
                    replacement.write_text(json.dumps(raw), encoding="utf-8")
                    replacement.replace(fixture)
                    self.wait_for(lambda: any(
                        item["kind"] == "schedule_changed"
                        for item in store.list_notifications("alice@example.test")["items"]
                    ))
                    response = client.get("/api/me/notifications", headers={"Authorization": "Bearer alice"})
                    self.assertEqual(response.status_code, 200)
                    changes = [item for item in response.json()["items"] if item["kind"] == "schedule_changed"]
                    self.assertEqual(len(changes), 1)
                    self.assertEqual(changes[0]["payload"]["after"]["room"], "202")
                    self.assertEqual(store.claim_deliveries(datetime.now(timezone.utc)), [])
                    other = client.get("/api/me/notifications", headers={"Authorization": "Bearer bob"})
                    self.assertEqual(other.json()["items"], [])
                self.assertEqual(len(store.list_notifications("alice@example.test")["items"]), len(response.json()["items"]))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
