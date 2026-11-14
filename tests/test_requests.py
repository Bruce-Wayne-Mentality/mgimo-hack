"""Requests and certificates (C4: FR-REQ-1..5, K2 tracker, S1 queue, section 10.2)."""

import asyncio
import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from hse_schedule.accounts.models import AuditLog
from hse_schedule.accounts.router import AuthSettings
from hse_schedule.accounts.seed import DEMO_ACCOUNTS, seed_demo
from hse_schedule.accounts.service import AuthService
from hse_schedule.api import create_app
from hse_schedule.db import Database
from hse_schedule.directory import StudentDirectory
from hse_schedule.migrate import upgrade
from hse_schedule.service import FixtureSource, ScheduleService
from hse_schedule.student_requests.catalog import validate_payload, PayloadError
from hse_schedule.student_requests.models import RequestEvent, StudentRequest
from hse_schedule.student_requests.seed import seed_demo_requests, seed_request_types
from hse_schedule.student_requests.service import RequestService, add_business_days

from tests.test_auth import reset_postgres

ROOT = Path(__file__).resolve().parents[1]
ANNA = {"login": "student.anna", "password": "Demo-Anna-2026"}
BORIS = {"login": "student.boris", "password": "Demo-Boris-2026"}
VERA = {"login": "student.vera", "password": "Demo-Vera-2026"}
STAFF = {"login": "staff.deanery", "password": "Demo-Staff-2026"}
ADMIN = {"login": "admin.demo", "password": "Demo-Admin-2026"}
CERT = {"type_code": "CERT_STUDY", "payload": {"destination": "В банк", "copies": 2}}
MIL = {"type_code": "CERT_MIL", "payload": {"purpose": "deferment", "office": "Военкомат №1"}}


class RequestTestCase(unittest.TestCase):
    demo_requests = False

    def setUp(self):
        self.temporary = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temporary, ignore_errors=True)
        self.url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(self.temporary / 'app.sqlite3').as_posix()}"
        if os.environ.get("TEST_DATABASE_URL"):
            reset_postgres(self.url)
        upgrade(self.url)
        self.database = Database(self.url, pooled=False)
        # Wednesday 11:00 Moscow time.
        self.now = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)

        async def seed():
            await seed_demo(self.database)
            await seed_request_types(self.database)
            if self.demo_requests:
                await seed_demo_requests(self.database, now=self.now)

        asyncio.run(seed())
        self.sent = []
        clock = lambda: self.now  # noqa: E731
        self.requests = RequestService(self.database, notify=lambda email, drafts: self.sent.append((email, drafts)), clock=clock)
        service = ScheduleService(StudentDirectory.from_file(ROOT / "examples/students.json"), FixtureSource(ROOT / "examples/lessons.json"))
        self.app = create_app(
            service, {}, demo=True,
            auth=AuthService(self.database, clock=clock),
            auth_settings=AuthSettings(secret=b"s" * 40, demo=True),
            demo_accounts=DEMO_ACCOUNTS,
            request_service=self.requests,
        )

    def client(self, account=ANNA):
        client = TestClient(self.app, base_url="https://testserver", follow_redirects=False)
        response = client.post("/api/auth/login", json=account)
        self.assertEqual(response.status_code, 200, response.text)
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client

    def create(self, client, body=MIL, key=None):
        headers = {"Idempotency-Key": key} if key else {}
        return client.post("/api/requests", json=body, headers=headers)

    def rows(self, statement):
        async def run():
            async with self.database.session() as db:
                return (await db.execute(statement)).scalars().all()

        return asyncio.run(run())


class CatalogTests(RequestTestCase):
    def test_catalogue_has_eight_types_with_forms(self):
        items = self.client().get("/api/request-types").json()["items"]
        self.assertEqual([item["code"] for item in items],
                         ["CERT_STUDY", "TRANSCRIPT", "CERT_INTERN", "CERT_MIL", "RETAKE", "TRANSFER", "ACAD_LEAVE", "AID"])
        self.assertTrue(all(item["fields"] for item in items))
        self.assertEqual(self.client().get("/api/request-types").status_code, 200)
        anonymous = TestClient(self.app, base_url="https://testserver")
        self.assertEqual(anonymous.get("/api/request-types").status_code, 401)

    def test_payload_validation_is_strict(self):
        fields = [
            {"name": "title", "label": "T", "kind": "text", "required": True, "max_length": 5},
            {"name": "copies", "label": "C", "kind": "int", "required": True, "min": 1, "max": 3},
            {"name": "lang", "label": "L", "kind": "select", "required": False, "options": [{"value": "ru", "label": "RU"}]},
            {"name": "period_from", "label": "F", "kind": "date", "required": False},
            {"name": "period_to", "label": "T", "kind": "date", "required": False},
        ]
        self.assertEqual(validate_payload(fields, {"title": " ok ", "copies": "2"}), {"title": "ok", "copies": 2})
        for payload, field in (
            ({"copies": 1}, "title"),
            ({"title": "toolong", "copies": 1}, "title"),
            ({"title": "a", "copies": 9}, "copies"),
            ({"title": "a", "copies": True}, "copies"),
            ({"title": "a", "copies": 1, "lang": "de"}, "lang"),
            ({"title": "a", "copies": 1, "period_from": "2026-13-01"}, "period_from"),
            ({"title": "a", "copies": 1, "period_from": "2026-11-10", "period_to": "2026-11-01"}, "period_to"),
            ({"title": "a", "copies": 1, "extra": "x"}, "extra"),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(PayloadError) as caught:
                    validate_payload(fields, payload)
                self.assertIn(field, caught.exception.fields)

    def test_sla_counts_business_days_in_moscow(self):
        friday = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(add_business_days(friday, 2).astimezone(timezone(timedelta(hours=3))).date().isoformat(), "2026-11-24")
        self.assertEqual(add_business_days(friday, 0), friday + timedelta(hours=1))


class StudentFlowTests(RequestTestCase):
    def test_create_assigns_number_due_date_and_history(self):
        client = self.client()
        response = self.create(client)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertRegex(body["number"], r"^ДК-2026-\d{6}$")
        self.assertEqual(body["status"], "submitted")
        self.assertEqual(body["status_label"], "Принята")
        self.assertEqual([step["status"] for step in body["track"]], ["submitted", "in_review", "ready"])
        self.assertIsNotNone(body["track"][0]["at"])
        self.assertEqual(body["fields"], [{"name": "purpose", "label": "Цель", "value": "Отсрочка"},
                                          {"name": "office", "label": "Военкомат", "value": "Военкомат №1"}])
        self.assertTrue(body["can_cancel"])
        second = self.create(client, MIL).json()
        first_no = int(body["number"].rsplit("-", 1)[1])
        self.assertEqual(int(second["number"].rsplit("-", 1)[1]), first_no + 1)
        self.assertIn("request.created", self.rows(select(AuditLog.action)))

    def test_same_idempotency_key_returns_the_same_request(self):
        client = self.client()
        first = self.create(client, key="key-12345678")
        again = self.create(client, key="key-12345678")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(first.json()["id"], again.json()["id"])
        self.assertEqual(len(client.get("/api/requests").json()["items"]), 1)
        # The same key from another student is independent.
        other = self.create(self.client(BORIS), key="key-12345678")
        self.assertEqual(other.status_code, 201)
        self.assertNotEqual(other.json()["id"], first.json()["id"])

    def test_invalid_form_and_unknown_type_are_422(self):
        client = self.client()
        bad = self.create(client, {"type_code": "CERT_MIL", "payload": {"purpose": "x"}})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(set(bad.json()["error"]["fields"]), {"purpose", "office"})
        self.assertEqual(self.create(client, {"type_code": "NOPE", "payload": {}}).status_code, 422)
        self.assertEqual(client.get("/api/requests").json()["items"], [])

    def test_simple_certificate_is_issued_automatically(self):
        body = self.create(self.client(), CERT).json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual([event["to"] for event in body["events"]], ["submitted", "in_review", "ready"])
        self.assertTrue(all(event["by_system"] for event in body["events"][1:]))
        self.assertTrue(all(step["at"] for step in body["track"]))
        self.assertFalse(body["can_cancel"])
        self.assertEqual(self.sent[-1][0], "anna@demo-university.test")
        self.assertIn("Готова", self.sent[-1][1][0]["title"])
        self.assertEqual(self.sent[-1][1][0]["payload"]["link"], f"/requests/{body['id']}")

    def test_students_never_see_each_others_requests(self):
        mine = self.create(self.client(), MIL).json()
        boris = self.client(BORIS)
        for method, path in (("get", f"/api/requests/{mine['id']}"), ("post", f"/api/requests/{mine['id']}/cancel")):
            response = getattr(boris, method)(path)
            self.assertEqual(response.status_code, 404, path)
        reply = boris.post(f"/api/requests/{mine['id']}/comments", json={"body": "hi"})
        self.assertEqual(reply.status_code, 404)
        self.assertEqual(boris.get("/api/requests").json()["items"], [])
        self.assertEqual(boris.get("/api/requests/not-a-uuid").status_code, 404)

    def test_cancel_only_from_submitted_or_needs_info(self):
        client = self.client()
        created = self.create(client).json()
        cancelled = client.post(f"/api/requests/{created['id']}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        again = client.post(f"/api/requests/{created['id']}/cancel")
        self.assertEqual(again.status_code, 409)
        ready = self.create(client, CERT).json()
        self.assertEqual(client.post(f"/api/requests/{ready['id']}/cancel").status_code, 409)

    def test_changing_requests_require_csrf(self):
        client = self.client()
        response = client.post("/api/requests", json=MIL, headers={"X-CSRF-Token": "bad"})
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_file_requests(self):
        response = self.create(self.client(STAFF))
        self.assertEqual(response.status_code, 403)


class StaffFlowTests(RequestTestCase):
    def test_full_cycle_with_needs_info_and_reply(self):
        anna, staff = self.client(), self.client(STAFF)
        request_id = self.create(anna).json()["id"]
        queue = staff.get("/api/staff/requests", params={"status": "open"}).json()["items"]
        self.assertIn(request_id, [item["id"] for item in queue])

        taken = staff.post(f"/api/staff/requests/{request_id}/transition", json={"to": "in_review"})
        self.assertEqual(taken.json()["status"], "in_review")
        no_note = staff.post(f"/api/staff/requests/{request_id}/transition", json={"to": "needs_info"})
        self.assertEqual(no_note.status_code, 422)
        asked = staff.post(f"/api/staff/requests/{request_id}/transition", json={"to": "needs_info", "note": "Нужен номер свидетельства"})
        self.assertEqual(asked.json()["status"], "needs_info")
        self.assertIn("Нужен номер свидетельства", self.sent[-1][1][0]["body"])

        student_view = anna.get(f"/api/requests/{request_id}").json()
        self.assertTrue(student_view["can_reply"])
        replied = anna.post(f"/api/requests/{request_id}/comments", json={"body": "Номер 12345"})
        self.assertEqual(replied.json()["status"], "in_review")
        self.assertEqual(replied.json()["comments"][-1]["author"], "Вы")

        ready = staff.post(f"/api/staff/requests/{request_id}/transition", json={"to": "ready", "note": "Справка готова, заберите в 214"})
        self.assertEqual(ready.json()["status"], "ready")
        final = anna.get(f"/api/requests/{request_id}").json()
        self.assertEqual(final["result_note"], "Справка готова, заберите в 214")
        self.assertEqual([e["to"] for e in final["events"]], ["submitted", "in_review", "needs_info", "in_review", "ready"])
        self.assertFalse(final["can_reply"])
        self.assertEqual(anna.post(f"/api/requests/{request_id}/comments", json={"body": "ещё"}).status_code, 409)

    def test_invalid_transitions_are_409(self):
        anna, staff = self.client(), self.client(STAFF)
        request_id = self.create(anna).json()["id"]
        for target in ("ready", "rejected", "needs_info"):
            response = staff.post(f"/api/staff/requests/{request_id}/transition", json={"to": target, "note": "x"})
            self.assertEqual(response.status_code, 409, target)
        staff.post(f"/api/staff/requests/{request_id}/transition", json={"to": "in_review"})
        self.assertEqual(staff.post(f"/api/staff/requests/{request_id}/transition", json={"to": "in_review"}).status_code, 409)
        rejected = staff.post(f"/api/staff/requests/{request_id}/transition", json={"to": "rejected", "note": "Нет оснований"})
        self.assertEqual(rejected.json()["status"], "rejected")
        self.assertEqual(staff.post(f"/api/staff/requests/{request_id}/transition", json={"to": "in_review"}).status_code, 409)
        bad_target = staff.post(f"/api/staff/requests/{request_id}/transition", json={"to": "cancelled"})
        self.assertEqual(bad_target.status_code, 422)

    def test_internal_notes_stay_with_staff(self):
        anna, staff = self.client(), self.client(STAFF)
        request_id = self.create(anna).json()["id"]
        staff.post(f"/api/requests/{request_id}/comments", json={"body": "Проверить документы", "internal": True})
        staff.post(f"/api/requests/{request_id}/comments", json={"body": "Здравствуйте!"})
        student_comments = anna.get(f"/api/requests/{request_id}").json()["comments"]
        self.assertEqual([c["body"] for c in student_comments], ["Здравствуйте!"])
        self.assertEqual(student_comments[0]["author"], "Деканат")
        staff_comments = staff.get(f"/api/staff/requests/{request_id}").json()["comments"]
        self.assertEqual(len(staff_comments), 2)
        self.assertEqual(anna.post(f"/api/requests/{request_id}/comments", json={"body": "x", "internal": True}).status_code, 403)

    def test_staff_scope_is_own_faculty_and_types(self):
        staff, admin = self.client(STAFF), self.client(ADMIN)
        vera_request = self.create(self.client(VERA)).json()["id"]  # IT faculty, staff is ECON
        aid_request = self.create(self.client(BORIS), {"type_code": "AID", "payload": {"basis": "Сложная ситуация"}}).json()["id"]  # not in scopes
        self.assertEqual(staff.get(f"/api/staff/requests/{vera_request}").status_code, 404)
        self.assertEqual(staff.get(f"/api/staff/requests/{aid_request}").status_code, 404)
        self.assertEqual(staff.post(f"/api/staff/requests/{vera_request}/transition", json={"to": "in_review"}).status_code, 404)
        ids = [item["id"] for item in staff.get("/api/staff/requests").json()["items"]]
        self.assertNotIn(vera_request, ids)
        self.assertNotIn(aid_request, ids)
        admin_ids = [item["id"] for item in admin.get("/api/staff/requests").json()["items"]]
        self.assertIn(vera_request, admin_ids)
        self.assertEqual(self.client().get("/api/staff/requests").status_code, 403)
        self.assertEqual(self.client().get(f"/api/staff/requests/{vera_request}").status_code, 404)


class DemoSeedTests(RequestTestCase):
    demo_requests = True

    def test_demo_requests_cover_the_jury_story(self):
        anna = {item["type"]["code"]: item["status"] for item in self.client().get("/api/requests").json()["items"]}
        self.assertEqual(anna, {"CERT_STUDY": "ready", "CERT_INTERN": "in_review"})
        boris = {item["type"]["code"]: item["status"] for item in self.client(BORIS).get("/api/requests").json()["items"]}
        self.assertEqual(boris, {"CERT_MIL": "needs_info", "RETAKE": "submitted"})
        self.assertEqual(self.client(VERA).get("/api/requests").json()["items"], [])
        overdue = self.client(STAFF).get("/api/staff/requests", params={"overdue": "true"}).json()["items"]
        self.assertEqual([item["type"]["code"] for item in overdue], ["RETAKE"])
        numbers = [item.number for item in self.rows(select(StudentRequest))]
        self.assertTrue(all(re.match(r"^ДК-2026-\d{6}$", number) for number in numbers))
        self.assertEqual(len(set(numbers)), 4)
        self.assertGreaterEqual(len(self.rows(select(RequestEvent))), 9)

        async def again():
            return await seed_demo_requests(self.database, now=self.now)

        self.assertEqual(asyncio.run(again()), 0)
        # A new request continues the numbering after the demo ones.
        created = self.create(self.client(VERA)).json()
        self.assertEqual(created["number"], "ДК-2026-000005")


if __name__ == "__main__":
    unittest.main()
