"""Fictional demo curriculum (section 13): disciplines, weekly timetable,
checkpoints and the test students' scores.

One source feeds both the timetable (examples/demo-week.json is generated
from it, see ``demo_week``) and the study records, so the same disciplines
appear on every screen. Dates are offsets from the seeding day, so the demo
always looks current. All names are invented.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")
SEMESTER = "2026-осень"
SEMESTER_LABEL = "Осень 2026"

# Timetable group identifiers of the demo groups (the HSE-style source uses numeric OIDs).
SCHEDULE_OIDS = {"ЭК-25-1": "2510", "ЭК-24-1": "2410", "ПИ-26-1": "2610", "ПИ-25-1": "2520"}

PAIRS = {1: ("09:30", "10:50"), 2: ("11:10", "12:30"), 3: ("13:00", "14:20"), 4: ("14:40", "16:00"), 5: ("16:20", "17:40")}

# (title, weight, max score, due offset in days or None = final date, critical, is_final)
TEMPLATES: dict[str, list[tuple]] = {
    "exam": [
        ("Контрольная работа 1", 15, 20, -43, False, False),
        ("Домашнее задание 1", 10, 10, -29, False, False),
        ("Контрольная работа 2", 15, 20, -8, True, False),
        ("Домашнее задание 2", 10, 10, 2, False, False),
        ("Мини-проект", 10, 10, 16, False, False),
        ("Экзамен", 40, 40, None, True, True),
    ],
    "credit": [
        ("Тест 1", 20, 20, -36, False, False),
        ("Эссе", 20, 20, -15, False, False),
        ("Тест 2", 20, 20, 4, False, False),
        ("Зачётная работа", 40, 40, None, True, True),
    ],
    "diff_credit": [
        ("Кейс 1", 20, 20, -33, False, False),
        ("Презентация проекта", 20, 20, -12, True, False),
        ("Кейс 2", 20, 20, 9, False, False),
        ("Дифференцированный зачёт", 40, 40, None, True, True),
    ],
    "late": [
        ("Реферат", 30, 30, 6, False, False),
        ("Устный опрос", 30, 30, 20, False, False),
        ("Зачёт", 40, 40, None, True, True),
    ],
    "coursework": [
        ("План работы", 10, 10, -40, False, False),
        ("Обзор литературы", 20, 20, -12, True, False),
        ("Черновик", 30, 30, 9, False, False),
        ("Защита", 40, 40, None, True, True),
    ],
}

# slots: (weekday 0=Mon, pair number, kind, room, building)
DISCIPLINES: dict[str, list[dict]] = {
    "ЭК-25-1": [
        {"code": "MICRO", "title": "Микроэкономика", "form": "exam", "template": "exam", "credits": 5,
         "teacher": "Корнилова Тамара Андреевна", "final": 52, "room": "А-301",
         "slots": [(0, 1, "Лекция", "А-301", "Корпус А"), (2, 2, "Семинар", "Б-214", "Корпус Б")]},
        {"code": "ECONOMETRICS", "title": "Эконометрика", "form": "exam", "template": "exam", "credits": 5,
         "teacher": "Веденеев Павел Станиславович", "final": 56, "room": "А-210",
         "slots": [(1, 2, "Лекция", "А-210", "Корпус А"), (3, 3, "Практическое занятие", "Б-118", "Корпус Б")]},
        {"code": "PROB", "title": "Теория вероятностей и статистика", "form": "exam", "template": "exam", "credits": 4,
         "teacher": "Луговая Инна Романовна", "final": 60, "room": "А-301",
         "slots": [(0, 2, "Лекция", "А-210", "Корпус А"), (4, 1, "Семинар", "Б-205", "Корпус Б")]},
        {"code": "FINMARK", "title": "Финансовые рынки и институты", "form": "diff_credit", "template": "diff_credit", "credits": 3,
         "teacher": "Шестаков Денис Маркович", "final": 31, "room": "Б-214",
         "slots": [(1, 3, "Семинар", "Б-214", "Корпус Б"), (2, 1, "Лекция", "А-301", "Корпус А")]},
        {"code": "ENG", "title": "Английский язык (B2)", "form": "credit", "template": "credit", "credits": 3,
         "teacher": "Голубева Светлана Витальевна", "final": 34, "room": "В-402",
         "slots": [(1, 1, "Практическое занятие", "В-402", "Корпус В"), (4, 2, "Практическое занятие", "В-402", "Корпус В")]},
        {"code": "HISTEC", "title": "История экономических учений", "form": "credit", "template": "late", "credits": 2,
         "teacher": "Арсеньев Кирилл Леонидович", "final": 38, "room": "А-210",
         "slots": [(3, 1, "Лекция", "А-210", "Корпус А")]},
    ],
    "ЭК-24-1": [
        {"code": "MACRO2", "title": "Макроэкономика II", "form": "exam", "template": "exam", "credits": 5,
         "teacher": "Тарасевич Глеб Олегович", "final": 53, "room": "А-305",
         "slots": [(0, 2, "Лекция", "А-305", "Корпус А"), (2, 3, "Семинар", "Б-220", "Корпус Б")]},
        {"code": "CORPFIN", "title": "Корпоративные финансы", "form": "exam", "template": "exam", "credits": 5,
         "teacher": "Мельникова Алла Борисовна", "final": 57, "room": "А-305",
         "slots": [(1, 1, "Лекция", "А-305", "Корпус А"), (3, 2, "Семинар", "Б-220", "Корпус Б")]},
        {"code": "MARKETING", "title": "Маркетинг", "form": "diff_credit", "template": "diff_credit", "credits": 3,
         "teacher": "Ракитин Всеволод Ильич", "final": 32, "room": "Б-108",
         "slots": [(0, 3, "Лекция", "А-305", "Корпус А"), (4, 2, "Семинар", "Б-108", "Корпус Б")]},
        {"code": "PYDATA", "title": "Анализ данных на Python", "form": "exam", "template": "exam", "credits": 4,
         "teacher": "Земцов Арсений Дмитриевич", "final": 61, "room": "Б-118",
         "slots": [(1, 3, "Практическое занятие", "Б-118", "Корпус Б"), (3, 4, "Практическое занятие", "Б-118", "Корпус Б")]},
        {"code": "ENGECON", "title": "Английский для экономистов", "form": "credit", "template": "credit", "credits": 3,
         "teacher": "Голубева Светлана Витальевна", "final": 35, "room": "В-405",
         "slots": [(2, 1, "Практическое занятие", "В-405", "Корпус В"), (4, 1, "Практическое занятие", "В-405", "Корпус В")]},
        {"code": "COURSE3", "title": "Курсовая работа", "form": "coursework", "template": "coursework", "credits": 3,
         "teacher": "Мельникова Алла Борисовна", "final": 40, "room": "Б-220",
         "slots": [(3, 5, "Консультация", "Б-220", "Корпус Б")]},
    ],
    "ПИ-26-1": [
        {"code": "CALC", "title": "Математический анализ", "form": "exam", "template": "exam", "credits": 6,
         "teacher": "Соколовский Виктор Аркадьевич", "final": 54, "room": "В-101",
         "slots": [(0, 1, "Лекция", "В-101", "Корпус В"), (2, 1, "Практическое занятие", "В-210", "Корпус В"),
                   (4, 2, "Практическое занятие", "В-210", "Корпус В")]},
        {"code": "LINALG", "title": "Линейная алгебра и геометрия", "form": "exam", "template": "exam", "credits": 5,
         "teacher": "Ершова Наталья Петровна", "final": 59, "room": "В-101",
         "slots": [(1, 1, "Лекция", "В-101", "Корпус В"), (3, 2, "Практическое занятие", "В-212", "Корпус В")]},
        {"code": "PROG", "title": "Основы программирования", "form": "exam", "template": "exam", "credits": 5,
         "teacher": "Бережной Тимур Русланович", "final": 62, "room": "Б-118",
         "slots": [(0, 3, "Лекция", "В-101", "Корпус В"), (1, 3, "Лабораторная работа", "Б-118", "Корпус Б"),
                   (3, 3, "Лабораторная работа", "Б-118", "Корпус Б")]},
        {"code": "DISCR", "title": "Дискретная математика", "form": "credit", "template": "credit", "credits": 4,
         "teacher": "Хоменко Людмила Ивановна", "final": 33, "room": "В-212",
         "slots": [(2, 2, "Семинар", "В-212", "Корпус В"), (4, 1, "Лекция", "В-101", "Корпус В")]},
        {"code": "HISTRU", "title": "История России", "form": "credit", "template": "late", "credits": 2,
         "teacher": "Арсеньев Кирилл Леонидович", "final": 37, "room": "А-210",
         "slots": [(1, 2, "Лекция", "А-210", "Корпус А")]},
        {"code": "ENG1", "title": "Английский язык (B1)", "form": "credit", "template": "credit", "credits": 3,
         "teacher": "Пименова Дарья Сергеевна", "final": 36, "room": "В-404",
         "slots": [(3, 1, "Практическое занятие", "В-404", "Корпус В")]},
    ],
}

# Score fractions for checkpoints already graded, in template order; None = not handed in.
# attendance: (attended, total lessons so far)
SCORES: dict[str, dict[str, dict]] = {
    "student.anna": {
        "MICRO": {"scores": [0.9, 1.0, 0.85], "attendance": (15, 16)},
        "ECONOMETRICS": {"scores": [0.8, 0.9, 0.75], "attendance": (14, 16)},
        "PROB": {"scores": [0.95, 1.0, 0.9], "attendance": (16, 16)},
        "FINMARK": {"scores": [0.85, 0.9], "attendance": (7, 8)},
        "ENG": {"scores": [0.9, 0.95], "attendance": (15, 16)},
        "HISTEC": {"scores": [], "attendance": (8, 8)},
    },
    "student.boris": {
        "MACRO2": {"scores": [0.75, 0.8, 0.7], "attendance": (14, 16)},
        "CORPFIN": {"scores": [0.6, 0.6, 0.6], "attendance": (11, 16)},
        "MARKETING": {"scores": [0.8, 0.85], "attendance": (7, 8)},
        "PYDATA": {"scores": [0.85, 0.9, 0.8], "attendance": (15, 16)},
        "ENGECON": {"scores": [0.8, 0.9], "attendance": (14, 16)},
        "COURSE3": {"scores": [1.0, 0.8], "attendance": (5, 6)},
    },
    "student.vera": {
        "CALC": {"scores": [0.55, 0.6, None], "attendance": (20, 24)},
        "LINALG": {"scores": [0.4, 0.5, 0.45], "attendance": (13, 16)},
        "PROG": {"scores": [0.9, 1.0, 0.95], "attendance": (23, 24)},
        "DISCR": {"scores": [1.0, None], "attendance": (14, 16)},
        "HISTRU": {"scores": [], "attendance": (7, 8)},
        "ENG1": {"scores": [0.85, 0.9], "attendance": (8, 8)},
    },
}

# Previous semesters: (semester_no, label, title, form, credits, mark or None for «зачтено»)
PAST: dict[str, list[tuple]] = {
    "student.anna": [
        (1, "Осень 2025", "Введение в экономику", "exam", 5, 5),
        (1, "Осень 2025", "Математический анализ", "exam", 6, 4),
        (1, "Осень 2025", "Линейная алгебра", "exam", 4, 5),
        (1, "Осень 2025", "История России", "credit", 2, None),
        (1, "Осень 2025", "Английский язык (B1)", "credit", 3, None),
        (2, "Весна 2026", "Макроэкономика I", "exam", 5, 5),
        (2, "Весна 2026", "Математическая статистика", "exam", 4, 5),
        (2, "Весна 2026", "Информатика для экономистов", "diff_credit", 3, 4),
        (2, "Весна 2026", "Философия", "credit", 2, None),
        (2, "Весна 2026", "Английский язык (B1+)", "credit", 3, None),
    ],
    "student.boris": [
        (1, "Осень 2024", "Введение в экономику", "exam", 5, 4),
        (1, "Осень 2024", "Математический анализ", "exam", 6, 3),
        (1, "Осень 2024", "История России", "credit", 2, None),
        (2, "Весна 2025", "Микроэкономика", "exam", 5, 4),
        (2, "Весна 2025", "Линейная алгебра", "exam", 4, 4),
        (2, "Весна 2025", "Информатика", "diff_credit", 3, 5),
        (3, "Осень 2025", "Макроэкономика I", "exam", 5, 4),
        (3, "Осень 2025", "Эконометрика", "exam", 5, 3),
        (3, "Осень 2025", "Теория вероятностей", "exam", 4, 4),
        (4, "Весна 2026", "Финансовый учёт", "exam", 4, 4),
        (4, "Весна 2026", "Мировая экономика", "diff_credit", 3, 4),
        (4, "Весна 2026", "Статистика", "exam", 4, 3),
    ],
}

FIRST_NAMES = ("Алексей", "Мария", "Дмитрий", "Ксения", "Иван", "Полина", "Егор", "Софья", "Никита", "Алиса",
               "Тимофей", "Варвара", "Роман", "Ульяна", "Глеб", "Ева", "Арсений", "Злата", "Матвей", "Милана")
LAST_NAMES = ("Сорокин", "Белова", "Гончаров", "Яковлева", "Фролов", "Киселёва", "Лапин", "Орлова", "Зуев",
              "Воронцова", "Мартынов", "Комарова", "Ширяев", "Тихонова", "Блинов", "Савельева", "Крылов", "Ермакова")


def background_students(group_code: str, count: int = 10) -> list[dict]:
    """Deterministic fictional classmates for the staff gradebook and queue."""
    rng = random.Random(f"bg-{group_code}")
    rows = []
    used: set[str] = set()
    for index in range(count):
        while True:
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            # Russian surnames agree with the first name's gender.
            female = first.endswith("а") or first.endswith("я") or first in ("Ева",)
            if female and not last.endswith("а"):
                last = last + "а" if not last.endswith("ий") else last[:-2] + "ая"
            if not female and last.endswith("а"):
                last = last[:-1]
            name = f"{last} {first}"
            if name not in used:
                used.add(name)
                break
        quality = rng.uniform(0.5, 1.0)
        rows.append({
            "login": f"bg.{SCHEDULE_OIDS[group_code]}.{index + 1:02d}",
            "full_name": name,
            "record_book_no": f"DEMO-{SCHEDULE_OIDS[group_code]}{index + 1:02d}",
            "email": f"bg.{SCHEDULE_OIDS[group_code]}.{index + 1:02d}@demo-university.test",
            "quality": quality,
            "seed": rng.random(),
        })
    return rows


def checkpoint_rows(discipline: dict, today: date) -> list[dict]:
    final_day = today + timedelta(days=discipline["final"])
    rows = []
    for sort, (title, weight, max_score, offset, critical, is_final) in enumerate(TEMPLATES[discipline["template"]]):
        due = final_day if offset is None else today + timedelta(days=offset)
        rows.append({"title": title, "weight": weight, "max_score": max_score, "due_on": due,
                     "critical": critical, "is_final": is_final, "sort": sort})
    return rows


def final_at(discipline: dict, today: date) -> datetime:
    day = today + timedelta(days=discipline["final"])
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, time(10, 0), tzinfo=MOSCOW).astimezone(timezone.utc)


def demo_week() -> dict:
    """The weekly timetable template in the HSE source format (examples/demo-week.json)."""
    monday = date(2026, 11, 16)
    lessons = []
    oid = 300000
    for group_code, disciplines in DISCIPLINES.items():
        for discipline in disciplines:
            for weekday, pair, kind, room, building in discipline["slots"]:
                oid += 1
                begin, end = PAIRS[pair]
                group = {"groupOid": int(SCHEDULE_OIDS[group_code]), "group": group_code}
                lessons.append({
                    "lessonOid": oid,
                    "date": (monday + timedelta(days=weekday)).strftime("%Y.%m.%d"),
                    "beginLesson": begin,
                    "endLesson": end,
                    "discipline": discipline["title"],
                    "kindOfWork": kind,
                    "lecturer": discipline["teacher"],
                    "listOfLecturers": [{"lecturer": discipline["teacher"]}],
                    "groupOid": group["groupOid"],
                    "group": group_code,
                    "listGroups": [group],
                    "auditorium": room,
                    "building": f"{building} (вымышленный)",
                    "subGroup": "",
                    "url1": "",
                    "url2": "",
                })
    lessons.sort(key=lambda row: (row["date"], row["beginLesson"], row["group"]))
    return {"Count": len(lessons), "StatusCode": {"Code": 0, "Description": "OK"}, "Lessons": lessons}


def demo_students() -> dict:
    return {
        "students": [
            {"email": "anna@demo-university.test", "name": "Анна Миронова", "group_oids": [SCHEDULE_OIDS["ЭК-25-1"]]},
            {"email": "boris@demo-university.test", "name": "Борис Лебедев", "group_oids": [SCHEDULE_OIDS["ЭК-24-1"]]},
            {"email": "vera@demo-university.test", "name": "Вера Кузнецова", "group_oids": [SCHEDULE_OIDS["ПИ-26-1"]]},
        ]
    }


if __name__ == "__main__":  # python -m hse_schedule.academics.curriculum
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "examples"
    (root / "demo-week.json").write_text(json.dumps(demo_week(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "demo-students.json").write_text(json.dumps(demo_students(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("examples/demo-week.json and examples/demo-students.json written")
