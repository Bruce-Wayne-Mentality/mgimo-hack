"""Parse the JSON and group selectors used by the public HSE portal."""

import hashlib
import json
import re
from dataclasses import replace
from datetime import date, datetime, time
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from .errors import InvalidPayload
from .models import Group, Lesson
from .validation import normalize_oid


def _text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidPayload("Ожидалось текстовое поле расписания.")
    return " ".join(value.split()) or None


def _oid(value: object) -> str:
    try:
        return normalize_oid(value)
    except ValueError as exc:
        raise InvalidPayload(str(exc)) from exc


def _objects(row: dict, key: str) -> list[dict]:
    values = row.get(key)
    if values is None:
        return []
    if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
        raise InvalidPayload(f"Поле {key} должно быть списком объектов.")
    return values


def _groups(row: dict) -> tuple[Group, ...]:
    values = list(_objects(row, "listGroups"))
    if row.get("groupOid") not in (None, 0, "0"):
        values.append({"groupOid": row["groupOid"], "group": row.get("group")})
    groups: dict[str, Group] = {}
    for value in values:
        oid = _oid(value.get("groupOid"))
        name = (_text(value.get("group")) or "").split("#", 1)[0]
        if oid not in groups or (not groups[oid].name and name):
            groups[oid] = Group(oid, name)
    return tuple(sorted(groups.values(), key=lambda g: (int(g.oid), g.name)))


def _lesson(row: dict, timezone: ZoneInfo) -> Lesson:
    title = _text(row.get("discipline"))
    if not title:
        raise InvalidPayload("В занятии отсутствует название discipline.")
    raw_date = row.get("date")
    try:
        if not isinstance(raw_date, str) or not re.fullmatch(
            r"\d{4}([.-])\d{2}\1\d{2}", raw_date
        ):
            raise ValueError("date")
        lesson_date = date.fromisoformat(raw_date.replace(".", "-"))
        times = []
        for key in ("beginLesson", "endLesson"):
            value = row.get(key)
            if not isinstance(value, str) or not re.fullmatch(r"\d{1,2}:\d{2}", value):
                raise ValueError(key)
            hour, minute = map(int, value.split(":"))
            times.append(datetime.combine(lesson_date, time(hour, minute), timezone))
        start, end = times
        if end <= start:
            raise ValueError("endLesson <= beginLesson")
    except ValueError as exc:
        raise InvalidPayload("Некорректная дата или время занятия.") from exc

    teachers = {
        name
        for value in _objects(row, "listOfLecturers")
        if (name := _text(value.get("lecturer")))
    }
    # HSE sometimes supplies only the scalar lecturer, sometimes a full list.
    if not teachers and (name := _text(row.get("lecturer"))):
        teachers.add(name)
    links = tuple(
        sorted(
            {
                url
                for key in ("url1", "url2")
                if (url := _text(row.get(key)))
                and re.match(r"^https?://[^\s/]+", url, flags=re.IGNORECASE)
            }
        )
    )
    source_id = row.get("lessonOid")
    lesson = Lesson(
        id="",
        date=lesson_date,
        starts_at=start,
        ends_at=end,
        title=title,
        kind=_text(row.get("kindOfWork")),
        teachers=tuple(sorted(teachers)),
        groups=_groups(row),
        subgroup=_text(row.get("subGroup")),
        room=_text(row.get("auditorium")),
        building=_text(row.get("building")),
        links=links,
        source_lesson_id=_oid(source_id) if source_id is not None else None,
    )
    # Include all visible fields: recurring source IDs and simultaneous
    # subgroup/teacher variants must remain separate events.
    fingerprint = json.dumps(lesson.to_dict(), ensure_ascii=False, sort_keys=True)
    return replace(lesson, id=hashlib.sha256(fingerprint.encode()).hexdigest()[:24])


def parse_lessons(payload: object, *, timezone: str = "Europe/Moscow") -> tuple[Lesson, ...]:
    """Normalize either a RUZ array or the portal's Lessons/StatusCode envelope.

    A broken response raises an error; it never becomes an empty timetable.
    """
    if isinstance(payload, dict):
        status = payload.get("StatusCode")
        if status is not None and (
            not isinstance(status, dict)
            or type(status.get("Code")) is not int
            or status["Code"] != 0
        ):
            raise InvalidPayload("Источник расписания вернул ошибку StatusCode.")
        rows = payload.get("Lessons")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise InvalidPayload("Ожидался массив занятий или объект с массивом Lessons.")
    zone = ZoneInfo(timezone)
    lessons: dict[str, Lesson] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise InvalidPayload(f"Занятие #{index + 1} должно быть объектом.")
        try:
            lesson = _lesson(row, zone)
        except InvalidPayload as exc:
            raise InvalidPayload(f"Занятие #{index + 1}: {exc}") from exc
        lessons[lesson.id] = lesson
    return tuple(sorted(lessons.values(), key=lambda x: (x.starts_at, x.ends_at, x.title, x.id)))


class _GroupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.groups: dict[str, Group] = {}
        self.found_selector = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag != "option" or "data-groups" not in values:
            return
        self.found_selector = True
        try:
            rows = json.loads(values["data-groups"] or "")
        except ValueError as exc:
            raise InvalidPayload("Некорректный JSON в селекторе групп ВШЭ.") from exc
        if not isinstance(rows, list):
            raise InvalidPayload("Селектор групп должен содержать массив.")
        for row in rows:
            if not isinstance(row, list) or len(row) != 2 or not (name := _text(row[0])):
                raise InvalidPayload("Некорректная запись группы ВШЭ.")
            oid = _oid(row[1])
            self.groups[oid] = Group(oid=oid, name=name)


def parse_groups(html: str) -> tuple[Group, ...]:
    """Read the [name, OID] lists embedded in a programme timetable page."""
    parser = _GroupParser()
    parser.feed(html)
    if not parser.found_selector:
        raise InvalidPayload("На странице не найден селектор групп ВШЭ.")
    return tuple(sorted(parser.groups.values(), key=lambda g: (g.name, int(g.oid))))
