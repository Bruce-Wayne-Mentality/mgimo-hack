"""Timetable sources and personal schedule selection."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

from .directory import StudentDirectory
from .errors import ConfigurationError
from .models import Lesson
from .parser import parse_lessons
from .validation import normalize_oid, validate_date_range


class ScheduleSource(Protocol):
    def schedule(
        self,
        *,
        start: date,
        finish: date,
        student_oid: str | None = None,
        group_oid: str | None = None,
    ) -> tuple[Lesson, ...]: ...


class ScheduleService:
    def __init__(self, directory: StudentDirectory, source: ScheduleSource) -> None:
        self.directory = directory
        self.source = source
        self.timezone = getattr(source, "timezone", "Europe/Moscow")

    def get_schedule(self, email: str, start: date, finish: date) -> tuple[Lesson, ...]:
        validate_date_range(start, finish)
        student = self.directory.get(email)
        lessons: set[Lesson] = set()
        if student.student_oid is not None:
            lessons.update(
                self.source.schedule(start=start, finish=finish, student_oid=student.student_oid)
            )
        else:
            for group_oid in student.group_oids:
                lessons.update(self.source.schedule(start=start, finish=finish, group_oid=group_oid))
            # A source may expand an academic group to alternative teaching
            # groups. Keep only the student's explicit assignments, including
            # assignments appearing in another selected group's response.
            assigned = set(student.group_oids)
            lessons = {
                lesson for lesson in lessons
                if any(group.oid in assigned for group in lesson.groups)
            }
        return tuple(
            sorted(
                (lesson for lesson in lessons if start <= lesson.date <= finish),
                key=lambda lesson: (lesson.starts_at, lesson.ends_at, lesson.title, lesson.id),
            )
        )


class FixtureSource:
    """Offline teaching-group source; its data is explicitly synthetic in the demo."""

    def __init__(self, path: str | Path, timezone: str = "Europe/Moscow") -> None:
        self.timezone = timezone
        self.path = Path(path)
        self._lessons = self._load()

    def _payload(self) -> object:
        try:
            return json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Не удалось прочитать файл занятий: {exc}") from exc

    def _load(self) -> tuple[Lesson, ...]:
        return parse_lessons(self._payload(), timezone=self.timezone)

    def schedule(
        self,
        *,
        start: date,
        finish: date,
        student_oid: str | None = None,
        group_oid: str | None = None,
    ) -> tuple[Lesson, ...]:
        validate_date_range(start, finish)
        if student_oid is not None:
            raise ConfigurationError("Файловый источник поддерживает только явные учебные группы")
        if group_oid is None:
            raise ConfigurationError("Для файлового источника требуется group_oid")
        oid = normalize_oid(group_oid)
        # Re-read local exports so the background monitor sees office edits.
        lessons = self._load()
        return tuple(
            lesson
            for lesson in lessons
            if start <= lesson.date <= finish and any(group.oid == oid for group in lesson.groups)
        )


class WeeklyDemoSource(FixtureSource):
    """Repeat a synthetic teaching week for the demo, independently of today.

    Source exports keep their exact dates in FixtureSource. Only --demo uses
    this adapter: weekdays and times are projected onto the requested dates,
    then parsed normally so occurrence IDs remain stable across restarts.
    """

    def schedule(
        self,
        *,
        start: date,
        finish: date,
        student_oid: str | None = None,
        group_oid: str | None = None,
    ) -> tuple[Lesson, ...]:
        validate_date_range(start, finish)
        if student_oid is not None:
            raise ConfigurationError("Демонстрационный источник поддерживает только учебные группы")
        if group_oid is None:
            raise ConfigurationError("Для демонстрационного источника требуется group_oid")
        oid = normalize_oid(group_oid)
        payload = self._payload()
        templates = parse_lessons(payload, timezone=self.timezone)
        weeks = {lesson.date - timedelta(days=lesson.date.weekday()) for lesson in templates}
        if len(weeks) > 1:
            raise ConfigurationError("Шаблон деморасписания должен содержать одну учебную неделю")
        rows = payload["Lessons"] if isinstance(payload, dict) else payload
        weekdays = [date.fromisoformat(row["date"].replace(".", "-")).weekday() for row in rows]
        occurrences = []
        for offset in range((finish - start).days + 1):
            day = start + timedelta(days=offset)
            for row, weekday in zip(rows, weekdays):
                if day.weekday() == weekday:
                    occurrences.append({**row, "date": day.isoformat()})
        return tuple(
            lesson for lesson in parse_lessons(occurrences, timezone=self.timezone)
            if any(group.oid == oid for group in lesson.groups)
        )
