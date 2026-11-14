from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from hse_schedule.directory import Student, StudentDirectory
from hse_schedule.errors import ConfigurationError, UnknownStudent
from hse_schedule.models import Group, Lesson
from hse_schedule.service import FixtureSource, ScheduleService


ROOT = Path(__file__).resolve().parents[1]
START = date(2026, 11, 9)
FINISH = date(2026, 11, 15)


def lesson(identifier: str, *, day: date = START, group: str = "1000") -> Lesson:
    starts = datetime(day.year, day.month, day.day, 9, 30, tzinfo=timezone(timedelta(hours=3)))
    return Lesson(
        id=identifier,
        date=day,
        starts_at=starts,
        ends_at=starts + timedelta(minutes=80),
        title="Демо",
        kind="Лекция",
        teachers=("Демо",),
        groups=(Group(oid=group, name="Демо"),),
        subgroup=None,
        room="101",
        building="Демо",
        links=(),
        source_lesson_id=identifier,
    )


class FakeSource:
    def __init__(self, responses: dict[str, tuple[Lesson, ...]]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def schedule(self, **kwargs) -> tuple[Lesson, ...]:
        self.calls.append(kwargs)
        return self.responses[kwargs.get("student_oid") or kwargs["group_oid"]]


class DirectoryTests(unittest.TestCase):
    def test_email_is_normalized_and_unknown_account_rejected(self):
        directory = StudentDirectory([Student(" Anna@Example.EDU ", "Анна", group_oids=("1000",))])
        self.assertEqual(directory.get("ANNA@example.edu ").email, "anna@example.edu")
        for email in ("missing@example.edu", "", "not-an-email"):
            with self.subTest(email=email), self.assertRaises(UnknownStudent):
                directory.get(email)

    def test_duplicate_normalized_email_is_configuration_error(self):
        with self.assertRaises(ConfigurationError):
            StudentDirectory([
                Student("anna@example.edu", "Анна", group_oids=("1000",)),
                Student("ANNA@example.edu ", "Другая Анна", student_oid="123"),
            ])

    def test_individual_or_group_mapping_must_be_explicit(self):
        for student in (
            Student("anna@example.edu", "Анна"),
            Student("anna@example.edu", "Анна", student_oid="123", group_oids=("1000",)),
            Student("invalid", "Анна", group_oids=("1000",)),
            Student("anna@example.edu", "Анна", group_oids="1000"),
            Student("anna@example.edu", "Анна", group_oids=(True,)),
        ):
            with self.subTest(student=student), self.assertRaises(ConfigurationError):
                StudentDirectory([student])

    def test_invalid_file_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "roster.json"
            for payload in ([], {"students": {}}, {"students": [None]}, {"students": [{"email": "invalid"}]}):
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.subTest(payload=payload), self.assertRaises(ConfigurationError):
                    StudentDirectory.from_file(path)


class ServiceTests(unittest.TestCase):
    def test_student_oid_is_used_without_group_requests(self):
        directory = StudentDirectory([Student("anna@example.edu", "Анна", student_oid="123")])
        item = lesson("individual")
        source = FakeSource({"123": (item,)})
        result = ScheduleService(directory, source).get_schedule("anna@example.edu", START, FINISH)
        self.assertEqual(result, (item,))
        self.assertEqual(source.calls, [{"start": START, "finish": FINISH, "student_oid": "123"}])

    def test_groups_are_personal_and_duplicates_removed(self):
        shared = lesson("shared")
        personal = lesson("personal", day=START + timedelta(days=1), group="1001")
        source = FakeSource({"1000": (shared,), "1001": (personal, shared), "1002": ()})
        directory = StudentDirectory([
            Student("anna@example.edu", "Анна", group_oids=("1000", "1001")),
            Student("boris@example.edu", "Борис", group_oids=("1000", "1002")),
        ])
        service = ScheduleService(directory, source)
        self.assertIs(service.directory, directory)
        self.assertEqual(service.get_schedule("anna@example.edu", START, FINISH), (shared, personal))
        self.assertEqual(service.get_schedule("boris@example.edu", START, FINISH), (shared,))

    def test_group_response_cannot_add_unassigned_or_ambiguous_lessons(self):
        shared = lesson("shared")
        personal = lesson("personal", day=START + timedelta(days=1), group="1001")
        other_student = lesson("other-student", group="1002")
        missing_membership = replace(lesson("no-group"), groups=())
        # The first source request returns an expanded academic schedule.
        source = FakeSource({
            "1000": (shared, personal, other_student, missing_membership),
            "1001": (),
        })
        directory = StudentDirectory([
            Student("anna@example.edu", "Анна", group_oids=("1000", "1001")),
        ])
        result = ScheduleService(directory, source).get_schedule("anna@example.edu", START, FINISH)
        self.assertEqual(result, (shared, personal))

    def test_personal_student_source_does_not_require_group_metadata(self):
        personal = replace(lesson("personal"), groups=())
        source = FakeSource({"123": (personal,)})
        directory = StudentDirectory([
            Student("anna@example.edu", "Анна", student_oid="123"),
        ])
        self.assertEqual(
            ScheduleService(directory, source).get_schedule("anna@example.edu", START, FINISH),
            (personal,),
        )

    def test_invalid_range_does_not_call_source(self):
        directory = StudentDirectory([Student("anna@example.edu", "Анна", student_oid="123")])
        source = FakeSource({"123": ()})
        service = ScheduleService(directory, source)
        for start, finish in ((FINISH, START), (START, START + timedelta(days=31))):
            with self.subTest(start=start, finish=finish), self.assertRaises(ValueError):
                service.get_schedule("anna@example.edu", start, finish)
        self.assertEqual(source.calls, [])
        self.assertEqual(service.get_schedule("anna@example.edu", START, START + timedelta(days=30)), ())

    def test_unknown_account_does_not_call_source(self):
        source = FakeSource({})
        with self.assertRaises(UnknownStudent):
            ScheduleService(StudentDirectory([]), source).get_schedule("unknown@example.edu", START, FINISH)
        self.assertEqual(source.calls, [])

    def test_out_of_range_results_are_excluded(self):
        inside = lesson("inside")
        outside = lesson("outside", day=FINISH + timedelta(days=1))
        source = FakeSource({"123": (outside, inside)})
        directory = StudentDirectory([Student("anna@example.edu", "Анна", student_oid="123")])
        self.assertEqual(ScheduleService(directory, source).get_schedule("anna@example.edu", START, FINISH), (inside,))

    def test_repeated_source_oid_with_different_dates_is_not_removed(self):
        first = lesson("source-id", day=START)
        second = lesson("source-id", day=START + timedelta(days=1))
        source = FakeSource({"123": (second, first)})
        directory = StudentDirectory([Student("anna@example.edu", "Анна", student_oid="123")])
        self.assertEqual(ScheduleService(directory, source).get_schedule("anna@example.edu", START, FINISH), (first, second))


class FixtureTests(unittest.TestCase):
    def test_demo_students_share_lectures_but_not_seminars(self):
        directory = StudentDirectory.from_file(ROOT / "examples/students.json")
        service = ScheduleService(directory, FixtureSource(ROOT / "examples/lessons.json"))
        anna = service.get_schedule("anna@demo-university.test", START, FINISH)
        boris = service.get_schedule("boris@demo-university.test", START, FINISH)
        self.assertEqual(len(anna), 4)
        self.assertEqual(len(boris), 4)
        self.assertEqual(len(set(anna) & set(boris)), 2)
        self.assertEqual({group.oid for item in anna for group in item.groups}, {"1000", "1001"})
        self.assertEqual({group.oid for item in boris for group in item.groups}, {"1000", "1002"})

    def test_fixture_filters_dates_and_rejects_student_oid(self):
        source = FixtureSource(ROOT / "examples/lessons.json")
        self.assertEqual(source.schedule(start=START, finish=START, group_oid="1002"), ())
        with self.assertRaises(ConfigurationError):
            source.schedule(start=START, finish=FINISH, student_oid="123")


if __name__ == "__main__":
    unittest.main()
