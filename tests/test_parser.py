"""Synthetic examples matching the observed public portal field schema."""

import copy
import json
import unittest

from hse_schedule.errors import InvalidPayload
from hse_schedule.parser import parse_groups, parse_lessons


def row(**changes):
    value = {
        "lessonOid": 42,
        "date": "2026.11.09",
        "beginLesson": "09:30",
        "endLesson": "10:50",
        "discipline": "  Математический   анализ\u00a0 ",
        "kindOfWork": "Лекция",
        "lecturer": "Первый Преподаватель",
        "listOfLecturers": [
            {"lecturer": "Второй Преподаватель"},
            {"lecturer": "Первый Преподаватель"},
        ],
        "groupOid": 1000,
        "group": "Группа 1#служебная часть",
        "listGroups": [{"groupOid": 1001, "group": "Группа 2"}],
        "subGroup": None,
        "auditorium": " 101 ",
        "building": "Учебный корпус",
        "url1": "https://example.edu/lecture",
        "url2": None,
    }
    value.update(changes)
    return value


class LessonParserTests(unittest.TestCase):
    def test_public_envelope_preserves_class_details(self):
        lessons = parse_lessons({"Count": 1, "StatusCode": {"Code": 0}, "Lessons": [row()]})
        self.assertEqual(len(lessons), 1)
        lesson = lessons[0]
        self.assertEqual(lesson.title, "Математический анализ")
        self.assertEqual(lesson.starts_at.isoformat(), "2026-11-09T09:30:00+03:00")
        self.assertEqual(lesson.ends_at.isoformat(), "2026-11-09T10:50:00+03:00")
        self.assertEqual(lesson.source_lesson_id, "42")
        self.assertEqual(lesson.teachers, ("Второй Преподаватель", "Первый Преподаватель"))
        self.assertEqual([(g.oid, g.name) for g in lesson.groups], [("1000", "Группа 1"), ("1001", "Группа 2")])
        self.assertEqual(lesson.room, "101")
        self.assertIsNone(lesson.subgroup)
        self.assertEqual(lesson.links, ("https://example.edu/lecture",))
        encoded = json.loads(json.dumps(lesson.to_dict()))
        self.assertEqual(encoded["date"], "2026-11-09")
        self.assertIsInstance(encoded["teachers"], list)
        self.assertIsInstance(encoded["groups"], list)

    def test_raw_array_iso_date_and_scalar_teacher(self):
        lesson = parse_lessons([row(date="2026-11-09", beginLesson="9:30", listOfLecturers=None)])[0]
        self.assertEqual(lesson.teachers, ("Первый Преподаватель",))

    def test_exact_duplicates_removed_but_recurring_and_parallel_events_kept(self):
        original = row()
        tomorrow = row(date="2026.11.10")
        parallel = row(auditorium="202", subGroup="2")
        lessons = parse_lessons([tomorrow, original, copy.deepcopy(original), parallel])
        self.assertEqual(len(lessons), 3)
        self.assertEqual(len({lesson.id for lesson in lessons}), 3)
        self.assertEqual(lessons[-1].date.isoformat(), "2026-11-10")
        self.assertEqual({lesson.source_lesson_id for lesson in lessons}, {"42"})

    def test_id_is_stable_across_response_order(self):
        first = row()
        reordered = dict(reversed(list(first.items())))
        reordered["listOfLecturers"] = list(reversed(first["listOfLecturers"]))
        self.assertEqual(parse_lessons([first])[0].id, parse_lessons([reordered])[0].id)

    def test_optional_fields_and_zero_scalar_group(self):
        lesson = parse_lessons([row(
            groupOid=0, group=None, lecturer=None, listOfLecturers=[],
            kindOfWork=None, auditorium=None, building=None, url1="javascript:alert(1)"
        )])[0]
        self.assertEqual([g.oid for g in lesson.groups], ["1001"])
        self.assertEqual(lesson.teachers, ())
        self.assertEqual(lesson.links, ())
        self.assertIsNone(lesson.room)

    def test_empty_timetable_is_valid(self):
        self.assertEqual(parse_lessons([]), ())
        self.assertEqual(parse_lessons({"Lessons": [], "StatusCode": {"Code": 0}}), ())

    def test_errors_are_not_interpreted_as_empty_timetable(self):
        for value in (
            None, "<html>login</html>", {}, {"error": "unavailable"},
            {"Lessons": None}, {"Lessons": {}}, [None],
            {"Lessons": [], "StatusCode": {"Code": 1}},
            {"Lessons": [], "StatusCode": {"Code": False}},
            {"Lessons": [], "StatusCode": "error"},
        ):
            with self.subTest(value=value), self.assertRaises(InvalidPayload):
                parse_lessons(value)

    def test_invalid_row_fails_whole_response(self):
        invalid = (
            {"discipline": None}, {"discipline": " "},
            {"date": "2026.02.30"}, {"date": "09.11.2026"},
            {"beginLesson": "25:00"}, {"endLesson": "09:00"},
            {"endLesson": "09:30"}, {"beginLesson": None},
            {"listGroups": {}}, {"listOfLecturers": ""},
            {"listOfLecturers": ["name"]}, {"groupOid": True},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(InvalidPayload):
                parse_lessons([row(), row(**changes)])


class GroupParserTests(unittest.TestCase):
    def test_embedded_group_selector_and_html_entities(self):
        html = """<select><option data-groups='[[&quot;БПМИ261&quot;, &quot;88229&quot;],
        [&quot;БПМИ262&quot;, &quot;88230&quot;]]'>1 курс</option>
        <option data-groups='[["БПМИ261", "88229"]]'>duplicate</option></select>"""
        groups = parse_groups(html)
        self.assertEqual([(g.oid, g.name) for g in groups], [("88229", "БПМИ261"), ("88230", "БПМИ262")])

    def test_missing_or_malformed_selector_is_an_error(self):
        for html in (
            "<html>Вход в систему</html>",
            "<option data-groups='broken'>1</option>",
            "<option data-groups='{}'>1</option>",
            "<option data-groups='[[null, 1]]'>1</option>",
        ):
            with self.subTest(html=html), self.assertRaises(InvalidPayload):
                parse_groups(html)


if __name__ == "__main__":
    unittest.main()
