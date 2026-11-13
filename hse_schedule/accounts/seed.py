"""Fictional demo data: faculties, groups and the jury test accounts (section 13.1).

Passwords below are deliberately public demo values (section 10.3, item 5).
The database stores only their argon2id hashes, produced when seeding.
"""

from __future__ import annotations

from sqlalchemy import func, select

from ..db import Database
from .models import Faculty, Staff, Student, StudyGroup, User
from .security import hash_password

FACULTIES = (
    {"code": "ECON", "title": "Факультет экономики и управления"},
    {"code": "IT", "title": "Факультет информационных технологий"},
)

GROUPS = (
    {"code": "ЭК-25-1", "faculty": "ECON", "course": 2, "program_code": "38.03.01", "program_title": "Экономика"},
    {"code": "ЭК-24-1", "faculty": "ECON", "course": 3, "program_code": "38.03.01", "program_title": "Экономика"},
    {"code": "ПИ-26-1", "faculty": "IT", "course": 1, "program_code": "09.03.04", "program_title": "Программная инженерия"},
    {"code": "ПИ-25-1", "faculty": "IT", "course": 2, "program_code": "09.03.04", "program_title": "Программная инженерия"},
)

STUDENTS = (
    {"login": "student.anna", "password": "Demo-Anna-2026", "full_name": "Анна Сергеевна Миронова",
     "group": "ЭК-25-1", "record_book_no": "DEMO-250114", "email": "anna@demo-university.test",
     "phone": "+7 900 000-00-01", "description": "Студент А · 2 курс"},
    {"login": "student.boris", "password": "Demo-Boris-2026", "full_name": "Борис Андреевич Лебедев",
     "group": "ЭК-24-1", "record_book_no": "DEMO-240327", "email": "boris@demo-university.test",
     "phone": None, "description": "Студент Б · 3 курс"},
    {"login": "student.vera", "password": "Demo-Vera-2026", "full_name": "Вера Олеговна Кузнецова",
     "group": "ПИ-26-1", "record_book_no": "DEMO-260502", "email": "vera@demo-university.test",
     "phone": None, "description": "Студент В · 1 курс"},
)

STAFF = (
    {"login": "staff.deanery", "password": "Demo-Staff-2026", "role": "staff",
     "full_name": "Ольга Викторовна Демченко", "position": "Специалист деканата", "faculty": "ECON",
     "scopes": ["CERT_STUDY", "CERT_INTERN", "CERT_MIL", "TRANSCRIPT", "ACAD_LEAVE"],
     "description": "Сотрудник деканата"},
    {"login": "admin.demo", "password": "Demo-Admin-2026", "role": "admin",
     "full_name": "Администратор демо", "position": "Администратор системы", "faculty": None,
     "scopes": [], "description": "Администратор"},
)

DEMO_ACCOUNTS = tuple(
    {"login": row["login"], "password": row["password"], "description": row["description"]}
    for row in (*STUDENTS, *STAFF)
)


async def seed_demo(database: Database) -> dict[str, int]:
    """Create missing demo rows; existing accounts and their passwords are kept."""
    created = {"faculties": 0, "groups": 0, "users": 0}
    async with database.session() as db:
        faculties = {row.code: row for row in (await db.scalars(select(Faculty))).all()}
        for data in FACULTIES:
            if data["code"] not in faculties:
                faculties[data["code"]] = Faculty(**data)
                db.add(faculties[data["code"]])
                created["faculties"] += 1
        await db.flush()

        groups = {row.code: row for row in (await db.scalars(select(StudyGroup))).all()}
        for data in GROUPS:
            if data["code"] not in groups:
                values = {key: value for key, value in data.items() if key != "faculty"}
                groups[data["code"]] = StudyGroup(faculty_id=faculties[data["faculty"]].id, **values)
                db.add(groups[data["code"]])
                created["groups"] += 1
        await db.flush()

        existing = set((await db.scalars(select(func.lower(User.login)))).all())
        for data in STUDENTS:
            if data["login"] in existing:
                continue
            user = User(login=data["login"], password_hash=hash_password(data["password"]), role="student")
            db.add(user)
            await db.flush()
            db.add(Student(
                user_id=user.id, full_name=data["full_name"], record_book_no=data["record_book_no"],
                group_id=groups[data["group"]].id, email=data["email"], phone=data["phone"],
            ))
            created["users"] += 1
        for data in STAFF:
            if data["login"] in existing:
                continue
            user = User(login=data["login"], password_hash=hash_password(data["password"]), role=data["role"])
            db.add(user)
            await db.flush()
            db.add(Staff(
                user_id=user.id, full_name=data["full_name"], position=data["position"],
                faculty_id=faculties[data["faculty"]].id if data["faculty"] else None, scopes=data["scopes"],
            ))
            created["users"] += 1
        await db.commit()
    return created
