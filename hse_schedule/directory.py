"""Explicit mapping from a university account to its personal timetable."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable

from .errors import ConfigurationError, UnknownStudent
from .validation import normalize_oid


_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")


def _email(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("email должен быть строкой")
    normalized = value.strip().casefold()
    if not _EMAIL.fullmatch(normalized):
        raise ValueError("неверный email")
    return normalized


@dataclass(frozen=True)
class Student:
    email: str
    name: str
    student_oid: str | None = None
    group_oids: tuple[str, ...] = ()


class StudentDirectory:
    """Roster supplied by the academic office, never inferred from the email."""

    def __init__(self, students: Iterable[Student]) -> None:
        indexed: dict[str, Student] = {}
        for index, student in enumerate(students, start=1):
            try:
                email = _email(student.email)
                if not isinstance(student.name, str) or not student.name.strip():
                    raise ValueError("name должен быть непустой строкой")
                student_oid = (
                    normalize_oid(student.student_oid)
                    if student.student_oid is not None
                    else None
                )
                if not isinstance(student.group_oids, (list, tuple)):
                    raise ValueError("group_oids должен быть списком идентификаторов")
                group_oids = tuple(dict.fromkeys(normalize_oid(oid) for oid in student.group_oids))
                if bool(student_oid) == bool(group_oids):
                    raise ValueError("задайте либо student_oid, либо непустой group_oids")
                if email in indexed:
                    raise ValueError("email встречается несколько раз")
            except (TypeError, ValueError) as exc:
                raise ConfigurationError(f"Ошибка записи студента #{index}: {exc}") from exc
            indexed[email] = Student(email, student.name.strip(), student_oid, group_oids)
        self._students = MappingProxyType(indexed)

    @classmethod
    def from_file(cls, path: str | Path) -> StudentDirectory:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Не удалось прочитать справочник студентов: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("students"), list):
            raise ConfigurationError('Справочник должен содержать объект с массивом "students"')
        students: list[Student] = []
        for index, row in enumerate(payload["students"], start=1):
            if not isinstance(row, dict):
                raise ConfigurationError(f"Запись студента #{index} должна быть объектом")
            students.append(
                Student(
                    email=row.get("email"),
                    name=row.get("name"),
                    student_oid=row.get("student_oid"),
                    group_oids=row.get("group_oids", ()),
                )
            )
        return cls(students)

    def get(self, email: str) -> Student:
        try:
            normalized = _email(email)
            return self._students[normalized]
        except (ValueError, KeyError) as exc:
            raise UnknownStudent("Для этого аккаунта не настроено персональное расписание") from exc

    def list_students(self) -> tuple[Student, ...]:
        """Iterate trusted enrollments for background timetable refreshes."""
        return tuple(self._students[key] for key in sorted(self._students))
