from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from hse_schedule.api import create_app
from hse_schedule.directory import StudentDirectory
from hse_schedule.errors import ConfigurationError, InvalidPayload, SourceUnavailable, UnknownStudent
from hse_schedule.service import FixtureSource, ScheduleService


class PersonalScheduleAPITests(unittest.TestCase):
    def setUp(self):
        self.students = {
            "alice@example.test": SimpleNamespace(email="alice@example.test", name="Алиса"),
            "bob@example.test": SimpleNamespace(email="bob@example.test", name="Борис"),
        }
        self.service = Mock()
        self.service.timezone = "Europe/Moscow"
        self.service.directory.get.side_effect = self._student
        self.service.get_schedule.side_effect = self._lessons
        self.app = create_app(
            self.service,
            {"alice-token": "alice@example.test", "bob-token": "bob@example.test"},
            demo=True,
        )
        self.client = TestClient(self.app)
        self.headers = {"Authorization": "Bearer alice-token"}
        self.dates = {"start": "2026-11-09", "finish": "2026-11-15"}

    def _student(self, email):
        if email not in self.students:
            raise UnknownStudent(email)
        return self.students[email]

    @staticmethod
    def _lessons(email, _start, _finish):
        return (SimpleNamespace(to_dict=lambda: {"id": email, "title": "Личная пара"}),)

    def test_health_needs_no_identity_and_never_loads_schedule(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "demo": True})
        self.service.get_schedule.assert_not_called()
        self.service.directory.get.assert_not_called()

    def test_personal_endpoints_require_valid_bearer(self):
        for path in ("/api/me", "/api/me/schedule"):
            for authorization in (None, "Bearer wrong", "Basic alice-token", "Bearer"):
                with self.subTest(path=path, authorization=authorization):
                    headers = {} if authorization is None else {"Authorization": authorization}
                    response = self.client.get(path, params=self.dates, headers=headers)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
                    self.assertNotIn("alice@example.test", response.text)
        self.service.get_schedule.assert_not_called()

    def test_current_identity_comes_from_token(self):
        response = self.client.get(
            "/api/me", params={"email": "bob@example.test"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"email": "alice@example.test", "name": "Алиса"})
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_schedule_cannot_switch_account_using_query_email(self):
        response = self.client.get(
            "/api/me/schedule",
            params={**self.dates, "email": "bob@example.test"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["student"]["email"], "alice@example.test")
        self.assertEqual(body["lessons"][0]["id"], "alice@example.test")
        self.assertTrue(body["demo"])
        self.assertEqual(body["timezone"], "Europe/Moscow")
        self.service.get_schedule.assert_called_once_with(
            "alice@example.test", date(2026, 11, 9), date(2026, 11, 15)
        )

    def test_second_account_receives_its_own_schedule(self):
        response = self.client.get(
            "/api/me/schedule",
            params=self.dates,
            headers={"Authorization": "Bearer bob-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lessons"][0]["id"], "bob@example.test")
        self.assertNotIn("alice@example.test", response.text)

    def test_invalid_or_missing_dates_are_rejected_before_loading(self):
        ranges = (
            {},
            {"start": "2026-11-09"},
            {"start": "not-a-date", "finish": "2026-11-15"},
            {"start": "2026-11-16", "finish": "2026-11-15"},
            {"start": "2026-11-01", "finish": "2026-12-02"},
        )
        for dates in ranges:
            with self.subTest(dates=dates):
                response = self.client.get("/api/me/schedule", params=dates, headers=self.headers)
                self.assertEqual(response.status_code, 422)
        self.service.get_schedule.assert_not_called()

    def test_thirty_one_days_inclusive_is_allowed(self):
        response = self.client.get(
            "/api/me/schedule",
            params={"start": "2026-11-01", "finish": "2026-12-01"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)

    def test_unknown_student_has_no_schedule(self):
        app = create_app(self.service, {"unregistered-token": "unknown@example.test"})
        with TestClient(app) as client:
            response = client.get(
                "/api/me/schedule",
                params=self.dates,
                headers={"Authorization": "Bearer unregistered-token"},
            )
        self.assertEqual(response.status_code, 404)
        self.service.get_schedule.assert_not_called()

    def test_upstream_errors_are_not_reported_as_empty_schedule(self):
        for error in (SourceUnavailable("private upstream info"), InvalidPayload("private data")):
            with self.subTest(error=type(error).__name__):
                self.service.get_schedule.side_effect = error
                response = self.client.get(
                    "/api/me/schedule", params=self.dates, headers=self.headers
                )
                self.assertEqual(response.status_code, 502)
                self.assertNotIn("lessons", response.json())
                self.assertNotIn("private", response.text)

    def test_configuration_error_is_controlled(self):
        self.service.get_schedule.side_effect = ConfigurationError("secret configuration")
        response = self.client.get("/api/me/schedule", params=self.dates, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.text)

    def test_invalid_token_configuration_is_rejected(self):
        for tokens in ({"": "alice@example.test"}, {"token": ""}, {None: "alice@example.test"}):
            with self.subTest(tokens=tokens):
                with self.assertRaises(ConfigurationError):
                    create_app(self.service, tokens)

    def test_host_can_use_verified_session_instead_of_bearer(self):
        self.app.dependency_overrides[self.app.state.account_dependency] = lambda: "bob@example.test"
        response = self.client.get("/api/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "bob@example.test")


class DemoIntegrationTests(unittest.TestCase):
    def test_personal_timetables_share_lectures_and_keep_seminars_separate(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        service = ScheduleService(
            StudentDirectory.from_file(examples / "students.json"),
            FixtureSource(examples / "lessons.json"),
        )
        app = create_app(
            service,
            {
                "anna-demo": "anna@demo-university.test",
                "boris-demo": "boris@demo-university.test",
            },
            demo=True,
        )
        schedules = {}
        with TestClient(app) as client:
            for account in ("anna", "boris"):
                response = client.get(
                    "/api/me/schedule",
                    params={"start": "2026-11-09", "finish": "2026-11-15"},
                    headers={"Authorization": f"Bearer {account}-demo"},
                )
                self.assertEqual(response.status_code, 200)
                schedules[account] = response.json()

        alice = {lesson["source_lesson_id"] for lesson in schedules["anna"]["lessons"]}
        bob = {lesson["source_lesson_id"] for lesson in schedules["boris"]["lessons"]}
        self.assertEqual(alice & bob, {"90001", "90004"})
        self.assertEqual(alice - bob, {"90002", "90005"})
        self.assertEqual(bob - alice, {"90003", "90006"})
        for account, body in schedules.items():
            self.assertEqual(body["student"]["email"], f"{account}@demo-university.test")
            self.assertTrue(body["demo"])
            self.assertEqual(len(body["lessons"]), 4)
            self.assertTrue(body["lessons"][0]["starts_at"].endswith("+03:00"))


if __name__ == "__main__":
    unittest.main()
